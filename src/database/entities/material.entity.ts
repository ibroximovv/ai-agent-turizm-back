import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn,
  ManyToOne,
  JoinColumn,
  Index,
  type Relation,
} from 'typeorm';
import { TopicEntity } from './topic.entity.js';
import { UserEntity } from './user.entity.js';

/**
 * `bigint` columns are returned as strings by the postgres driver, which would
 * make `file_size` a string at runtime despite its `number` type. Converting on
 * read keeps the entity and the API response honest.
 */
const bigintToNumber = {
  to: (value?: number | null): number | null => value ?? 0,
  from: (value?: string | number | null): number => {
    if (value === null || value === undefined) return 0;
    return typeof value === 'number' ? value : Number.parseInt(value, 10) || 0;
  },
};

export enum MaterialType {
  PRESENTATION = 'presentation',
  QUESTIONS = 'questions',
  LITERATURE = 'literature',
}

export enum MaterialStatus {
  NEW = 'new',
  QUEUED = 'queued',
  CONVERTING = 'converting',
  MD_READY = 'md_ready',
  UPLOADING = 'uploading',
  INDEXED = 'indexed',
  FAILED = 'failed',
}

@Entity('materials')
export class MaterialEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid' })
  topic_id!: string;

  @Column({
    type: 'enum',
    enum: MaterialType,
    default: MaterialType.LITERATURE,
  })
  type!: MaterialType;

  @Column({ type: 'varchar', length: 255 })
  raw_file_path!: string;

  @Column({ type: 'varchar', length: 300 })
  original_filename!: string;

  @Column({ type: 'bigint', default: 0, transformer: bigintToNumber })
  file_size!: number;

  @Index('idx_materials_file_hash')
  @Column({ type: 'varchar', length: 64, nullable: true })
  file_hash?: string;

  @Index('idx_materials_status')
  @Column({
    type: 'enum',
    enum: MaterialStatus,
    default: MaterialStatus.NEW,
  })
  status!: MaterialStatus;

  @Column({ type: 'text', nullable: true })
  error_message?: string;

  @Column({ type: 'varchar', length: 255, nullable: true })
  md_file_path?: string;

  @Column({ type: 'int', default: 0 })
  chunk_count!: number;

  @Column({ type: 'int', default: 0 })
  char_count!: number;

  @Column({ type: 'varchar', length: 30, nullable: true })
  detected_script?: string;

  @Column({ type: 'varchar', length: 64, nullable: true })
  owui_file_id?: string;

  @Column({ type: 'timestamptz', nullable: true })
  indexed_at?: Date;

  @Column({ type: 'uuid', nullable: true })
  uploaded_by_id?: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at!: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  updated_at!: Date;

  @ManyToOne(() => TopicEntity, (topic) => topic.materials, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'topic_id' })
  topic!: Relation<TopicEntity>;

  @ManyToOne(() => UserEntity, {
    onDelete: 'SET NULL',
    nullable: true,
  })
  @JoinColumn({ name: 'uploaded_by_id' })
  uploaded_by?: Relation<UserEntity>;
}
