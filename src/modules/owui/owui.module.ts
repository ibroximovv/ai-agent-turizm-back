import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { OwuiService } from './owui.service.js';
import { OwuiController } from './owui.controller.js';

@Module({
  imports: [ConfigModule],
  controllers: [OwuiController],
  providers: [OwuiService],
  exports: [OwuiService],
})
export class OwuiModule {}
