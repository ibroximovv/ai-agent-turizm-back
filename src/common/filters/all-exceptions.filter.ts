import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { HttpAdapterHost } from '@nestjs/core';
import { QueryFailedError } from 'typeorm';

/** PostgreSQL error codes we can translate into meaningful HTTP responses. */
const PG_UNIQUE_VIOLATION = '23505';
const PG_FOREIGN_KEY_VIOLATION = '23503';
const PG_NOT_NULL_VIOLATION = '23502';

interface ErrorBody {
  statusCode: number;
  message: string | string[];
  error?: string;
  path: string;
  timestamp: string;
}

/**
 * Normalises every error into a single JSON shape and keeps driver-level
 * failures (unique / FK violations) from surfacing as opaque 500s.
 */
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger(AllExceptionsFilter.name);

  constructor(private readonly httpAdapterHost: HttpAdapterHost) {}

  catch(exception: unknown, host: ArgumentsHost): void {
    const { httpAdapter } = this.httpAdapterHost;
    const ctx = host.switchToHttp();
    const request = ctx.getRequest();
    const path: string = httpAdapter.getRequestUrl(request) ?? '';

    const { status, message, error } = this.describe(exception);

    if (status >= HttpStatus.INTERNAL_SERVER_ERROR) {
      this.logger.error(
        `${status} ${path} — ${Array.isArray(message) ? message.join('; ') : message}`,
        exception instanceof Error ? exception.stack : undefined,
      );
    }

    const body: ErrorBody = {
      statusCode: status,
      message,
      error,
      path,
      timestamp: new Date().toISOString(),
    };

    httpAdapter.reply(ctx.getResponse(), body, status);
  }

  private describe(exception: unknown): {
    status: number;
    message: string | string[];
    error?: string;
  } {
    if (exception instanceof HttpException) {
      const response = exception.getResponse();
      if (typeof response === 'string') {
        return { status: exception.getStatus(), message: response };
      }
      const asRecord = response as {
        message?: string | string[];
        error?: string;
      };
      return {
        status: exception.getStatus(),
        message: asRecord.message ?? exception.message,
        error: asRecord.error,
      };
    }

    if (exception instanceof QueryFailedError) {
      const code = (exception as QueryFailedError & { code?: string }).code;
      switch (code) {
        case PG_UNIQUE_VIOLATION:
          return {
            status: HttpStatus.CONFLICT,
            message: 'A record with these unique values already exists',
            error: 'Conflict',
          };
        case PG_FOREIGN_KEY_VIOLATION:
          return {
            status: HttpStatus.BAD_REQUEST,
            message: 'Referenced record does not exist',
            error: 'Bad Request',
          };
        case PG_NOT_NULL_VIOLATION:
          return {
            status: HttpStatus.BAD_REQUEST,
            message: 'A required field is missing',
            error: 'Bad Request',
          };
        default:
          return {
            status: HttpStatus.INTERNAL_SERVER_ERROR,
            message: 'Database query failed',
            error: 'Internal Server Error',
          };
      }
    }

    return {
      status: HttpStatus.INTERNAL_SERVER_ERROR,
      message:
        exception instanceof Error
          ? exception.message
          : 'Internal server error',
      error: 'Internal Server Error',
    };
  }
}
