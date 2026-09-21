import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConfigModule, ConfigService } from '@nestjs/config';
import type { DatabaseConfig } from '../config/configuration.js';
import {
  ModuleEntity,
  TopicEntity,
  MaterialEntity,
  AuditLogEntity,
  UserEntity,
} from './entities/index.js';

const ENTITIES = [
  ModuleEntity,
  TopicEntity,
  MaterialEntity,
  AuditLogEntity,
  UserEntity,
];

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => {
        // Values come pre-parsed from the config factory, so `port` is a real
        // number and the boolean flags are not the string "false".
        const db = configService.getOrThrow<DatabaseConfig>('database');

        return {
          type: 'postgres' as const,
          host: db.host,
          port: db.port,
          username: db.username,
          password: db.password,
          database: db.database,
          entities: ENTITIES,
          synchronize: db.synchronize,
          logging: db.logging,
        };
      },
    }),
    TypeOrmModule.forFeature(ENTITIES),
  ],
  exports: [TypeOrmModule],
})
export class DatabaseModule {}
