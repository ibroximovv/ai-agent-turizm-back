import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { TopicEntity } from '../../database/entities/topic.entity.js';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import { TopicsService } from './topics.service.js';
import { TopicsController } from './topics.controller.js';

@Module({
  imports: [TypeOrmModule.forFeature([TopicEntity, ModuleEntity])],
  controllers: [TopicsController],
  providers: [TopicsService],
  exports: [TopicsService],
})
export class TopicsModule {}
