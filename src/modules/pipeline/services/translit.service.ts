import { Injectable } from '@nestjs/common';

const UZ_ONLY = new Set('ўқғҳЎҚҒҲ');
const RU_ONLY = new Set('ыщЫЩ');

const MAP: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  ж: 'j',
  з: 'z',
  и: 'i',
  й: 'y',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'x',
  ц: 'ts',
  ч: 'ch',
  ш: 'sh',
  щ: 'sh',
  ъ: 'ʼ',
  ь: '',
  э: 'e',
  ю: 'yu',
  я: 'ya',
  ё: 'yo',
  ў: 'o‘',
  қ: 'q',
  ғ: 'g‘',
  ҳ: 'h',
  ы: 'i',
};

const UPPER_MAP: Record<string, string> = Object.fromEntries(
  Object.entries(MAP).map(([k, v]) => [k.toUpperCase(), v]),
);

/** Every Cyrillic letter the transliterator recognises, as a regex class. */
const CYR_RUN = /[\u0400-\u04ff]+/g;

/**
 * `е` becomes `ye` at the start of a word and after a vowel or a hard/soft
 * sign; elsewhere it is a plain `e`.
 */
const VOWEL_BEFORE_YE = new Set('аеёиоуўэюяъьАЕЁИОУЎЭЮЯЪЬ');
const CYR_LETTER = 'а-яёўқғҳА-ЯЁЎҚҒҲ';
const FIX_FINAL_II = new RegExp(`ии(?![${CYR_LETTER}])`, 'g');

@Injectable()
export class TranslitService {
  isUzbekCyrillic(text: string, sample: number = 4000): boolean {
    const chunk = text.slice(0, sample);
    let uz = 0;
    let ru = 0;
    for (const ch of chunk) {
      if (UZ_ONLY.has(ch)) uz++;
      if (RU_ONLY.has(ch)) ru++;
    }
    return uz > 0 && uz >= ru;
  }

  detectScript(
    text: string,
    sample: number = 4000,
  ): 'uz-latn' | 'uz-cyrl' | 'ru' | 'other' {
    const chunk = text.slice(0, sample);
    let cyr = 0;
    let lat = 0;
    for (const ch of chunk) {
      if (ch >= '\u0400' && ch <= '\u04ff') cyr++;
      else if (ch >= 'a' && ch <= 'z') lat++;
      else if (ch >= 'A' && ch <= 'Z') lat++;
    }
    if (cyr + lat < 10) return 'other';

    if (cyr / (cyr + lat) > 0.3) {
      return this.isUzbekCyrillic(text, sample) ? 'uz-cyrl' : 'ru';
    }
    return lat ? 'uz-latn' : 'other';
  }

  repairUzbekCyrillic(text: string): string {
    return text.replace(FIX_FINAL_II, 'ий');
  }

  private convertE(word: string): string {
    const out: string[] = [];
    for (let i = 0; i < word.length; i++) {
      const ch = word[i];
      if (ch !== '\u0435' && ch !== '\u0415') {
        out.push(ch);
        continue;
      }
      const prev = i > 0 ? word[i - 1] : '';
      if (!prev || VOWEL_BEFORE_YE.has(prev)) {
        out.push(ch === '\u0415' ? 'Ye' : 'ye');
      } else {
        out.push(ch === '\u0415' ? 'E' : 'e');
      }
    }
    return out.join('');
  }

  private translitWord(word: string): string {
    const isUpper = word === word.toUpperCase() && word !== word.toLowerCase();
    const withE = this.convertE(word);
    const out: string[] = [];

    for (const ch of withE) {
      if (MAP[ch] !== undefined) {
        out.push(MAP[ch]);
      } else if (UPPER_MAP[ch] !== undefined) {
        const rep = UPPER_MAP[ch];
        out.push(
          rep.length > 1
            ? rep.charAt(0).toUpperCase() + rep.slice(1).toLowerCase()
            : rep.toUpperCase(),
        );
      } else {
        out.push(ch);
      }
    }

    const res = out.join('');
    return isUpper ? res.toUpperCase() : res;
  }

  toLatin(text: string): string {
    const repaired = this.repairUzbekCyrillic(text);
    // Match the whole Cyrillic block so that letters outside the Uzbek subset
    // (ё, ъ, ь, э and Russian loanword letters) are transliterated too instead
    // of being left behind as stray Cyrillic inside Latin words.
    return repaired.replace(CYR_RUN, (m) => this.translitWord(m));
  }
}
