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

    try {
      const parser = new PDFParse({ data: buffer });
      const textResult = await parser.getText();
      await parser.destroy();

      const chunks: ParsedChunk[] = [];
      let totalChars = 0;

      for (const page of textResult.pages) {
        const pageText = (page.text || '').trim();
        if (!pageText) continue;

        if (pageText.length < 40) {
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

      return { chunks, totalChars, warnings };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.error(`Error parsing PDF ${filePath}: ${msg}`);
      throw new Error(`Failed to parse PDF: ${msg}`);
    }
  }

  private async parsePptx(filePath: string): Promise<ParsedDocument> {
    const zip = new AdmZip(filePath);
    const zipEntries = zip.getEntries();
    const warnings: string[] = [];

    // Filter and sort slide xml entries
    const slideEntries = zipEntries
      .filter((e) => /^ppt\/slides\/slide\d+\.xml$/.test(e.entryName))
      .sort((a, b) => {
        const numA = parseInt(a.entryName.match(/\d+/)![0], 10);
        const numB = parseInt(b.entryName.match(/\d+/)![0], 10);
        return numA - numB;
      });

    if (slideEntries.length === 0) {
      warnings.push('No slides found in PPTX presentation.');
    }

    const chunks: ParsedChunk[] = [];
    let totalChars = 0;

    for (let i = 0; i < slideEntries.length; i++) {
      const slideXml = slideEntries[i].getData().toString('utf8');
      const slideNum = i + 1;

      // Extract all <a:t>...</a:t> text tags
      const textMatches = slideXml.match(/<a:t[^>]*>([\s\S]*?)<\/a:t>/gi) || [];
      const slideTexts = textMatches.map((m) =>
        m.replace(/<[^>]+>/g, '').trim(),
      );

      // Check for presenter notes for this slide
      const noteEntry = zip.getEntry(`ppt/notesSlides/notesSlide${slideNum}.xml`);
      let notesText = '';
      if (noteEntry) {
        const noteXml = noteEntry.getData().toString('utf8');
        const noteMatches =
          noteXml.match(/<a:t[^>]*>([\s\S]*?)<\/a:t>/gi) || [];
        notesText = noteMatches
          .map((m) => m.replace(/<[^>]+>/g, '').trim())
          .filter((t) => t.length > 0)
          .join(' ');
      }

      let combinedText = slideTexts.filter((t) => t.length > 0).join('\n');
      if (notesText) {
        combinedText += `\n\n[Presenter Notes: ${notesText}]`;
      }

      if (combinedText.trim()) {
        chunks.push({
          label: `slide ${slideNum}`,
          text: combinedText.trim(),
        });
        totalChars += combinedText.length;
      }
    }

    return { chunks, totalChars, warnings };
  }

  private async parseDocx(filePath: string): Promise<ParsedDocument> {
    try {
      const result = await (mammoth as any).convertToMarkdown({ path: filePath });
      const md: string = result.value || '';
      const warnings: string[] = (result.messages || []).map((m: any) => m.message);

      // Split into sections by markdown headings or paragraphs
      const rawSections = md.split(/(?=^#{1,3}\s)/m);
      const chunks: ParsedChunk[] = [];
      let totalChars = 0;

      for (let i = 0; i < rawSections.length; i++) {
        const sec = rawSections[i].trim();
        if (!sec) continue;
        chunks.push({
          label: `section ${i + 1}`,
          text: sec,
        });
        totalChars += sec.length;
      }

      if (chunks.length === 0 && md.trim()) {
        chunks.push({
          label: 'section 1',
          text: md.trim(),
        });
        totalChars = md.length;
      }

      return { chunks, totalChars, warnings };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`Failed to parse DOCX: ${msg}`);
    }
  }

  private async parseTextFile(filePath: string): Promise<ParsedDocument> {
    const content = await fs.readFile(filePath, 'utf8');
    const sections = content.split(/(?:\r?\n){3,}/);
    const chunks: ParsedChunk[] = [];
    let totalChars = 0;

    for (let i = 0; i < sections.length; i++) {
      const s = sections[i].trim();
      if (!s) continue;
      chunks.push({
        label: `part ${i + 1}`,
        text: s,
      });
      totalChars += s.length;
    }

    if (chunks.length === 0 && content.trim()) {
      chunks.push({
        label: 'part 1',
        text: content.trim(),
      });
      totalChars = content.length;
    }

    return { chunks, totalChars, warnings: [] };
  }
}
