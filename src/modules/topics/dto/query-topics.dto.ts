import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsOptional, IsUUID } from 'class-validator';
import { PaginationQueryDto } from '../../../common/dto/pagination.dto.js';

export class QueryTopicsDto extends PaginationQueryDto {
  @ApiPropertyOptional({
    description: 'Filter topics by module UUID',
  })
  @IsOptional()
  @IsUUID()
  module_id?: string;
}
