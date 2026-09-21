import { Injectable } from '@nestjs/common';

/**
 * Digraphs whose second letter is frequently left lowercase by broken PDF/PPTX
 * font encodings inside otherwise all-caps headings (`TO‘RTINChI BOB`).
 */
const CAPS_DIGRAPHS_GLOBAL = /(Ch|Sh|Yo|Yu|Ya|Ts|Ng)/g;
const CAPS_DIGRAPHS = /(Ch|Sh|Yo|Yu|Ya|Ts|Ng)/;

/** A word, including the apostrophe variants used by `o‘` / `g‘`. */
const WORD_WITH_APOSTROPHES = /[\p{L}\p{M}‘’'ʼ`]+/gu;

@Injectable()
export class CleanerService {
  /**
   * Cleans text layout, unicode anomalies, and capital digraphs.
   */
  cleanText(text: string): string {
    if (!text) return '';

    // 1. Unicode NFC normalization
    let cleaned = text.normalize('NFC');

    // 2. Drop zero-width characters that break word matching and RAG lookups
    cleaned = cleaned.replace(/[\u200b-\u200d\ufeff\u00ad]/g, '');

    // 3. Normalise line endings so the unwrap steps below see plain \n
    cleaned = cleaned.replace(/\r\n?/g, '\n');

    // 4. Replace non-breaking spaces and irregular whitespace
    cleaned = cleaned.replace(
      /[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g,
      ' ',
    );

    // 5. Fix hyphenated line breaks (e.g. "konver- \ntatsiya" -> "konvertatsiya")
    cleaned = cleaned.replace(/(\p{L}+)-[ \t]*\n[ \t]*(\p{L}+)/gu, '$1$2');

    // 6. Unwrap single linebreaks within paragraphs while preserving double
    //    linebreaks. A lookahead is used so that adjacent single newlines are
    //    all unwrapped — a consuming match would skip every other one.
    cleaned = cleaned.replace(/([^\n])\n(?=[^\n])/g, '$1 ');

    // 7. Clean excessive spaces per line
    cleaned = cleaned
      .split('\n')
      .map((line) => line.replace(/[^\S\n]+/g, ' ').trim())
      .join('\n');

    // 8. Repair all-caps words whose digraph tail was decoded as lowercase
    //    (TO‘RTINChI -> TO‘RTINCHI, ShAHARShUNOSLIK -> SHAHARSHUNOSLIK)
    cleaned = this.fixAllCapsDigraphs(cleaned);

    // 9. Collapse more than 2 consecutive newlines into 2
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');

    return cleaned.trim();
  }

  /**
   * Uppercases digraph tails only when doing so leaves the whole word in caps,
   * so ordinary capitalised words (`Shahar`, `Chegara`) are left untouched.
   */
  private fixAllCapsDigraphs(text: string): string {
    return text.replace(WORD_WITH_APOSTROPHES, (word) => {
      if (!CAPS_DIGRAPHS.test(word)) return word;

      const repaired = word.replace(CAPS_DIGRAPHS_GLOBAL, (digraph) =>
        digraph.toUpperCase(),
      );

      // Any remaining lowercase letter means this was a mixed-case word.
      if (/\p{Ll}/u.test(repaired)) return word;
      if (!/\p{Lu}/u.test(word)) return word;

      return repaired;
    });
  }
}
