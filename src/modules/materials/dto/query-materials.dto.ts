import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsOptional, IsUUID } from 'class-validator';
import { PaginationQueryDto } from '../../../common/dto/pagination.dto.js';
import {
  MaterialStatus,
  MaterialType,
} from '../../../database/entities/material.entity.js';

export class QueryMaterialsDto extends PaginationQueryDto {
  @ApiPropertyOptional({ description: 'Filter by Topic UUID' })
  @IsOptional()
  @IsUUID()
  topic_id?: string;

  @ApiPropertyOptional({ description: 'Filter by Module UUID' })
  @IsOptional()
  @IsUUID()
  module_id?: string;

  @ApiPropertyOptional({
    description: 'Filter by material category',
    enum: MaterialType,
  })
  @IsOptional()
  @IsEnum(MaterialType)
  type?: MaterialType;

  @ApiPropertyOptional({
    description: 'Filter by ingestion pipeline status',
    enum: MaterialStatus,
  })
  @IsOptional()
  @IsEnum(MaterialStatus)
  status?: MaterialStatus;
}
