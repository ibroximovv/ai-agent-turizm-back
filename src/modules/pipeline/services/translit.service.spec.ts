import { TranslitService } from './translit.service.js';

describe('TranslitService', () => {
  const translit = new TranslitService();

  describe('detectScript', () => {
    it('detects Uzbek Cyrillic by its distinctive letters', () => {
      expect(
        translit.detectScript('Ўзбекистон Республикаси туризм тўғрисида қонун'),
      ).toBe('uz-cyrl');
    });

    it('detects Russian when the Uzbek-only letters are absent', () => {
      expect(
        translit.detectScript('Российская Федерация общие вещи и защита прав'),
      ).toBe('ru');
    });

    it('detects Uzbek Latin', () => {
      expect(
        translit.detectScript('Turizm asoslari va qonunchilik masalalari'),
      ).toBe('uz-latn');
    });

    it('returns other for text with too few letters', () => {
      expect(translit.detectScript('123 — 456')).toBe('other');
    });
  });

  describe('repairUzbekCyrillic', () => {
    it('rewrites a word-final -ии as -ий', () => {
      expect(translit.repairUzbekCyrillic('ташкилотларии.')).toBe(
        'ташкилотларий.',
      );
    });

    it('leaves -ии alone mid-word', () => {
      expect(translit.repairUzbekCyrillic('ииланган')).toBe('ииланган');
    });
  });

  describe('toLatin', () => {
    it('transliterates the Uzbek-specific letters', () => {
      expect(translit.toLatin('ўқғҳ')).toBe('o‘qg‘h');
    });

    it('uses ye at the start of a word and e after a consonant', () => {
      expect(translit.toLatin('ер')).toBe('yer');
      expect(translit.toLatin('бет')).toBe('bet');
    });

    it('uses ye after a vowel', () => {
      expect(translit.toLatin('оеч')).toBe('oyech');
    });

    it('keeps all-caps words in caps', () => {
      expect(translit.toLatin('ШАҲАР')).toBe('SHAHAR');
    });

    it('title-cases multi-letter replacements', () => {
      expect(translit.toLatin('Чегара')).toBe('Chegara');
    });

    it('repairs the corrupted final -ии font artefact', () => {
      expect(translit.toLatin('ташкилотларии')).toBe('tashkilotlariy');
    });

    it('leaves Latin and punctuation untouched', () => {
      expect(translit.toLatin('PDF файл, 2024-йил')).toBe('PDF fayl, 2024-yil');
    });

    it('transliterates Cyrillic letters outside the Uzbek subset', () => {
      expect(translit.toLatin('объект')).toBe('obʼyekt');
    });
  });
});
