import { Controller, Get } from '@nestjs/common';
import { ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { OwuiService } from './owui.service.js';

@ApiTags('Open WebUI')
@Controller('owui')
export class OwuiController {
  constructor(private readonly owuiService: OwuiService) {}

  @Get('status')
  @ApiOperation({
    summary: 'Check Open WebUI integration status',
    description:
      'Tests HTTP connectivity and authentication with the configured Open WebUI instance.',
  })
  @ApiResponse({
    status: 200,
    description: 'Connection diagnostics status',
    schema: {
      example: {
        connected: true,
        baseUrl: 'http://localhost:8080',
        hasApiKey: true,
        knowledgeBasesCount: 4,
        message: 'Successfully connected to Open WebUI (4 Knowledge Bases found)',
      },
    },
  })
  async getStatus() {
    return this.owuiService.checkConnection();
  }

  @Get('knowledge-bases')
  @ApiOperation({
    summary: 'List knowledge bases in Open WebUI',
    description: 'Retrieves all available Knowledge Bases from Open WebUI.',
  })
  @ApiResponse({
    status: 200,
    description: 'List of Knowledge Bases',
  })
  async listKnowledgeBases() {
    return this.owuiService.listKnowledgeBases();
  }
}
