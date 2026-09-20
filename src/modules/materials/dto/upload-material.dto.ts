import { ApiProperty } from '@nestjs/swagger';
import { IsEnum, IsNotEmpty, IsUUID } from 'class-validator';
import { MaterialType } from '../../../database/entities/material.entity.js';

export class UploadMaterialDto {
  @ApiProperty({
    description: 'Target Topic UUID',
    example: 'b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22',
  })
  @IsUUID()
  @IsNotEmpty()
  topic_id!: string;

  @ApiProperty({
    description: 'Material educational category',
    enum: MaterialType,
    default: MaterialType.LITERATURE,
    example: MaterialType.LITERATURE,
  })
  @IsEnum(MaterialType)
  type: MaterialType = MaterialType.LITERATURE;

  @ApiProperty({
    type: 'string',
    format: 'binary',
    description: 'Document file (PDF, PPTX, DOCX, TXT, MD) up to 200MB',
  })
  file?: any;
}
