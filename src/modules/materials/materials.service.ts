import {
  BadRequestException,
  ConflictException,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as path from 'path';
import {
  buildStoredFilename,
  decodeMultipartFilename,
  sanitizePathSegment,
} from '../../common/filename.js';
import type { UploadsConfig } from '../../config/configuration.js';
import {
  MaterialEntity,
  MaterialStatus,
} from '../../database/entities/material.entity.js';
import { TopicEntity } from '../../database/entities/topic.entity.js';
import { UploadMaterialDto } from './dto/upload-material.dto.js';
import { QueryMaterialsDto } from './dto/query-materials.dto.js';
import { PipelineService } from '../pipeline/pipeline.service.js';
import { OwuiService } from '../owui/owui.service.js';

const ALLOWED_EXTENSIONS = new Set(['.pdf', '.pptx', '.docx', '.txt', '.md']);

@Injectable()
export class MaterialsService {
  private readonly logger = new Logger(MaterialsService.name);

  constructor(
    @InjectRepository(MaterialEntity)
    private readonly materialRepo: Repository<MaterialEntity>,
    @InjectRepository(TopicEntity)
    private readonly topicRepo: Repository<TopicEntity>,
    private readonly pipelineService: PipelineService,
    private readonly owuiService: OwuiService,
    private readonly configService: ConfigService,
  ) {}

  async findAll(query: QueryMaterialsDto) {
    const qb = this.materialRepo
      .createQueryBuilder('material')
      .leftJoinAndSelect('material.topic', 'topic')
      .leftJoinAndSelect('topic.module', 'module');

    if (query.topic_id) {
      qb.andWhere('material.topic_id = :topicId', {
        topicId: query.topic_id,
      });
    }

    if (query.module_id) {
      qb.andWhere('topic.module_id = :moduleId', {
        moduleId: query.module_id,
      });
    }

    if (query.type) {
      qb.andWhere('material.type = :type', { type: query.type });
    }

    if (query.status) {
      qb.andWhere('material.status = :status', { status: query.status });
    }

    if (query.search) {
      qb.andWhere('material.original_filename ILIKE :search', {
        search: `%${query.search}%`,
      });
    }

    qb.orderBy('material.created_at', 'DESC');

    const page = query.page || 1;
    const limit = query.limit || 20;
    qb.skip((page - 1) * limit).take(limit);

    const [items, total] = await qb.getManyAndCount();

    return {
      items,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async findOne(id: string): Promise<MaterialEntity> {
    const material = await this.materialRepo.findOne({
      where: { id },
      relations: { topic: { module: true } },
    });

    if (!material) {
      throw new NotFoundException(`Material with ID "${id}" not found`);
    }

    return material;
  }

  async uploadFile(
    file: Express.Multer.File | undefined,
    dto: UploadMaterialDto,
  ): Promise<MaterialEntity> {
    if (!file?.buffer) {
      throw new BadRequestException('No file provided for upload');
    }

    const topic = await this.topicRepo.findOne({
      where: { id: dto.topic_id },
      relations: { module: true },
    });
    if (!topic?.module) {
      throw new NotFoundException(
        `Target topic with ID "${dto.topic_id}" not found`,
      );
    }

    // Recover the real name before it reaches the database, the frontmatter
    // and the grounding markers.
    const originalName = decodeMultipartFilename(file.originalname);

    const ext = path.extname(originalName).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      throw new BadRequestException(
        `Unsupported file extension: ${ext}. Supported formats: ${Array.from(ALLOWED_EXTENSIONS).join(', ')}`,
      );
    }

    // 1. Calculate SHA-256 hash
    const hash = crypto.createHash('sha256').update(file.buffer).digest('hex');

    // 2. Reject byte-identical re-uploads instead of indexing the same content
    //    twice into the knowledge base.
    const duplicate = await this.materialRepo.findOne({
      where: { topic_id: topic.id, file_hash: hash },
    });
    if (duplicate) {
      throw new ConflictException(
        `An identical file is already attached to this topic as material "${duplicate.id}" ` +
          `(${duplicate.original_filename}). Delete it first or use POST /api/materials/${duplicate.id}/retry.`,
      );
    }

    // 3. Save raw file to disk: {uploads}/raw/{moduleCode}/{topicCode}/{hash}__{filename}
    //    Codes originate from user input, so each segment is sanitised before it
    //    becomes part of a filesystem path.
    const rawDir = path.join(
      this.uploads().rawDir,
      sanitizePathSegment(topic.module.code),
      sanitizePathSegment(topic.code),
    );
    await fs.mkdir(rawDir, { recursive: true });

    const storedFilename = buildStoredFilename(originalName, ext, hash);
    const rawFilePath = path.join(rawDir, storedFilename);
    await fs.writeFile(rawFilePath, file.buffer);

    // 4. Create Material record
    const material = this.materialRepo.create({
      topic_id: topic.id,
      type: dto.type,
      raw_file_path: rawFilePath,
      original_filename: originalName,
      file_size: file.size,
      file_hash: hash,
      status: MaterialStatus.QUEUED,
    });

    const saved = await this.materialRepo.save(material);

    // 5. Trigger asynchronous processing pipeline
    this.runPipelineInBackground(saved.id);

    return saved;
  }

  async getContent(id: string): Promise<{
    id: string;
    filename: string;
    markdown: string;
    chunkCount: number;
    charCount: number;
    detectedScript?: string;
  }> {
    const material = await this.findOne(id);
    if (!material.md_file_path) {
      throw new BadRequestException(
        'Material has not been converted to Markdown yet',
      );
    }

    try {
      const markdown = await fs.readFile(material.md_file_path, 'utf8');
      return {
        id: material.id,
        filename: material.original_filename,
        markdown,
        chunkCount: material.chunk_count,
        charCount: material.char_count,
        detectedScript: material.detected_script,
      };
    } catch {
      throw new NotFoundException(
        `Markdown file not found on disk at ${material.md_file_path}`,
      );
    }
  }

  async retry(id: string): Promise<MaterialEntity> {
    const material = await this.findOne(id);

    if (this.pipelineService.isProcessing(material.id)) {
      throw new ConflictException(
        'This material is already being processed - wait for the current run to finish',
      );
    }

    // Persist the queued state *before* starting the run: the pipeline loads
    // its own copy of the entity, so saving this stale one afterwards would
    // overwrite the status and results the run has already written.
    material.status = MaterialStatus.QUEUED;
    material.error_message = undefined;
    const queued = await this.materialRepo.save(material);

    this.runPipelineInBackground(queued.id);

    return queued;
  }

  async remove(id: string): Promise<{ success: boolean; message: string }> {
    const material = await this.findOne(id);

    // If indexed in Open WebUI, remove file and unlink
    if (material.owui_file_id && material.topic?.module?.owui_kb_id) {
      await this.owuiService.removeFileFromKnowledgeBase(
        material.topic.module.owui_kb_id,
        material.owui_file_id,
      );
      await this.owuiService.deleteFile(material.owui_file_id);
    }

    // Remove files from disk
    if (material.raw_file_path) {
      await fs.unlink(material.raw_file_path).catch(() => undefined);
    }
    if (material.md_file_path) {
      await fs.unlink(material.md_file_path).catch(() => undefined);
    }

    await this.materialRepo.remove(material);

    return {
      success: true,
      message: `Material "${material.original_filename}" deleted successfully`,
    };
  }

  /**
   * The pipeline is intentionally not awaited so that uploads return promptly.
   * Failures are already recorded on the material and in the audit log; they
   * are logged here as well so an unattended run is never silently lost.
   */
  private runPipelineInBackground(materialId: string): void {
    void this.pipelineService
      .processMaterial(materialId)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        this.logger.error(
          `Background pipeline run failed for ${materialId}: ${msg}`,
        );
      });
  }

  private uploads(): UploadsConfig {
    const uploads = this.configService.get<UploadsConfig>('uploads');
    if (!uploads) {
      throw new Error('Uploads configuration is missing');
    }
    return uploads;
  }
}
