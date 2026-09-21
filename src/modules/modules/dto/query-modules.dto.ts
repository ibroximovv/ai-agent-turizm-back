import { ApiPropertyOptional } from '@nestjs/swagger';
import { Transform } from 'class-transformer';
import { IsBoolean, IsOptional } from 'class-validator';
import { PaginationQueryDto } from '../../../common/dto/pagination.dto.js';

/**
 * Query strings carry booleans as text. Unrecognised values are passed through
 * untouched so that @IsBoolean() rejects them instead of silently meaning
 * "false" — an `is_active=maybe` typo must not quietly hide active modules.
 */
function parseBoolQuery(value: unknown): unknown {
  if (typeof value === 'boolean') return value;
  if (typeof value !== 'string') return value;
  const normalized = value.trim().toLowerCase();
  if (['true', '1', 'yes'].includes(normalized)) return true;
  if (['false', '0', 'no'].includes(normalized)) return false;
  return value;
}

export class QueryModulesDto extends PaginationQueryDto {
  @ApiPropertyOptional({
    description: 'Filter by active status',
  })
  @IsOptional()
  @Transform(({ value }) => parseBoolQuery(value))
  @IsBoolean()
  is_active?: boolean;
}
