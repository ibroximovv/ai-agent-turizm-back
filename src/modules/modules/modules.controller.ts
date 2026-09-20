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
import { ModulesService } from './modules.service.js';
import { CreateModuleDto } from './dto/create-module.dto.js';
import { UpdateModuleDto } from './dto/update-module.dto.js';
import { QueryModulesDto } from './dto/query-modules.dto.js';

@ApiTags('Modules')
@Controller('modules')
export class ModulesController {
  constructor(private readonly modulesService: ModulesService) {}

  @Get()
  @ApiOperation({
    summary: 'List all modules',
    description:
      'Returns a paginated list of educational modules with topics count and materials status breakdown.',
  })
  @ApiResponse({
    status: 200,
    description: 'Paginated list of modules',
  })
  async findAll(@Query() query: QueryModulesDto) {
    return this.modulesService.findAll(query);
  }

  @Get(':id')
  @ApiOperation({
    summary: 'Get module details',
    description: 'Returns module information along with its associated topics.',
  })
  @ApiResponse({
    status: 200,
    description: 'Module details',
  })
  @ApiResponse({
    status: 404,
    description: 'Module not found',
  })
  async findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.modulesService.findOne(id);
  }

  @Post()
  @ApiOperation({
    summary: 'Create a new module',
    description: 'Creates a new educational module with a unique code.',
  })
  @ApiResponse({
    status: 201,
    description: 'Module successfully created',
  })
  @ApiResponse({
    status: 409,
    description: 'Module code already exists',
  })
  async create(@Body() dto: CreateModuleDto) {
    return this.modulesService.create(dto);
  }

  @Patch(':id')
  @ApiOperation({
    summary: 'Update an existing module',
  })
  @ApiResponse({
    status: 200,
    description: 'Module updated successfully',
  })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateModuleDto,
  ) {
    return this.modulesService.update(id, dto);
  }

  @Delete(':id')
  @ApiOperation({
    summary: 'Delete a module',
    description:
      'Deletes a module and cascades to all its topics, materials, and audit logs.',
  })
  @ApiResponse({
    status: 200,
    description: 'Module deleted successfully',
  })
  async remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.modulesService.remove(id);
  }

  @Post(':id/kb')
  @ApiOperation({
    summary: 'Create or sync Open WebUI Knowledge Base for this module',
    description:
      'Creates a dedicated Knowledge Base in Open WebUI if not present and saves its ID.',
  })
  @ApiResponse({
    status: 200,
    description: 'Knowledge Base status and details',
  })
  async syncKb(@Param('id', ParseUUIDPipe) id: string) {
    return this.modulesService.createOrSyncKb(id);
  }

  @Post(':id/process-all')
  @ApiOperation({
    summary: 'Batch process all materials in this module',
    description:
      'Enqueues all materials in the module for document parsing, transliteration, grounding injection, and OWUI indexing.',
  })
  @ApiResponse({
    status: 200,
    description: 'Summary of queued materials for pipeline processing',
  })
  async processAll(@Param('id', ParseUUIDPipe) id: string) {
    return this.modulesService.processAllMaterials(id);
  }
}
