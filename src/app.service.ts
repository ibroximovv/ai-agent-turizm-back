import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

export interface HealthStatus {
  status: 'ok';
  service: string;
  environment: string;
  uptimeSeconds: number;
  timestamp: string;
}

const SERVICE_NAME = 'ai-agent-turizm-back';

@Injectable()
export class AppService {
  constructor(private readonly configService: ConfigService) {}

  getHealth(): HealthStatus {
    return {
      status: 'ok',
      service: SERVICE_NAME,
      environment: this.configService.get<string>('nodeEnv') ?? 'development',
      uptimeSeconds: Math.round(process.uptime()),
      timestamp: new Date().toISOString(),
    };
  }
}
