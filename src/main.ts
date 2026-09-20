import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { AppModule, ObserveInstrument } from './app.module.js';

async function bootstrap() {
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
    .addTag('Open WebUI', 'Open WebUI integration, diagnostics, and Knowledge Bases')
    .addTag('Auth', 'Admin authentication and token management')
    .build();

  const document = SwaggerModule.createDocument(app, swaggerConfig);
  SwaggerModule.setup('api/docs', app, document);

  const port = process.env.PORT ?? 3000;
  await app.listen(port);
  console.log(`🚀 Application running on: http://localhost:${port}/api`);
  console.log(
    `📚 Swagger documentation available at: http://localhost:${port}/api/docs`,
  );
}
await bootstrap();
