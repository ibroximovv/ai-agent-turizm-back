import * as path from 'path';

export interface DatabaseConfig {
  host: string;
  port: number;
  username: string;
  password: string;
  database: string;
  synchronize: boolean;
  logging: boolean;
}

export interface OwuiConfig {
  url: string;
  apiKey?: string;
  kbId?: string;
  timeoutMs: number;
}

export interface UploadsConfig {
  /** Absolute root directory holding `raw/` and `ready/` subtrees. */
  rootDir: string;
  rawDir: string;
  readyDir: string;
  maxBytes: number;
}

export interface AppConfig {
  nodeEnv: string;
  port: number;
  database: DatabaseConfig;
  owui: OwuiConfig;
  uploads: UploadsConfig;
}

const DEFAULT_MAX_UPLOAD_MB = 200;

function toInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toBool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value.trim() === '') return fallback;
  return ['true', '1', 'yes', 'on'].includes(value.trim().toLowerCase());
}

/**
 * Maximum accepted upload size in bytes.
 *
 * Read straight from the environment because Multer limits are evaluated when
 * the controller decorators are created, before the DI container exists.
 */
export function maxUploadBytes(): number {
  return toInt(process.env.MAX_UPLOAD_MB, DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024;
}

export function uploadsRootDir(): string {
  return path.resolve(
    process.env.UPLOADS_DIR ?? path.join(process.cwd(), 'uploads'),
  );
}

export const configuration = (): AppConfig => {
  const rootDir = uploadsRootDir();

  return {
    nodeEnv: process.env.NODE_ENV ?? 'development',
    port: toInt(process.env.PORT, 3000),
    database: {
      host: process.env.POSTGRES_HOST ?? 'localhost',
      port: toInt(process.env.POSTGRES_PORT, 5432),
      username: process.env.POSTGRES_USER ?? 'postgres',
      password: process.env.POSTGRES_PASSWORD ?? 'postgres',
      database: process.env.POSTGRES_DB ?? 'turizm_db',
      synchronize: toBool(process.env.POSTGRES_SYNC, true),
      logging: toBool(process.env.POSTGRES_LOGGING, false),
    },
    owui: {
      url: (process.env.OWUI_URL ?? 'http://localhost:8080').replace(
        /\/+$/,
        '',
      ),
      apiKey: process.env.OWUI_API_KEY?.trim() || undefined,
      kbId: process.env.OWUI_KB_ID?.trim() || undefined,
      timeoutMs: toInt(process.env.OWUI_TIMEOUT_MS, 30000),
    },
    uploads: {
      rootDir,
      rawDir: path.join(rootDir, 'raw'),
      readyDir: path.join(rootDir, 'ready'),
      maxBytes: maxUploadBytes(),
    },
  };
};
