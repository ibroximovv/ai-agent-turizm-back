import { PartialType } from '@nestjs/swagger';
import { CreateModuleDto } from './create-module.dto.js';

export class UpdateModuleDto extends PartialType(CreateModuleDto) {}
