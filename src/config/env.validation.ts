import { plainToInstance, Transform, Type } from 'class-transformer';
import {
  IsBoolean,
  IsEnum,
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  IsUrl,
  Max,
  Min,
  validateSync,
} from 'class-validator';

/**
 * Env values are always strings, so `Boolean('false')` would wrongly yield true.
 * Unrecognised values are left as-is so that @IsBoolean() reports them.
 */
function parseBool(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  const normalized = value.trim().toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(normalized)) return true;
  if (['false', '0', 'no', 'off'].includes(normalized)) return false;
  return value;
}

export enum NodeEnv {
  DEVELOPMENT = 'development',
  PRODUCTION = 'production',
  TEST = 'test',
}

/**
 * Shape of the environment variables the application depends on.
 * Only declared keys are validated; every other variable is passed through.
 */
export class EnvironmentVariables {
  @IsOptional()
  @IsEnum(NodeEnv)
  NODE_ENV?: NodeEnv;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(65535)
  PORT?: number;

  @IsOptional()
  @IsString()
  UPLOADS_DIR?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  MAX_UPLOAD_MB?: number;

  @IsOptional()
  @IsString()
  @IsNotEmpty()
  POSTGRES_HOST?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(65535)
  POSTGRES_PORT?: number;

  @IsOptional()
  @IsString()
  @IsNotEmpty()
  POSTGRES_USER?: string;

  @IsOptional()
  @IsString()
  POSTGRES_PASSWORD?: string;

  @IsOptional()
  @IsString()
  @IsNotEmpty()
  POSTGRES_DB?: string;

  @IsOptional()
  @Transform(({ value }) => parseBool(value))
  @IsBoolean()
  POSTGRES_SYNC?: boolean;

  @IsOptional()
  @Transform(({ value }) => parseBool(value))
  @IsBoolean()
  POSTGRES_LOGGING?: boolean;

  @IsOptional()
  @IsUrl({ require_tld: false, require_protocol: true })
  OWUI_URL?: string;

  @IsOptional()
  @IsString()
  OWUI_API_KEY?: string;

  @IsOptional()
  @IsString()
  OWUI_KB_ID?: string;
}

/**
 * Fails fast at bootstrap when a declared variable holds an unusable value,
 * instead of surfacing as an obscure driver error on the first query.
 * The original config object is returned untouched so that undeclared
 * variables stay reachable through ConfigService.
 */
export function validateEnv(
  config: Record<string, unknown>,
): Record<string, unknown> {
  const instance = plainToInstance(EnvironmentVariables, config, {
    // Env values always arrive as strings; @Type handles the declared coercions.
    enableImplicitConversion: false,
  });

  const errors = validateSync(instance, {
    skipMissingProperties: false,
    whitelist: false,
    forbidNonWhitelisted: false,
  });

  if (errors.length > 0) {
    const details = errors
      .map(
        (e) =>
          `  - ${e.property}: ${Object.values(e.constraints ?? {}).join('; ')}`,
      )
      .join('\n');
    throw new Error(`Invalid environment configuration:\n${details}`);
  }

  return config;
}
