import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  ParseUUIDPipe,
  Patch,
  Post,
  Query,
} from '@nestjs/common';
import { ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TopicsService } from './topics.service.js';
import { CreateTopicDto } from './dto/create-topic.dto.js';
import { UpdateTopicDto } from './dto/update-topic.dto.js';
import { QueryTopicsDto } from './dto/query-topics.dto.js';

@ApiTags('Topics')
@Controller('topics')
export class TopicsController {
  constructor(private readonly topicsService: TopicsService) {}

  @Get()
  @ApiOperation({
    summary: 'List topics',
    description:
      'Filterable by module UUID and searchable by topic code, name, or description.',
  })
  @ApiResponse({
    status: 200,
    description: 'Paginated list of topics',
  })
  async findAll(@Query() query: QueryTopicsDto) {
    return this.topicsService.findAll(query);
  }

  @Get(':id')
  @ApiOperation({
    summary: 'Get topic details',
    description: 'Returns topic details along with associated materials.',
  })
  @ApiResponse({
    status: 200,
    description: 'Topic details',
  })
  @ApiResponse({
    status: 404,
    description: 'Topic not found',
  })
  async findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.topicsService.findOne(id);
  }

  @Post()
  @ApiOperation({
    summary: 'Create a new topic',
    description:
      'Creates a new educational topic under an existing module with unique code within the module.',
  })
  @ApiResponse({
    status: 201,
    description: 'Topic successfully created',
  })
  @ApiResponse({
    status: 409,
    description: 'Topic code already exists within this module',
  })
  async create(@Body() dto: CreateTopicDto) {
    return this.topicsService.create(dto);
  }

  @Patch(':id')
  @ApiOperation({
    summary: 'Update an existing topic',
  })
  @ApiResponse({
    status: 200,
    description: 'Topic updated successfully',
  })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateTopicDto,
  ) {
    return this.topicsService.update(id, dto);
  }

  @Delete(':id')
  @ApiOperation({
    summary: 'Delete a topic',
    description: 'Deletes a topic and cascades to all its materials and audit logs.',
  })
  @ApiResponse({
    status: 200,
    description: 'Topic deleted successfully',
  })
  async remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.topicsService.remove(id);
  }
}
