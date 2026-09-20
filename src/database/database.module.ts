import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConfigModule, ConfigService } from '@nestjs/config';
import {
  ModuleEntity,
  TopicEntity,
  MaterialEntity,
  AuditLogEntity,
  UserEntity,
} from './entities/index.js';

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => ({
        type: 'postgres',
        host: configService.get<string>('POSTGRES_HOST', 'localhost'),
        port: configService.get<number>('POSTGRES_PORT', 5432),
        username: configService.get<string>('POSTGRES_USER', 'postgres'),
        password: configService.get<string>('POSTGRES_PASSWORD', 'postgres'),
        database: configService.get<string>('POSTGRES_DB', 'turizm_db'),
        entities: [
          ModuleEntity,
          TopicEntity,
          MaterialEntity,
          AuditLogEntity,
          UserEntity,
        ],
        synchronize:
          configService.get<string>('POSTGRES_SYNC', 'true') === 'true',
        logging:
          configService.get<string>('POSTGRES_LOGGING', 'false') === 'true',
      }),
    }),
    TypeOrmModule.forFeature([
      ModuleEntity,
      TopicEntity,
      MaterialEntity,
      AuditLogEntity,
      UserEntity,
    ]),
  ],
  exports: [TypeOrmModule],
})
export class DatabaseModule {}
