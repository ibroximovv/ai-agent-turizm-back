import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import {
  MaterialEntity,
  AuditLogEntity,
  ModuleEntity,
  TopicEntity,
} from '../../database/entities/index.js';
import { OwuiModule } from '../owui/owui.module.js';
import { ParserService } from './services/parser.service.js';
import { CleanerService } from './services/cleaner.service.js';
import { TranslitService } from './services/translit.service.js';
import { ChunkerService } from './services/chunker.service.js';
import { PipelineService } from './pipeline.service.js';

@Module({
  imports: [
    TypeOrmModule.forFeature([
      MaterialEntity,
      AuditLogEntity,
      ModuleEntity,
      TopicEntity,
    ]),
    OwuiModule,
  ],
  providers: [
    ParserService,
    CleanerService,
    TranslitService,
    ChunkerService,
    PipelineService,
  ],
  exports: [PipelineService, TranslitService, CleanerService, ParserService],
})
export class PipelineModule {}
