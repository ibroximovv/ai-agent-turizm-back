import {
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { TopicEntity } from '../../database/entities/topic.entity.js';
import { ModuleEntity } from '../../database/entities/module.entity.js';
import { CreateTopicDto } from './dto/create-topic.dto.js';
import { UpdateTopicDto } from './dto/update-topic.dto.js';
import { QueryTopicsDto } from './dto/query-topics.dto.js';

@Injectable()
export class TopicsService {
  constructor(
    @InjectRepository(TopicEntity)
    private readonly topicRepo: Repository<TopicEntity>,
    @InjectRepository(ModuleEntity)
    private readonly moduleRepo: Repository<ModuleEntity>,
  ) {}

  async findAll(query: QueryTopicsDto) {
    const qb = this.topicRepo
      .createQueryBuilder('topic')
      .leftJoinAndSelect('topic.module', 'module')
      .leftJoinAndSelect('topic.materials', 'materials');

    if (query.module_id) {
      qb.andWhere('topic.module_id = :moduleId', {
        moduleId: query.module_id,
      });
    }

    if (query.search) {
      qb.andWhere(
        '(topic.code ILIKE :search OR topic.name ILIKE :search OR topic.description ILIKE :search)',
        { search: `%${query.search}%` },
      );
    }

    qb.orderBy('topic.order_index', 'ASC').addOrderBy(
      'topic.created_at',
      'ASC',
    );

    const page = query.page || 1;
    const limit = query.limit || 20;
    qb.skip((page - 1) * limit).take(limit);

    const [items, total] = await qb.getManyAndCount();

    for (const topic of items) {
      Object.assign(topic, { materialsCount: topic.materials?.length ?? 0 });
    }

    return {
      items,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async findOne(id: string): Promise<TopicEntity> {
    const topic = await this.topicRepo.findOne({
      where: { id },
      relations: { module: true, materials: true },
      order: {
        materials: {
          created_at: 'ASC',
        },
      },
    });

    if (!topic) {
      throw new NotFoundException(`Topic with ID "${id}" not found`);
    }

    return topic;
  }

  async create(dto: CreateTopicDto): Promise<TopicEntity> {
    const module = await this.moduleRepo.findOne({
      where: { id: dto.module_id },
    });
    if (!module) {
      throw new NotFoundException(
        `Parent module with ID "${dto.module_id}" not found`,
      );
    }

    const existing = await this.topicRepo.findOne({
      where: { module_id: dto.module_id, code: dto.code },
    });
    if (existing) {
      throw new ConflictException(
        `Topic with code "${dto.code}" already exists in this module`,
      );
    }

    const topic = this.topicRepo.create(dto);
    return this.topicRepo.save(topic);
  }

  async update(id: string, dto: UpdateTopicDto): Promise<TopicEntity> {
    const topic = await this.findOne(id);

    if (dto.code && dto.code !== topic.code) {
      const targetModuleId = dto.module_id || topic.module_id;
      const existing = await this.topicRepo.findOne({
        where: { module_id: targetModuleId, code: dto.code },
      });
      if (existing && existing.id !== id) {
        throw new ConflictException(
          `Topic with code "${dto.code}" already exists in this module`,
        );
      }
    }

    if (dto.module_id && dto.module_id !== topic.module_id) {
      const module = await this.moduleRepo.findOne({
        where: { id: dto.module_id },
      });
      if (!module) {
        throw new NotFoundException(
          `Parent module with ID "${dto.module_id}" not found`,
        );
      }
    }

    Object.assign(topic, dto);
    return this.topicRepo.save(topic);
  }

  async remove(id: string): Promise<{ success: boolean; message: string }> {
    const topic = await this.findOne(id);
    await this.topicRepo.remove(topic);
    return {
      success: true,
      message: `Topic "${topic.code}" and its materials deleted successfully`,
    };
  }
}
