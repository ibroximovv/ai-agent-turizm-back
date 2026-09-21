import {
  BadRequestException,
  ConflictException,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { In, Repository } from 'typeorm';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import {
  MaterialEntity,
  MaterialStatus,
} from '../../database/entities/material.entity.js';
import { CreateModuleDto } from './dto/create-module.dto.js';
import { UpdateModuleDto } from './dto/update-module.dto.js';
import { QueryModulesDto } from './dto/query-modules.dto.js';
import { OwuiService } from '../owui/owui.service.js';
import { PipelineService } from '../pipeline/pipeline.service.js';

/**
 * How many materials of a batch are converted at the same time. Parsing keeps
 * whole documents in memory, so an unbounded fan-out over a large module would
 * exhaust the heap.
 */
const BATCH_CONCURRENCY = 2;

interface MaterialStats {
  total: number;
  byStatus: Record<string, number>;
}

@Injectable()
export class ModulesService {
  private readonly logger = new Logger(ModulesService.name);

  constructor(
    @InjectRepository(ModuleEntity)
    private readonly moduleRepo: Repository<ModuleEntity>,
    @InjectRepository(MaterialEntity)
    private readonly materialRepo: Repository<MaterialEntity>,
    private readonly owuiService: OwuiService,
    private readonly pipelineService: PipelineService,
  ) {}

  async findAll(query: QueryModulesDto) {
    const qb = this.moduleRepo
      .createQueryBuilder('module')
      .leftJoinAndSelect('module.topics', 'topics');

    if (query.is_active !== undefined) {
      qb.andWhere('module.is_active = :isActive', {
        isActive: query.is_active,
      });
    }

    if (query.search) {
      qb.andWhere(
        '(module.code ILIKE :search OR module.name ILIKE :search OR module.description ILIKE :search)',
        { search: `%${query.search}%` },
      );
    }

    qb.orderBy('module.order_index', 'ASC').addOrderBy(
      'module.created_at',
      'ASC',
    );

    const page = query.page || 1;
    const limit = query.limit || 20;
    qb.skip((page - 1) * limit).take(limit);

    const [items, total] = await qb.getManyAndCount();

    // Materials statistics for the whole page in one grouped query.
    const statsByModule = await this.materialStats(items.map((m) => m.id));

    for (const mod of items) {
      const stats = statsByModule.get(mod.id);
      Object.assign(mod, {
        topicsCount: mod.topics?.length ?? 0,
        materialsCount: stats?.total ?? 0,
        materialsByStatus: stats?.byStatus ?? {},
      });
    }

    return {
      items,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async findOne(id: string): Promise<ModuleEntity> {
    const mod = await this.moduleRepo.findOne({
      where: { id },
      relations: { topics: true },
      order: {
        topics: {
          order_index: 'ASC',
        },
      },
    });

    if (!mod) {
      throw new NotFoundException(`Module with ID "${id}" not found`);
    }

    return mod;
  }

  async create(dto: CreateModuleDto): Promise<ModuleEntity> {
    const existing = await this.moduleRepo.findOne({
      where: { code: dto.code },
    });
    if (existing) {
      throw new ConflictException(
        `Module with code "${dto.code}" already exists`,
      );
    }

    const mod = this.moduleRepo.create(dto);
    return this.moduleRepo.save(mod);
  }

  async update(id: string, dto: UpdateModuleDto): Promise<ModuleEntity> {
    const mod = await this.findOne(id);

    if (dto.code && dto.code !== mod.code) {
      const existing = await this.moduleRepo.findOne({
        where: { code: dto.code },
      });
      if (existing && existing.id !== id) {
        throw new ConflictException(
          `Module with code "${dto.code}" already exists`,
        );
      }
    }

    Object.assign(mod, dto);
    return this.moduleRepo.save(mod);
  }

  async remove(id: string): Promise<{ success: boolean; message: string }> {
    const mod = await this.findOne(id);
    await this.moduleRepo.remove(mod);
    return {
      success: true,
      message: `Module "${mod.code}" and its related topics/materials deleted successfully`,
    };
  }

  async createOrSyncKb(id: string): Promise<{
    module: ModuleEntity;
    kb: { id: string; name: string };
    created: boolean;
  }> {
    const mod = await this.findOne(id);

    const owuiStatus = await this.owuiService.checkConnection();
    if (!owuiStatus.connected) {
      throw new BadRequestException(
        `Cannot sync with Open WebUI: ${owuiStatus.message}`,
      );
    }

    if (mod.owui_kb_id) {
      try {
        const existingKb = await this.owuiService.getKnowledgeBase(
          mod.owui_kb_id,
        );
        return {
          module: mod,
          kb: existingKb,
          created: false,
        };
      } catch {
        // If not found in OWUI, create a new one
      }
    }

    const newKb = await this.owuiService.createKnowledgeBase(
      `${mod.code} - ${mod.name}`,
      mod.description || mod.name,
    );
    mod.owui_kb_id = newKb.id;
    await this.moduleRepo.save(mod);

    return {
      module: mod,
      kb: newKb,
      created: true,
    };
  }

  async processAllMaterials(id: string): Promise<{
    moduleId: string;
    totalQueued: number;
    skipped: number;
    concurrency: number;
    materials: Array<{ id: string; filename: string }>;
  }> {
    const mod = await this.findOne(id);

    const materials = await this.materialRepo
      .createQueryBuilder('mat')
      .innerJoin('mat.topic', 'top')
      .where('top.module_id = :moduleId', { moduleId: mod.id })
      .orderBy('mat.created_at', 'ASC')
      .getMany();

    // Anything already mid-run is left alone rather than processed twice.
    const queueable = materials.filter(
      (m) => !this.pipelineService.isProcessing(m.id),
    );

    if (queueable.length > 0) {
      await this.materialRepo.update(
        { id: In(queueable.map((m) => m.id)) },
        { status: MaterialStatus.QUEUED, error_message: undefined },
      );
    }

    void this.drainQueue(queueable.map((m) => m.id));

    return {
      moduleId: mod.id,
      totalQueued: queueable.length,
      skipped: materials.length - queueable.length,
      concurrency: BATCH_CONCURRENCY,
      materials: queueable.map((m) => ({
        id: m.id,
        filename: m.original_filename,
      })),
    };
  }

  /**
   * Processes the queue in the background with a fixed number of workers, so a
   * module with hundreds of documents cannot overwhelm the process.
   */
  private async drainQueue(materialIds: string[]): Promise<void> {
    const queue = [...materialIds];

    const worker = async (): Promise<void> => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        try {
          await this.pipelineService.processMaterial(next);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          this.logger.error(`Batch processing failed for ${next}: ${msg}`);
        }
      }
    };

    const workers = Array.from(
      { length: Math.min(BATCH_CONCURRENCY, queue.length) },
      () => worker(),
    );
    await Promise.all(workers);
  }

  /** One grouped query for every module on the page instead of one per module. */
  private async materialStats(
    moduleIds: string[],
  ): Promise<Map<string, MaterialStats>> {
    const result = new Map<string, MaterialStats>();
    if (moduleIds.length === 0) return result;

    const rows = await this.materialRepo
      .createQueryBuilder('mat')
      .innerJoin('mat.topic', 'top')
      .where('top.module_id IN (:...moduleIds)', { moduleIds })
      .select('top.module_id', 'module_id')
      .addSelect('mat.status', 'status')
      .addSelect('COUNT(mat.id)', 'count')
      .groupBy('top.module_id')
      .addGroupBy('mat.status')
      .getRawMany<{ module_id: string; status: string; count: string }>();

    for (const row of rows) {
      const count = Number.parseInt(row.count, 10) || 0;
      const stats = result.get(row.module_id) ?? { total: 0, byStatus: {} };
      stats.byStatus[row.status] = count;
      stats.total += count;
      result.set(row.module_id, stats);
    }

    return result;
  }
}
