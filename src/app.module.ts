import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { createObserveModule } from '@nestjs/observe';
import { configuration, validateEnv } from './config/index.js';
import { DatabaseModule } from './database/database.module.js';
import { AppController } from './app.controller.js';
import { AppService } from './app.service.js';
import { OwuiModule } from './modules/owui/owui.module.js';
import { PipelineModule } from './modules/pipeline/pipeline.module.js';
import { AuditLogsModule } from './modules/audit-logs/audit-logs.module.js';
import { ModulesModule } from './modules/modules/modules.module.js';
import { TopicsModule } from './modules/topics/topics.module.js';
import { MaterialsModule } from './modules/materials/materials.module.js';

export const { ObserveModule, ObserveInstrument } = createObserveModule();

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      cache: true,
      envFilePath: ['.env'],
      load: [configuration],
      validate: validateEnv,
    }),
    DatabaseModule,
    ObserveModule.forRoot({
      appKey: process.env.OBSERVE_APP_KEY ?? 'turizm-app-key',
      appSecret: process.env.OBSERVE_APP_SECRET ?? 'turizm-app-secret',
      serviceId: 'ai-agent-turizm-back',
    }),
    OwuiModule,
    PipelineModule,
    AuditLogsModule,
    ModulesModule,
    TopicsModule,
    MaterialsModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
