import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosError, AxiosInstance, AxiosResponse } from 'axios';
import type { OwuiConfig } from '../../config/configuration.js';

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
    const config = this.configService.get<OwuiConfig>('owui');
    this.baseUrl = (config?.url ?? 'http://localhost:8080').replace(/\/+$/, '');
    this.apiKey = config?.apiKey;

    const headers: Record<string, string> = {};
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }

    this.client = axios.create({
      baseURL: this.baseUrl,
      timeout: config?.timeoutMs ?? 30000,
      headers,
    });
  }

  /** True when an API key is present, i.e. calls have a chance of succeeding. */
  isConfigured(): boolean {
    return !!this.apiKey;
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
    if (!this.isConfigured()) {
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
      const errorMsg = this.describeError(err);
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
    const data = await this.request('List knowledge bases', () =>
      this.client.get<OwuiKnowledgeBase[] | { items?: OwuiKnowledgeBase[] }>(
        '/api/v1/knowledge/',
      ),
    );

    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.items)) return data.items;
    return [];
  }

  /**
   * Create a new knowledge base in Open WebUI.
   */
  async createKnowledgeBase(
    name: string,
    description: string = '',
  ): Promise<OwuiKnowledgeBase> {
    return this.request(`Create knowledge base "${name}"`, () =>
      this.client.post<OwuiKnowledgeBase>('/api/v1/knowledge/create', {
        name,
        description: description || name,
      }),
    );
  }

  /**
   * Get knowledge base details by ID.
   */
  async getKnowledgeBase(kbId: string): Promise<OwuiKnowledgeBase> {
    return this.request(`Get knowledge base ${kbId}`, () =>
      this.client.get<OwuiKnowledgeBase>(
        `/api/v1/knowledge/${encodeURIComponent(kbId)}`,
      ),
    );
  }

  /**
   * Upload a markdown file directly to Open WebUI files repository.
   */
  async uploadMarkdownFile(
    filename: string,
    content: string | Buffer,
  ): Promise<OwuiFileUploadResult> {
    const formData = new FormData();
    const buffer =
      typeof content === 'string' ? Buffer.from(content, 'utf8') : content;
    const blob = new Blob([new Uint8Array(buffer)], { type: 'text/markdown' });
    formData.append('file', blob, filename);

    // The Content-Type header is intentionally left unset: axios derives it
    // from the FormData together with the multipart boundary.
    return this.request(`Upload "${filename}"`, () =>
      this.client.post<OwuiFileUploadResult>('/api/v1/files/', formData, {
        params: { process: 'true' },
      }),
    );
  }

  /**
   * Add a file to a knowledge base.
   */
  async addFileToKnowledgeBase(
    kbId: string,
    fileId: string,
  ): Promise<{ success: boolean }> {
    await this.request(`Link file ${fileId} to KB ${kbId}`, () =>
      this.client.post(
        `/api/v1/knowledge/${encodeURIComponent(kbId)}/file/add`,
        { file_id: fileId },
      ),
    );
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
      await this.client.post(
        `/api/v1/knowledge/${encodeURIComponent(kbId)}/file/remove`,
        { file_id: fileId },
      );
      return { success: true };
    } catch (err: unknown) {
      const msg = this.describeError(err);
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
      await this.client.delete(`/api/v1/files/${encodeURIComponent(fileId)}`);
      return { success: true };
    } catch (err: unknown) {
      const msg = this.describeError(err);
      this.logger.warn(`Failed to delete file ${fileId} in OWUI: ${msg}`);
      return { success: false };
    }
  }

  /**
   * Keeps the reason Open WebUI rejected a call attached to the error, so it
   * reaches the material's `error_message` and the audit log.
   */
  private async request<T>(
    label: string,
    call: () => Promise<AxiosResponse<T>>,
  ): Promise<T> {
    try {
      const res = await call();
      return res.data;
    } catch (err: unknown) {
      throw new Error(`${label}: ${this.describeError(err)}`);
    }
  }

  /**
   * Axios reports every non-2xx as a bare "Request failed with status code
   * 401", which hides the reason Open WebUI rejected the call.
   */
  private describeError(err: unknown): string {
    if (axios.isAxiosError(err)) {
      const axiosErr = err as AxiosError<{ detail?: string; message?: string }>;
      const status = axiosErr.response?.status;
      const detail =
        axiosErr.response?.data?.detail ??
        axiosErr.response?.data?.message ??
        axiosErr.message;
      return status ? `HTTP ${status}: ${detail}` : detail;
    }
    return err instanceof Error ? err.message : String(err);
  }
}
