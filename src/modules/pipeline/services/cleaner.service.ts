import { Injectable } from '@nestjs/common';

@Injectable()
export class CleanerService {
  /**
   * Cleans text layout, unicode anomalies, and capital digraphs.
   */
  cleanText(text: string): string {
    if (!text) return '';

    // 1. Unicode NFC normalization
    let cleaned = text.normalize('NFC');

    // 2. Replace non-breaking spaces and irregular whitespace
    cleaned = cleaned.replace(/[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g, ' ');

    // 3. Fix hyphenated line breaks (e.g. "konver- \ntatsiya" -> "konvertatsiya")
    cleaned = cleaned.replace(/(\p{L}+)-\s*\n\s*(\p{L}+)/gu, '$1$2');

    // 4. Unwrap single linebreaks within paragraphs while preserving double linebreaks
    cleaned = cleaned.replace(/([^\n])\n([^\n])/g, '$1 $2');

    // 5. Clean excessive spaces per line
    cleaned = cleaned
      .split('\n')
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .join('\n');

    // 6. Fix all-caps digraphs where last char is lowercase (e.g., TO‘RTINChI -> TO‘RTINCHI, TUZILIShI -> TUZILISHI)
    cleaned = cleaned.replace(/\b([A-ZЎҚҒҲ]+)(Ch|Sh|Yo|Yu|Ya|Ts|O‘|G‘)([A-ZЎҚҒҲ]*)\b/g, (_m, p1, p2, p3) => {
      return p1 + p2.toUpperCase() + p3;
    });

    // 7. Collapse more than 2 consecutive newlines into 2
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');

    return cleaned.trim();
  }
}
