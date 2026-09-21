import { Logger, ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HttpAdapterHost, NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { AppModule, ObserveInstrument } from './app.module.js';
import { AllExceptionsFilter } from './common/filters/all-exceptions.filter.js';
import { LoggingInterceptor } from './common/interceptors/logging.interceptor.js';

async function bootstrap(): Promise<void> {
  const logger = new Logger('Bootstrap');

  const app = await NestFactory.create(AppModule, {
    instrument: ObserveInstrument,
  });

  // Enable CORS
  app.enableCors();

  // Global Validation Pipe
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      transform: true,
      forbidNonWhitelisted: true,
    }),
  );

  // Uniform error payloads, including for driver-level failures
  app.useGlobalFilters(new AllExceptionsFilter(app.get(HttpAdapterHost)));
  app.useGlobalInterceptors(new LoggingInterceptor());

  // Close the database pool and flush in-flight work on SIGTERM/SIGINT
  app.enableShutdownHooks();

  // Global API Prefix
  app.setGlobalPrefix('api');

  // Swagger OpenAPI Documentation
  const swaggerConfig = new DocumentBuilder()
    .setTitle('AI Agent Turizm Backend API')
    .setDescription(
      'Educational content management and grounding pipeline for Open WebUI RAG AI agents',
    )
    .setVersion('1.0.0')
    .addBearerAuth()
    .addTag('System', 'Health and system diagnostics')
    .addTag('Modules', 'Educational modules management and KB creation')
    .addTag('Topics', 'Topics within educational modules')
    .addTag('Materials', 'Document upload and grounding pipeline')
    .addTag('Audit Logs', 'Activity history and pipeline execution logs')
    .addTag(
      'Open WebUI',
      'Open WebUI integration, diagnostics, and Knowledge Bases',
    )
    .build();

  const document = SwaggerModule.createDocument(app, swaggerConfig);
  SwaggerModule.setup('api/docs', app, document);

  const port = app.get(ConfigService).getOrThrow<number>('port');
  await app.listen(port);

  logger.log(`🚀 Application running on: http://localhost:${port}/api`);
  logger.log(
    `📚 Swagger documentation available at: http://localhost:${port}/api/docs`,
  );
}

try {
  await bootstrap();
} catch (err: unknown) {
  // Without this the process exits on an unhandled rejection with no context.
  new Logger('Bootstrap').error(
    `Failed to start application: ${err instanceof Error ? err.message : String(err)}`,
    err instanceof Error ? err.stack : undefined,
  );
  process.exit(1);
}
