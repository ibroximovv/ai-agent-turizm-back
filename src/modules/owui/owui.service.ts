import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosInstance } from 'axios';

export interface OwuiKnowledgeBase {
  id: string;
  name: string;
  description?: string;
  user_id?: string;
  created_at?: number;
  updated_at?: number;
  files?: Array<{ id: string; name: string }>;
}

export interface OwuiFileUploadResult {
  id: string;
  filename: string;
  meta?: Record<string, unknown>;
}

@Injectable()
export class OwuiService {
  private readonly logger = new Logger(OwuiService.name);
  private readonly client: AxiosInstance;
  private readonly baseUrl: string;
  private readonly apiKey?: string;

  constructor(private readonly configService: ConfigService) {
    this.baseUrl = (
      this.configService.get<string>('OWUI_URL', 'http://localhost:8080') || ''
    ).replace(/\/$/, '');
    this.apiKey = this.configService.get<string>('OWUI_API_KEY') || undefined;

    const headers: Record<string, string> = {};
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }

    this.client = axios.create({
      baseURL: this.baseUrl,
      timeout: 30000,
      headers,
    });
  }

  /**
   * Check connection and authentication status with Open WebUI.
   */
  async checkConnection(): Promise<{
    connected: boolean;
    baseUrl: string;
    hasApiKey: boolean;
    knowledgeBasesCount?: number;
    message: string;
  }> {
    if (!this.apiKey) {
      return {
        connected: false,
        baseUrl: this.baseUrl,
        hasApiKey: false,
        message: 'OWUI_API_KEY is not configured in .env',
      };
    }

    try {
      const kbs = await this.listKnowledgeBases();
      return {
        connected: true,
        baseUrl: this.baseUrl,
        hasApiKey: true,
        knowledgeBasesCount: kbs.length,
        message: `Successfully connected to Open WebUI (${kbs.length} Knowledge Bases found)`,
      };
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      this.logger.warn(`Open WebUI connection check failed: ${errorMsg}`);
      return {
        connected: false,
        baseUrl: this.baseUrl,
        hasApiKey: true,
        message: `Failed to connect to ${this.baseUrl}: ${errorMsg}`,
      };
    }
  }

  /**
   * List all knowledge bases in Open WebUI.
   */
  async listKnowledgeBases(): Promise<OwuiKnowledgeBase[]> {
    const res = await this.client.get('/api/v1/knowledge/');
    if (Array.isArray(res.data)) {
      return res.data;
    }
    if (res.data && Array.isArray(res.data.items)) {
      return res.data.items;
    }
    return [];
  }

  /**
   * Create a new knowledge base in Open WebUI.
   */
  async createKnowledgeBase(
    name: string,
    description: string = '',
  ): Promise<OwuiKnowledgeBase> {
    const res = await this.client.post('/api/v1/knowledge/create', {
      name,
      description: description || name,
    });
    return res.data;
  }

  /**
   * Get knowledge base details by ID.
   */
  async getKnowledgeBase(kbId: string): Promise<OwuiKnowledgeBase> {
    const res = await this.client.get(`/api/v1/knowledge/${kbId}`);
    return res.data;
  }

  /**
   * Upload a markdown file directly to Open WebUI files repository.
   */
  async uploadMarkdownFile(
    filename: string,
    content: string | Buffer,
  ): Promise<OwuiFileUploadResult> {
    const formData = new FormData();
    const buffer = typeof content === 'string' ? Buffer.from(content, 'utf8') : content;
    const blob = new Blob([new Uint8Array(buffer)], { type: 'text/markdown' });
    formData.append('file', blob, filename);

    const res = await this.client.post('/api/v1/files/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      params: {
        process: 'true',
      },
    });
    return res.data;
  }

  /**
   * Add a file to a knowledge base.
   */
  async addFileToKnowledgeBase(
    kbId: string,
    fileId: string,
  ): Promise<{ success: boolean }> {
    await this.client.post(`/api/v1/knowledge/${kbId}/file/add`, {
      file_id: fileId,
    });
    return { success: true };
  }

  /**
   * Remove a file from a knowledge base.
   */
  async removeFileFromKnowledgeBase(
    kbId: string,
    fileId: string,
  ): Promise<{ success: boolean }> {
    try {
      await this.client.post(`/api/v1/knowledge/${kbId}/file/remove`, {
        file_id: fileId,
      });
      return { success: true };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.warn(
        `Failed to remove file ${fileId} from KB ${kbId}: ${msg}`,
      );
      return { success: false };
    }
  }

  /**
   * Delete a file from Open WebUI files repository.
   */
  async deleteFile(fileId: string): Promise<{ success: boolean }> {
    try {
      await this.client.delete(`/api/v1/files/${fileId}`);
      return { success: true };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.warn(`Failed to delete file ${fileId} in OWUI: ${msg}`);
      return { success: false };
    }
  }
}
