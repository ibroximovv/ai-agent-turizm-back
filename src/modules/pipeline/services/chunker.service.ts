import { Injectable } from '@nestjs/common';
import * as fs from 'fs/promises';
import * as path from 'path';
import { ParsedChunk } from './parser.service.js';

export interface GroundingMetadata {
  moduleCode: string;
  moduleName: string;
  topicCode: string;
  topicName: string;
  materialType: string;
  originalFilename: string;
  detectedScript: string;
}

export interface ChunkerResult {
  markdown: string;
  chunkCount: number;
  charCount: number;
  filePath: string;
}

const MARKER_INTERVAL = 600;

@Injectable()
export class ChunkerService {
  /**
   * Builds grounded Markdown with [MANBA: ...] markers and frontmatter.
   */
  async buildGroundedMarkdown(
    chunks: ParsedChunk[],
    meta: GroundingMetadata,
    outputDir: string,
  ): Promise<ChunkerResult> {
    const lines: string[] = [];

    // 1. YAML Frontmatter
    lines.push('---');
    lines.push(`module_id: "${meta.moduleCode}"`);
    lines.push(`module_name: "${this.escapeYaml(meta.moduleName)}"`);
    lines.push(`topic_id: "${meta.topicCode}"`);
    lines.push(`topic_name: "${this.escapeYaml(meta.topicName)}"`);
    lines.push(`type: "${meta.materialType}"`);
    lines.push(`source: "${meta.originalFilename}"`);
    lines.push(`script: "${meta.detectedScript}"`);
    lines.push(`chunks: "${chunks.length}"`);
    lines.push('---');
    lines.push('');

    // 2. Body with grounding markers injected every ~600 chars
    for (const chunk of chunks) {
      const marker = `[MANBA: ${meta.originalFilename} | ${chunk.label} | ${meta.topicCode} | ${meta.materialType}]`;

      lines.push(`\n## ${chunk.label.toUpperCase()}\n`);
      lines.push(marker);
      lines.push('');

      const text = chunk.text;
      if (text.length <= MARKER_INTERVAL) {
        lines.push(text);
      } else {
        // Split longer text into ~600 character segments
        let start = 0;
        while (start < text.length) {
          let end = start + MARKER_INTERVAL;
          if (end < text.length) {
            // Find convenient boundary (newline or space)
            const nextNewline = text.indexOf('\n', end);
            const nextSpace = text.indexOf(' ', end);
            if (nextNewline !== -1 && nextNewline - end < 150) {
              end = nextNewline;
            } else if (nextSpace !== -1 && nextSpace - end < 100) {
              end = nextSpace;
            }
          }

          const segment = text.slice(start, end).trim();
          if (segment) {
            if (start > 0) {
              lines.push('');
              lines.push(marker);
              lines.push('');
            }
            lines.push(segment);
          }
          start = end;
        }
      }
      lines.push('');
    }

    const fullMarkdown = lines.join('\n');
    const slug = meta.originalFilename
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .slice(0, 40);
    const filename = `${meta.topicCode}__${meta.materialType}__${slug}.md`;

    const targetDir = path.join(outputDir, meta.moduleCode);
    await fs.mkdir(targetDir, { recursive: true });
    const fullPath = path.join(targetDir, filename);

    await fs.writeFile(fullPath, fullMarkdown, 'utf8');

    return {
      markdown: fullMarkdown,
      chunkCount: chunks.length,
      charCount: fullMarkdown.length,
      filePath: fullPath,
    };
  }

  private escapeYaml(str: string): string {
    return str.replace(/"/g, '\\"');
  }
}
