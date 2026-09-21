import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  IsUUID,
  Matches,
  MaxLength,
  Min,
} from 'class-validator';
import {
  CODE_PATTERN,
  CODE_PATTERN_MESSAGE,
} from '../../../common/constants.js';

export class CreateTopicDto {
  @ApiProperty({
    description: 'Parent module UUID',
    example: 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
  })
  @IsUUID()
  @IsNotEmpty()
  module_id!: string;

  @ApiProperty({
    description: 'Unique topic code within the module',
    example: 'topic-01',
    maxLength: 40,
    pattern: CODE_PATTERN.source,
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(40)
  @Matches(CODE_PATTERN, { message: CODE_PATTERN_MESSAGE })
  code!: string;

  @ApiProperty({
    description: 'Full name of the topic',
    example: "Turizm to'g'risidagi qonunchilik asoslari",
    maxLength: 300,
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(300)
  name!: string;

  @ApiPropertyOptional({
    description: 'Optional description of the topic',
  })
  @IsOptional()
  @IsString()
  description?: string;

  @ApiPropertyOptional({
    description: 'Order index within module',
    default: 0,
    example: 1,
  })
  @IsOptional()
  @IsInt()
  @Min(0)
  order_index?: number;
}
