import { Controller, Get } from '@nestjs/common';
import { ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { AppService } from './app.service.js';

@ApiTags('System')
@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get()
  @ApiOperation({ summary: 'Health check & service status' })
  @ApiResponse({ status: 200, description: 'Service is operational' })
  getHello(): { status: string; service: string; timestamp: string } {
    return {
      status: 'ok',
      service: 'ai-agent-turizm-back',
      timestamp: new Date().toISOString(),
    };
  }
}
