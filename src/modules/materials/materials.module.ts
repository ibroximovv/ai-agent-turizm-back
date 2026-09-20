import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { MaterialEntity } from '../../database/entities/material.entity.js';
import { TopicEntity } from '../../database/entities/topic.entity.js';
import { PipelineModule } from '../pipeline/pipeline.module.js';
import { OwuiModule } from '../owui/owui.module.js';
import { MaterialsService } from './materials.service.js';
import { MaterialsController } from './materials.controller.js';

@Module({
  imports: [
    TypeOrmModule.forFeature([MaterialEntity, TopicEntity]),
    PipelineModule,
    OwuiModule,
  ],
  controllers: [MaterialsController],
  providers: [MaterialsService],
  exports: [MaterialsService],
})
export class MaterialsModule {}
