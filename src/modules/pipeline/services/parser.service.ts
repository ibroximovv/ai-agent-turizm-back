import { Injectable, Logger } from '@nestjs/common';
import * as fs from 'fs/promises';
import * as path from 'path';
import AdmZip from 'adm-zip';
import mammoth from 'mammoth';
import { PDFParse } from 'pdf-parse';

export interface ParsedChunk {
  label: string; // e.g. "page 1" or "slide 3" or "section 1"
  text: string;
}

export interface ParsedDocument {
  chunks: ParsedChunk[];
  totalChars: number;
  warnings: string[];
}

/** Text runs inside DrawingML (`<a:t>`), used by both slides and notes. */
const DRAWINGML_TEXT = /<a:t(?:\s[^>]*)?>([\s\S]*?)<\/a:t>/g;
/** Paragraph boundaries inside a shape's text body. */
const DRAWINGML_PARAGRAPH = /<a:p(?:\s[^>]*)?>[\s\S]*?<\/a:p>/g;
const SLIDE_ENTRY = /^ppt\/slides\/slide(\d+)\.xml$/;
/** Below this, a PDF page is most likely a scanned image rather than text. */
const SPARSE_PAGE_THRESHOLD = 40;

/**
 * `convertToMarkdown` is shipped by mammoth but missing from its bundled
 * typings, so the surface we use is declared explicitly.
 */
interface MammothResult {
  value: string;
  messages?: Array<{ message?: string }>;
}
interface MammothMarkdownApi {
  convertToMarkdown(input: { path: string }): Promise<MammothResult>;
}

@Injectable()
export class ParserService {
  private readonly logger = new Logger(ParserService.name);

  async parseFile(filePath: string): Promise<ParsedDocument> {
    const ext = path.extname(filePath).toLowerCase();

    switch (ext) {
      case '.pdf':
        return this.parsePdf(filePath);
      case '.pptx':
        return this.parsePptx(filePath);
      case '.docx':
        return this.parseDocx(filePath);
      case '.txt':
      case '.md':
        return this.parseTextFile(filePath);
      default:
        throw new Error(
          `Unsupported file format: ${ext}. Only .pdf, .pptx, .docx, .txt, and .md are supported.`,
        );
    }
  }

  private async parsePdf(filePath: string): Promise<ParsedDocument> {
    const buffer = await fs.readFile(filePath);
    const warnings: string[] = [];
    const parser = new PDFParse({ data: buffer });

    try {
      const textResult = await parser.getText();

      const chunks: ParsedChunk[] = [];
      let totalChars = 0;

      for (const page of textResult.pages) {
        const pageText = (page.text || '').trim();
        if (!pageText) continue;

        if (pageText.length < SPARSE_PAGE_THRESHOLD) {
          warnings.push(
            `Page ${page.num} contains very little text (${pageText.length} chars) - might be a scanned image.`,
          );
        }

        chunks.push({
          label: `page ${page.num}`,
          text: pageText,
        });
        totalChars += pageText.length;
      }

      if (chunks.length === 0) {
        warnings.push(
          'No extractable text found in the PDF - the document is likely scanned and needs OCR.',
        );
      }

      return { chunks, totalChars, warnings };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.error(`Error parsing PDF ${filePath}: ${msg}`);
      throw new Error(`Failed to parse PDF: ${msg}`);
    } finally {
      // Always release the worker, including on the failure path.
      await parser.destroy().catch(() => undefined);
    }
  }

