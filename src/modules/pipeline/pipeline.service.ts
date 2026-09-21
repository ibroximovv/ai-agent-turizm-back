import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { InjectRepository } from '@nestjs/typeorm';
import * as fs from 'fs/promises';
import * as path from 'path';
import { Repository } from 'typeorm';
import type { UploadsConfig } from '../../config/configuration.js';
import {
  MaterialEntity,
  MaterialStatus,
} from '../../database/entities/material.entity.js';
import {
  AuditLogEntity,
  LogLevel,
} from '../../database/entities/audit-log.entity.js';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import { ParserService } from './services/parser.service.js';
import { CleanerService } from './services/cleaner.service.js';
import { TranslitService } from './services/translit.service.js';
import { ChunkerService } from './services/chunker.service.js';
import { OwuiService } from '../owui/owui.service.js';

/** Characters of document text inspected when detecting the script. */
const SCRIPT_SAMPLE_CHARS = 8000;

@Injectable()
export class PipelineService {
  private readonly logger = new Logger(PipelineService.name);

  /**
   * Materials currently being processed by this instance. Upload, retry and
   * batch processing can all target the same material, and running the pipeline
   * twice at once would have the two runs overwrite each other's status and
   * Open WebUI file ids.
   */
  private readonly inFlight = new Set<string>();

  constructor(
    @InjectRepository(MaterialEntity)
    private readonly materialRepo: Repository<MaterialEntity>,
    @InjectRepository(AuditLogEntity)
    private readonly auditLogRepo: Repository<AuditLogEntity>,
    @InjectRepository(ModuleEntity)
    private readonly moduleRepo: Repository<ModuleEntity>,
    private readonly parserService: ParserService,
    private readonly cleanerService: CleanerService,
    private readonly translitService: TranslitService,
    private readonly chunkerService: ChunkerService,
    private readonly owuiService: OwuiService,
    private readonly configService: ConfigService,
  ) {}

  isProcessing(materialId: string): boolean {
    return this.inFlight.has(materialId);
  }

  /**
   * Run the full pipeline for a material: parse -> clean -> translit -> chunk -> index
   */
  async processMaterial(materialId: string): Promise<MaterialEntity> {
    const material = await this.materialRepo.findOne({
      where: { id: materialId },
      relations: { topic: { module: true } },
    });

    if (!material) {
      throw new Error(`Material with ID ${materialId} not found`);
    }

    const topic = material.topic;
    const module = topic?.module;

    if (!topic || !module) {
      throw new Error(
        `Topic or Module relation missing for material ${materialId}`,
      );
    }

    if (this.inFlight.has(materialId)) {
      this.logger.warn(
        `Material ${materialId} is already being processed - skipping duplicate run.`,
      );
      return material;
    }
    this.inFlight.add(materialId);

    try {
      // 1. Stage: CONVERTING
      material.status = MaterialStatus.CONVERTING;
      material.error_message = undefined;
      await this.materialRepo.save(material);
      await this.logAudit(
        material.id,
        module.id,
        'conversion',
        LogLevel.INFO,
        `Started document parsing for "${material.original_filename}"`,
      );

      // 2. Parse file
      const parsedDoc = await this.parserService.parseFile(
        material.raw_file_path,
      );

      if (parsedDoc.chunks.length === 0) {
        throw new Error(
          'No extractable text found in the document - nothing to index.',
        );
      }

      // 3. Clean and transliterate chunks
      const detectedScript = this.translitService.detectScript(
        this.buildScriptSample(parsedDoc.chunks),
      );
      material.detected_script = detectedScript;

      const processedChunks = parsedDoc.chunks.map((chunk) => {
        let cleaned = this.cleanerService.cleanText(chunk.text);
        if (detectedScript === 'uz-cyrl') {
          cleaned = this.translitService.toLatin(cleaned);
        }
        return {
          label: chunk.label,
          text: cleaned,
        };
      });

      // 4. Inject grounding markers and build Markdown
      const chunkResult = await this.chunkerService.buildGroundedMarkdown(
        processedChunks,
        {
          materialId: material.id,
          moduleCode: module.code,
          moduleName: module.name,
          topicCode: topic.code,
          topicName: topic.name,
          materialType: material.type,
          originalFilename: material.original_filename,
          detectedScript,
        },
        this.readyDir(),
      );

      // A rename (different filename fingerprint) would otherwise leave the
      // previous markdown behind as an orphan.
      await this.removeStaleMarkdown(
        material.md_file_path,
        chunkResult.filePath,
      );

      material.md_file_path = chunkResult.filePath;
      material.chunk_count = chunkResult.chunkCount;
      material.char_count = chunkResult.charCount;
      material.status = MaterialStatus.MD_READY;
      await this.materialRepo.save(material);

      await this.logAudit(
        material.id,
        module.id,
        'conversion',
        LogLevel.INFO,
        `Converted to Markdown: ${chunkResult.chunkCount} chunks, ` +
          `${chunkResult.markerCount} grounding markers, ` +
          `${chunkResult.charCount.toLocaleString('en-US')} chars, script: ${detectedScript}`,
      );

      for (const warning of parsedDoc.warnings) {
        await this.logAudit(
          material.id,
          module.id,
          'conversion',
          LogLevel.WARN,
          warning,
        );
      }

      // 5. Stage: Open WebUI Indexing
      await this.indexToOwui(material, module);

      return material;
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      this.logger.error(
        `Pipeline failed for material ${materialId}: ${errorMsg}`,
      );

      material.status = MaterialStatus.FAILED;
      material.error_message = errorMsg;
      await this.materialRepo.save(material);

      await this.logAudit(
        material.id,
        module.id,
        'pipeline',
        LogLevel.ERROR,
        `Pipeline error: ${errorMsg}`,
      );

      throw err;
    } finally {
      this.inFlight.delete(materialId);
    }
  }

