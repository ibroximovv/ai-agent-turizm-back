import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn,
  Index,
  type Relation,
} from 'typeorm';
import { MaterialEntity } from './material.entity.js';
import { ModuleEntity } from './module.entity.js';

export enum LogLevel {
  INFO = 'info',
  WARN = 'warn',
  ERROR = 'error',
}

@Entity('audit_logs')
export class AuditLogEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid', nullable: true })
  material_id?: string;

  @Column({ type: 'uuid', nullable: true })
  module_id?: string;

  @Column({ type: 'varchar', length: 50 })
  stage!: string;

  @Column({
    type: 'enum',
    enum: LogLevel,
    default: LogLevel.INFO,
  })
  level!: LogLevel;

  @Column({ type: 'text' })
  message!: string;

  @Index('idx_audit_logs_created_at')
  @CreateDateColumn({ type: 'timestamptz' })
  created_at!: Date;

  @ManyToOne(() => MaterialEntity, {
    onDelete: 'CASCADE',
    nullable: true,
  })
  @JoinColumn({ name: 'material_id' })
  material?: Relation<MaterialEntity>;

  @ManyToOne(() => ModuleEntity, {
    onDelete: 'CASCADE',
    nullable: true,
  })
  @JoinColumn({ name: 'module_id' })
  module?: Relation<ModuleEntity>;
}
