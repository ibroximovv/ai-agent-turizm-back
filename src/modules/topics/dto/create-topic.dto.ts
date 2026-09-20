import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  IsUUID,
  MaxLength,
} from 'class-validator';

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
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(40)
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
  order_index?: number;
}
