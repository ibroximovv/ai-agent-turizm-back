import { PartialType } from '@nestjs/swagger';
import { CreateTopicDto } from './create-topic.dto.js';

export class UpdateTopicDto extends PartialType(CreateTopicDto) {}