  private async indexToOwui(
    material: MaterialEntity,
    module: ModuleEntity,
  ): Promise<void> {
    // A cheap local check; the HTTP calls below report real connectivity
    // problems through the catch block instead of costing an extra round trip
    // per material.
    if (!this.owuiService.isConfigured()) {
      this.logger.log(
        'OWUI_API_KEY is not configured. Material kept in md_ready state.',
      );
      await this.logAudit(
        material.id,
        module.id,
        'indexing',
        LogLevel.WARN,
        'Skipped Open WebUI indexing: OWUI_API_KEY is not configured',
      );
      return;
    }

    try {
      material.status = MaterialStatus.UPLOADING;
      await this.materialRepo.save(material);

      // Ensure Knowledge Base exists for module
      let kbId = module.owui_kb_id;
      if (!kbId) {
        const newKb = await this.owuiService.createKnowledgeBase(
          `${module.code} - ${module.name}`,
          module.description || module.name,
        );
        kbId = newKb.id;
        module.owui_kb_id = kbId;
        await this.moduleRepo.save(module);

        await this.logAudit(
          material.id,
          module.id,
          'kb_create',
          LogLevel.INFO,
          `Created Open WebUI Knowledge Base: ${kbId}`,
        );
      }

      // If re-indexing and old OWUI file ID exists, remove it first
      if (material.owui_file_id) {
        await this.owuiService.removeFileFromKnowledgeBase(
          kbId,
          material.owui_file_id,
        );
        await this.owuiService.deleteFile(material.owui_file_id);
        material.owui_file_id = undefined;
      }

      if (!material.md_file_path) {
        throw new Error(
          'Markdown file path is missing - conversion incomplete',
        );
      }

      // Upload Markdown file
      const filename = path.basename(material.md_file_path);
      const mdContent = await fs.readFile(material.md_file_path, 'utf8');

      const uploaded = await this.owuiService.uploadMarkdownFile(
        filename,
        mdContent,
      );
      material.owui_file_id = uploaded.id;

      // Add file to Knowledge Base
      await this.owuiService.addFileToKnowledgeBase(kbId, uploaded.id);

      material.status = MaterialStatus.INDEXED;
      material.error_message = undefined;
      material.indexed_at = new Date();
      await this.materialRepo.save(material);

      await this.logAudit(
        material.id,
        module.id,
        'indexing',
        LogLevel.INFO,
        `Successfully indexed file into Knowledge Base ${kbId} (File ID: ${uploaded.id})`,
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.warn(`Open WebUI indexing error: ${msg}`);
      // If indexing fails, keep material as md_ready with warning
      material.status = MaterialStatus.MD_READY;
      material.error_message = `Open WebUI indexing warning: ${msg}`;
      await this.materialRepo.save(material);

      await this.logAudit(
        material.id,
        module.id,
        'indexing',
        LogLevel.WARN,
        `OWUI indexing incomplete: ${msg}`,
      );
    }
  }

  /** Concatenates the leading chunks up to the script-detection sample size. */
  private buildScriptSample(chunks: Array<{ text: string }>): string {
    const parts: string[] = [];
    let length = 0;
    for (const chunk of chunks) {
      parts.push(chunk.text);
      length += chunk.text.length + 1;
      if (length >= SCRIPT_SAMPLE_CHARS) break;
    }
    return parts.join(' ').slice(0, SCRIPT_SAMPLE_CHARS);
  }

  private readyDir(): string {
    const uploads = this.configService.get<UploadsConfig>('uploads');
    return uploads?.readyDir ?? path.resolve(process.cwd(), 'uploads', 'ready');
  }

  private async removeStaleMarkdown(
    previousPath: string | undefined,
    currentPath: string,
  ): Promise<void> {
    if (!previousPath || previousPath === currentPath) return;
    await fs.unlink(previousPath).catch(() => undefined);
  }

  /**
   * Audit logging must never be the reason a pipeline run fails, so write
   * failures are reported to the application log and swallowed.
   */
  private async logAudit(
    materialId: string | undefined,
    moduleId: string | undefined,
    stage: string,
    level: LogLevel,
    message: string,
  ): Promise<void> {
    try {
      const log = this.auditLogRepo.create({
        material_id: materialId,
        module_id: moduleId,
        stage,
        level,
        message,
      });
      await this.auditLogRepo.save(log);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.error(`Failed to persist audit log (${stage}): ${msg}`);
    }
  }
}
