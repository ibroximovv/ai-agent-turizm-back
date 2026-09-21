import { Controller, Get } from '@nestjs/common';
import { ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { AppService } from './app.service.js';
import type { HealthStatus } from './app.service.js';

@ApiTags('System')
@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get()
  @ApiOperation({ summary: 'Health check & service status' })
  @ApiResponse({ status: 200, description: 'Service is operational' })
  getHealth(): HealthStatus {
    return this.appService.getHealth();
  }
}
