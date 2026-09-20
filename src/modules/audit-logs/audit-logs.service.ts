import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { AuditLogEntity } from '../../database/entities/audit-log.entity.js';
import { QueryAuditLogsDto } from './dto/query-audit-logs.dto.js';

@Injectable()
export class AuditLogsService {
  constructor(
    @InjectRepository(AuditLogEntity)
    private readonly auditLogRepo: Repository<AuditLogEntity>,
  ) {}

  async findAll(query: QueryAuditLogsDto) {
    const qb = this.auditLogRepo
      .createQueryBuilder('log')
      .leftJoinAndSelect('log.module', 'module')
      .leftJoinAndSelect('log.material', 'material');

    if (query.module_id) {
      qb.andWhere('log.module_id = :moduleId', { moduleId: query.module_id });
    }

    if (query.material_id) {
      qb.andWhere('log.material_id = :materialId', {
        materialId: query.material_id,
      });
    }

    if (query.level) {
      qb.andWhere('log.level = :level', { level: query.level });
    }

    if (query.stage) {
      qb.andWhere('log.stage = :stage', { stage: query.stage });
    }

    if (query.search) {
      qb.andWhere('log.message ILIKE :search', {
        search: `%${query.search}%`,
      });
    }

    qb.orderBy('log.created_at', 'DESC');

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
}
