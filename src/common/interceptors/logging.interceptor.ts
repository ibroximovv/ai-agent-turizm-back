import {
  CallHandler,
  ExecutionContext,
  Injectable,
  Logger,
  NestInterceptor,
} from '@nestjs/common';
import { Observable, tap } from 'rxjs';

/** Logs method, path and duration for every handled request. */
@Injectable()
export class LoggingInterceptor implements NestInterceptor {
  private readonly logger = new Logger('HTTP');

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<{
      method?: string;
      originalUrl?: string;
      url?: string;
    }>();
    const method = request.method ?? 'UNKNOWN';
    const url = request.originalUrl ?? request.url ?? '';
    const startedAt = Date.now();

    return next.handle().pipe(
      tap({
        next: () => {
          this.logger.log(`${method} ${url} — ${Date.now() - startedAt}ms`);
        },
        error: (err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          this.logger.warn(
            `${method} ${url} — failed after ${Date.now() - startedAt}ms: ${message}`,
          );
        },
      }),
    );
  }
}
