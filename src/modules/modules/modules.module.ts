import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import { MaterialEntity } from '../../database/entities/material.entity.js';
import { OwuiModule } from '../owui/owui.module.js';
import { PipelineModule } from '../pipeline/pipeline.module.js';
import { ModulesService } from './modules.service.js';
import { ModulesController } from './modules.controller.js';

@Module({
  imports: [
    TypeOrmModule.forFeature([ModuleEntity, MaterialEntity]),
    OwuiModule,
    PipelineModule,
  ],
  controllers: [ModulesController],
  providers: [ModulesService],
  exports: [ModulesService],
})
export class ModulesModule {}