  private async parsePptx(filePath: string): Promise<ParsedDocument> {
    const zip = new AdmZip(filePath);
    const warnings: string[] = [];

    // Sort by the slide number encoded in the entry name, not lexically.
    const slideEntries = zip
      .getEntries()
      .map((entry) => {
        const match = SLIDE_ENTRY.exec(entry.entryName);
        return match
          ? { entry, num: Number.parseInt(match[1], 10) }
          : undefined;
      })
      .filter(
        (item): item is { entry: AdmZip.IZipEntry; num: number } => !!item,
      )
      .sort((a, b) => a.num - b.num);

    if (slideEntries.length === 0) {
      warnings.push('No slides found in PPTX presentation.');
    }

    const chunks: ParsedChunk[] = [];
    let totalChars = 0;

    for (const { entry, num } of slideEntries) {
      const slideXml = entry.getData().toString('utf8');
      const slideText = this.extractDrawingMlParagraphs(slideXml).join('\n');

      // Notes are keyed by the slide's own number, so a gap in the slide
      // numbering must not shift the notes onto a neighbouring slide.
      const noteEntry = zip.getEntry(`ppt/notesSlides/notesSlide${num}.xml`);
      const notesText = noteEntry
        ? this.extractDrawingMlText(noteEntry.getData().toString('utf8')).join(
            ' ',
          )
        : '';

      let combinedText = slideText;
      if (notesText) {
        combinedText += `\n\n[Presenter Notes: ${notesText}]`;
      }
      combinedText = combinedText.trim();

      if (combinedText) {
        chunks.push({ label: `slide ${num}`, text: combinedText });
        totalChars += combinedText.length;
      }
    }

    return { chunks, totalChars, warnings };
  }

  private async parseDocx(filePath: string): Promise<ParsedDocument> {
    try {
      const api = mammoth as unknown as MammothMarkdownApi;
      const result = await api.convertToMarkdown({ path: filePath });
      const md: string = result.value || '';
      const warnings: string[] = (result.messages ?? [])
        .map((m) => m.message)
        .filter((m): m is string => !!m);

      // Split into sections at markdown headings.
      const chunks = this.toSequentialChunks(
        md.split(/(?=^#{1,3}\s)/m),
        'section',
      );

      if (chunks.length === 0 && md.trim()) {
        chunks.push({ label: 'section 1', text: md.trim() });
      }

      return {
        chunks,
        totalChars: chunks.reduce((sum, c) => sum + c.text.length, 0),
        warnings,
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`Failed to parse DOCX: ${msg}`);
    }
  }

  private async parseTextFile(filePath: string): Promise<ParsedDocument> {
    const content = await fs.readFile(filePath, 'utf8');
    const chunks = this.toSequentialChunks(
      content.split(/(?:\r?\n){3,}/),
      'part',
    );

    if (chunks.length === 0 && content.trim()) {
      chunks.push({ label: 'part 1', text: content.trim() });
    }

    return {
      chunks,
      totalChars: chunks.reduce((sum, c) => sum + c.text.length, 0),
      warnings: [],
    };
  }

  /**
   * Labels are numbered over the kept sections only, so the emitted grounding
   * markers never reference a section that is missing from the document.
   */
  private toSequentialChunks(
    rawSections: string[],
    labelPrefix: string,
  ): ParsedChunk[] {
    const chunks: ParsedChunk[] = [];
    for (const raw of rawSections) {
      const text = raw.trim();
      if (!text) continue;
      chunks.push({ label: `${labelPrefix} ${chunks.length + 1}`, text });
    }
    return chunks;
  }

  /** One entry per `<a:p>` paragraph, preserving the shape's line structure. */
  private extractDrawingMlParagraphs(xml: string): string[] {
    const paragraphs = xml.match(DRAWINGML_PARAGRAPH);
    if (!paragraphs) return this.extractDrawingMlText(xml);

    return paragraphs
      .map((paragraph) => this.extractDrawingMlText(paragraph).join(''))
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  private extractDrawingMlText(xml: string): string[] {
    const runs: string[] = [];
    for (const match of xml.matchAll(DRAWINGML_TEXT)) {
      const text = this.decodeXmlEntities(match[1]);
      if (text.trim()) runs.push(text);
    }
    return runs;
  }

  /**
   * OOXML escapes `& < > " '` and may use numeric references; leaving them
   * encoded would put literal `&amp;` sequences into the knowledge base.
   */
  private decodeXmlEntities(value: string): string {
    return value
      .replace(/&#x([0-9a-f]+);/gi, (_m, hex: string) =>
        String.fromCodePoint(Number.parseInt(hex, 16)),
      )
      .replace(/&#(\d+);/g, (_m, dec: string) =>
        String.fromCodePoint(Number.parseInt(dec, 10)),
      )
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'")
      .replace(/&amp;/g, '&');
  }
}
