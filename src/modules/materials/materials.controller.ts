import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import {
  ApiBody,
  ApiConsumes,
  ApiOperation,
  ApiResponse,
  ApiTags,
} from '@nestjs/swagger';
import { MaterialsService } from './materials.service.js';
import { UploadMaterialDto } from './dto/upload-material.dto.js';
import { QueryMaterialsDto } from './dto/query-materials.dto.js';

@ApiTags('Materials')
@Controller('materials')
export class MaterialsController {
  constructor(private readonly materialsService: MaterialsService) {}

  @Get()
  @ApiOperation({
    summary: 'List materials',
    description:
      'Filterable by topic UUID, module UUID, material type, status, and search query.',
  })
  @ApiResponse({
    status: 200,
    description: 'Paginated list of materials',
  })
  async findAll(@Query() query: QueryMaterialsDto) {
    return this.materialsService.findAll(query);
  }

  @Post('upload')
  @ApiOperation({
    summary: 'Upload educational document file',
    description:
      'Uploads a raw document (PDF, PPTX, DOCX, TXT, MD) up to 200MB, computes SHA-256, and enqueues it for conversion, Uzbek transliteration, source grounding, and Open WebUI indexing.',
  })
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    type: UploadMaterialDto,
  })
  @ApiResponse({
    status: 201,
    description: 'Document uploaded and pipeline execution triggered',
  })
  @ApiResponse({
    status: 400,
    description: 'Unsupported file format or invalid input',
  })
  @UseInterceptors(FileInterceptor('file'))
  async upload(
    @UploadedFile() file: Express.Multer.File | undefined,
    @Body() dto: UploadMaterialDto,
  ) {
    return this.materialsService.uploadFile(file, dto);
  }

  @Get(':id')
  @ApiOperation({
    summary: 'Get material details and processing status',
  })
  @ApiResponse({
    status: 200,
    description: 'Material details',
  })
  @ApiResponse({
    status: 404,
    description: 'Material not found',
  })
  async findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.materialsService.findOne(id);
  }

  @Get(':id/content')
  @ApiOperation({
    summary: 'Preview converted Markdown content with [MANBA: ...] markers',
    description:
      'Returns the generated Markdown content, character count, chunk count, and detected script.',
  })
  @ApiResponse({
    status: 200,
    description: 'Converted Markdown content payload',
  })
  @ApiResponse({
    status: 400,
    description: 'Material not converted to Markdown yet',
  })
  async getContent(@Param('id', ParseUUIDPipe) id: string) {
    return this.materialsService.getContent(id);
  }

  @Post(':id/retry')
  @ApiOperation({
    summary: 'Retry pipeline processing for a material',
    description:
      'Re-triggers document parsing, transliteration, grounding injection, and Open WebUI indexing.',
  })
  @ApiResponse({
    status: 200,
    description: 'Material enqueued for retry',
  })
  async retry(@Param('id', ParseUUIDPipe) id: string) {
    return this.materialsService.retry(id);
  }

  @Delete(':id')
  @ApiOperation({
    summary: 'Delete a material',
    description:
      'Deletes material, removes disk files, and unlinks/purges file from Open WebUI Knowledge Base.',
  })
  @ApiResponse({
    status: 200,
    description: 'Material deleted successfully',
  })
  async remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.materialsService.remove(id);
  }
}
