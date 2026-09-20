import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsOptional, IsString, IsUUID } from 'class-validator';
import { PaginationQueryDto } from '../../../common/dto/pagination.dto.js';
import { LogLevel } from '../../../database/entities/audit-log.entity.js';

export class QueryAuditLogsDto extends PaginationQueryDto {
  @ApiPropertyOptional({ description: 'Filter by Module UUID' })
  @IsOptional()
  @IsUUID()
  module_id?: string;

  @ApiPropertyOptional({ description: 'Filter by Material UUID' })
  @IsOptional()
  @IsUUID()
  material_id?: string;

  @ApiPropertyOptional({
    description: 'Filter by Log Level',
    enum: LogLevel,
  })
  @IsOptional()
  @IsEnum(LogLevel)
  level?: LogLevel;

  @ApiPropertyOptional({
    description: 'Filter by stage name (e.g. conversion, indexing, kb_create)',
  })
  @IsOptional()
  @IsString()
  stage?: string;
}
