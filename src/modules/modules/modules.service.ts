import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import { MaterialEntity } from '../../database/entities/material.entity.js';
import { CreateModuleDto } from './dto/create-module.dto.js';
import { UpdateModuleDto } from './dto/update-module.dto.js';
import { QueryModulesDto } from './dto/query-modules.dto.js';
import { OwuiService } from '../owui/owui.service.js';
import { PipelineService } from '../pipeline/pipeline.service.js';

@Injectable()
export class ModulesService {
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

    qb.orderBy('module.order_index', 'ASC').addOrderBy('module.created_at', 'ASC');

    const page = query.page || 1;
    const limit = query.limit || 20;
    qb.skip((page - 1) * limit).take(limit);

    const [items, total] = await qb.getManyAndCount();

    // Attach materials statistics for each module
    const enhancedItems = await Promise.all(
      items.map(async (mod: ModuleEntity) => {
        const materialsStats = await this.materialRepo
          .createQueryBuilder('mat')
          .innerJoin('mat.topic', 'top')
          .where('top.module_id = :moduleId', { moduleId: mod.id })
          .select('mat.status', 'status')
          .addSelect('COUNT(mat.id)', 'count')
          .groupBy('mat.status')
          .getRawMany();

        const stats: Record<string, number> = {};
        let totalMaterials = 0;
        for (const row of materialsStats) {
          const count = parseInt(row.count, 10);
          stats[row.status] = count;
          totalMaterials += count;
        }

        (mod as any).topicsCount = mod.topics ? mod.topics.length : 0;
        (mod as any).materialsCount = totalMaterials;
        (mod as any).materialsByStatus = stats;
        return mod;
      }),
    );

    return {
      items: enhancedItems,
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
    materials: Array<{ id: string; filename: string }>;
  }> {
    const mod = await this.findOne(id);

    const materials = await this.materialRepo
      .createQueryBuilder('mat')
      .innerJoin('mat.topic', 'top')
      .where('top.module_id = :moduleId', { moduleId: mod.id })
      .getMany();

    // Run processing asynchronously in background for each material
    for (const material of materials) {
      this.pipelineService.processMaterial(material.id).catch(() => {});
    }

    return {
      moduleId: mod.id,
      totalQueued: materials.length,
      materials: materials.map((m) => ({
        id: m.id,
        filename: m.original_filename,
      })),
    };
  }
}
