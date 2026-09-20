import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn,
  ManyToOne,
  OneToMany,
  JoinColumn,
  Unique,
  type Relation,
} from 'typeorm';
import { ModuleEntity } from './module.entity.js';
import type { MaterialEntity } from './material.entity.js';

@Entity('topics')
@Unique('uq_topics_module_code', ['module_id', 'code'])
export class TopicEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid' })
  module_id!: string;

  @Column({ type: 'varchar', length: 40 })
  code!: string;

  @Column({ type: 'varchar', length: 300 })
  name!: string;

  @Column({ type: 'text', nullable: true })
  description?: string;

  @Column({ type: 'int', default: 0 })
  order_index!: number;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at!: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  updated_at!: Date;

  @ManyToOne(() => ModuleEntity, (module) => module.topics, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'module_id' })
  module!: Relation<ModuleEntity>;

  @OneToMany('MaterialEntity', 'topic')
  materials!: Relation<MaterialEntity>[];
}
