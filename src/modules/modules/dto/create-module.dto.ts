import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsBoolean,
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  MaxLength,
} from 'class-validator';

export class CreateModuleDto {
  @ApiProperty({
    description: 'Unique module code identifier',
    example: 'module-01',
    maxLength: 40,
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(40)
  code!: string;

  @ApiProperty({
    description: 'Full name of the module',
    example: 'Turizm asoslari va qonunchilik',
    maxLength: 300,
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(300)
  name!: string;

  @ApiPropertyOptional({
    description: 'Detailed description of the module content and goals',
    example: "O'zbekiston Respublikasi turizm sohasi bo'yicha qonunlar to'plami",
  })
  @IsOptional()
  @IsString()
  description?: string;

  @ApiPropertyOptional({
    description: 'Display order index',
    default: 0,
    example: 1,
  })
  @IsOptional()
  @IsInt()
  order_index?: number;

  @ApiPropertyOptional({
    description: 'Active status',
    default: true,
  })
  @IsOptional()
  @IsBoolean()
  is_active?: boolean;
}
