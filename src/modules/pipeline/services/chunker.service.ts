import { Injectable } from '@nestjs/common';
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as path from 'path';
import { ParsedChunk } from './parser.service.js';

export interface GroundingMetadata {
  /** Discriminates the output file; two materials never share one. */
  materialId: string;
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
  /** Number of source chunks (pages / slides / sections) in the document. */
  chunkCount: number;
  /** Number of `[MANBA: ...]` grounding markers injected into the body. */
  markerCount: number;
  charCount: number;
  filePath: string;
}

const MARKER_INTERVAL = 600;
/** How far past the interval we may look for a nicer split boundary. */
const NEWLINE_LOOKAHEAD = 150;
const SPACE_LOOKAHEAD = 100;

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
    let markerCount = 0;

    // 1. YAML Frontmatter
    lines.push('---');
    lines.push(`module_id: ${this.yamlString(meta.moduleCode)}`);
    lines.push(`module_name: ${this.yamlString(meta.moduleName)}`);
    lines.push(`topic_id: ${this.yamlString(meta.topicCode)}`);
    lines.push(`topic_name: ${this.yamlString(meta.topicName)}`);
    lines.push(`type: ${this.yamlString(meta.materialType)}`);
    lines.push(`source: ${this.yamlString(meta.originalFilename)}`);
    lines.push(`script: ${this.yamlString(meta.detectedScript)}`);
    lines.push(`chunks: ${chunks.length}`);
    lines.push('---');
    lines.push('');

    // 2. Body with grounding markers injected every ~600 chars
    for (const chunk of chunks) {
      const marker = this.buildMarker(meta, chunk.label);

      lines.push(`\n## ${chunk.label.toUpperCase()}\n`);
      lines.push(marker);
      markerCount++;
      lines.push('');

      // Repeat the marker before every follow-up segment so that no vector
      // chunk can end up without its source attribution.
      const segments = this.splitForGrounding(chunk.text);
      segments.forEach((segment, index) => {
        if (index > 0) {
          lines.push('');
          lines.push(marker);
          markerCount++;
          lines.push('');
        }
        lines.push(segment);
      });
      lines.push('');
    }

    const fullMarkdown = lines.join('\n');
    const filename = this.buildFilename(meta);

    const targetDir = path.join(outputDir, this.pathSegment(meta.moduleCode));
    await fs.mkdir(targetDir, { recursive: true });
    const fullPath = path.join(targetDir, filename);

    await fs.writeFile(fullPath, fullMarkdown, 'utf8');

    return {
      markdown: fullMarkdown,
      chunkCount: chunks.length,
      markerCount,
      charCount: fullMarkdown.length,
      filePath: fullPath,
    };
  }

  /**
   * Splits a chunk into ~600 character segments, preferring a nearby newline or
   * space boundary so that words are not cut in half.
   */
  private splitForGrounding(text: string): string[] {
    const segments: string[] = [];
    let start = 0;

    while (start < text.length) {
      let end = start + MARKER_INTERVAL;

      if (end < text.length) {
        const nextNewline = text.indexOf('\n', end);
        const nextSpace = text.indexOf(' ', end);
        if (nextNewline !== -1 && nextNewline - end < NEWLINE_LOOKAHEAD) {
          end = nextNewline;
        } else if (nextSpace !== -1 && nextSpace - end < SPACE_LOOKAHEAD) {
          end = nextSpace;
        }
      }

      // Guarantee forward progress even if a boundary search returns `start`.
      if (end <= start) end = Math.min(start + MARKER_INTERVAL, text.length);

      const segment = text.slice(start, end).trim();
      if (segment) segments.push(segment);
      start = end;
    }

    return segments;
  }

  /**
   * `[MANBA: source | page 14 | topic-01 | literature]`
   *
   * `|` and `]` are stripped from the components so that a marker can never be
   * broken apart by a filename or label.
   */
  private buildMarker(meta: GroundingMetadata, label: string): string {
    const parts = [
      meta.originalFilename,
      label,
      meta.topicCode,
      meta.materialType,
    ].map((part) => part.replace(/[|\]\r\n]+/g, ' ').trim());

    return `[MANBA: ${parts.join(' | ')}]`;
  }

  /**
   * Output name is `{topic}__{type}__{slug}-{fingerprint}.md`.
   *
   * The fingerprint is derived from the material id, so two documents that
   * share a filename inside one topic cannot overwrite each other's markdown -
   * and a re-run of the same material always rewrites the same file. The slug
   * is only there to keep the name readable; it degenerates to `document` for a
   * filename with no ASCII characters.
   */
  private buildFilename(meta: GroundingMetadata): string {
    const slug =
      meta.originalFilename
        .toLowerCase()
        .replace(/\.[a-z0-9]+$/, '')
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 40) || 'document';

    const fingerprint = crypto
      .createHash('sha256')
      .update(meta.materialId)
      .digest('hex')
      .slice(0, 10);

    const topic = this.pathSegment(meta.topicCode);
    const type = this.pathSegment(meta.materialType);

    return `${topic}__${type}__${slug}-${fingerprint}.md`;
  }

  /**
   * Codes come from user input, so never let them escape the output directory.
   */
  private pathSegment(value: string): string {
    const safe = value.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[.-]+/, '');
    return safe || 'unknown';
  }

  /** Emits a double-quoted YAML scalar that cannot break the frontmatter. */
  private yamlString(value: string): string {
    const escaped = value
      .replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"')
      .replace(/[\r\n\t]+/g, ' ');
    return `"${escaped}"`;
  }
}
