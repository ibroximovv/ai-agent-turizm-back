import {
  BadRequestException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as path from 'path';
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
  constructor(
    @InjectRepository(MaterialEntity)
    private readonly materialRepo: Repository<MaterialEntity>,
    @InjectRepository(TopicEntity)
    private readonly topicRepo: Repository<TopicEntity>,
    private readonly pipelineService: PipelineService,
    private readonly owuiService: OwuiService,
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
    if (!file) {
      throw new BadRequestException('No file provided for upload');
    }

    const topic = await this.topicRepo.findOne({
      where: { id: dto.topic_id },
      relations: { module: true },
    });
    if (!topic || !topic.module) {
      throw new NotFoundException(
        `Target topic with ID "${dto.topic_id}" not found`,
      );
    }

    const ext = path.extname(file.originalname).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      throw new BadRequestException(
        `Unsupported file extension: ${ext}. Supported formats: ${Array.from(ALLOWED_EXTENSIONS).join(', ')}`,
      );
    }

    // 1. Calculate SHA-256 hash
    const hash = crypto.createHash('sha256').update(file.buffer).digest('hex');

    // 2. Save raw file to disk: uploads/raw/{moduleCode}/{topicCode}/{filename}
    const rawDir = path.resolve(
      process.cwd(),
      'uploads/raw',
      topic.module.code,
      topic.code,
    );
    await fs.mkdir(rawDir, { recursive: true });

    const sanitizedFilename = file.originalname.replace(/[^a-zA-Z0-9._-]+/g, '_');
    const rawFilePath = path.join(rawDir, sanitizedFilename);
    await fs.writeFile(rawFilePath, file.buffer);

    // 3. Create Material record
    const material = this.materialRepo.create({
      topic_id: topic.id,
      type: dto.type,
      raw_file_path: rawFilePath,
      original_filename: file.originalname,
      file_size: file.size,
      file_hash: hash,
      status: MaterialStatus.NEW,
    });

    const saved = await this.materialRepo.save(material);

    // 4. Trigger asynchronous processing pipeline
    this.pipelineService.processMaterial(saved.id).catch(() => {});

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

    // Re-trigger pipeline
    this.pipelineService.processMaterial(material.id).catch(() => {});

    material.status = MaterialStatus.QUEUED;
    return this.materialRepo.save(material);
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
      await fs.unlink(material.raw_file_path).catch(() => {});
    }
    if (material.md_file_path) {
      await fs.unlink(material.md_file_path).catch(() => {});
    }

    await this.materialRepo.remove(material);

    return {
      success: true,
      message: `Material "${material.original_filename}" deleted successfully`,
    };
  }
}
