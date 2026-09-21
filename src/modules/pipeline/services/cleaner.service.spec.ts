import { CleanerService } from './cleaner.service.js';

describe('CleanerService', () => {
  const cleaner = new CleanerService();

  it('returns an empty string for empty input', () => {
    expect(cleaner.cleanText('')).toBe('');
  });

  it('unwraps every single newline inside a paragraph', () => {
    expect(cleaner.cleanText('bir\nikki\nuch')).toBe('bir ikki uch');
  });

  it('unwraps adjacent newlines even around one-character lines', () => {
    // A consuming regex would skip every other newline and leave "a\nikki".
    expect(cleaner.cleanText('bir\na\nikki')).toBe('bir a ikki');
  });

  it('keeps paragraph breaks', () => {
    expect(cleaner.cleanText('birinchi band\n\nikkinchi band')).toBe(
      'birinchi band\n\nikkinchi band',
    );
  });

  it('collapses runs of more than two newlines', () => {
    expect(cleaner.cleanText('a\n\n\n\nb')).toBe('a\n\nb');
  });

  it('normalises CRLF line endings', () => {
    expect(cleaner.cleanText('bir\r\nikki')).toBe('bir ikki');
  });

  it('rejoins words broken by a hyphenated line break', () => {
    expect(cleaner.cleanText('konver-\ntatsiya')).toBe('konvertatsiya');
  });

  it('replaces non-breaking spaces with regular spaces', () => {
    expect(cleaner.cleanText('turizm asoslari')).toBe('turizm asoslari');
  });

  it('drops zero-width characters', () => {
    expect(cleaner.cleanText('tur​izm')).toBe('turizm');
  });

  describe('all-caps digraph repair', () => {
    it('repairs a trailing lowercase digraph tail', () => {
      expect(cleaner.cleanText('TO‘RTINChI BOB')).toBe('TO‘RTINCHI BOB');
      expect(cleaner.cleanText('TUZILIShI')).toBe('TUZILISHI');
    });

    it('repairs several digraphs in the same word', () => {
      expect(cleaner.cleanText('ShAHARShUNOSLIK')).toBe('SHAHARSHUNOSLIK');
    });

    it('repairs a word-initial digraph', () => {
      expect(cleaner.cleanText('ChIQISh')).toBe('CHIQISH');
    });

    it('repairs digraphs around o‘ / g‘', () => {
      expect(cleaner.cleanText('MAShG‘ULOT')).toBe('MASHG‘ULOT');
    });

    it('leaves ordinary capitalised words untouched', () => {
      expect(cleaner.cleanText('Shahar va Chegara')).toBe('Shahar va Chegara');
    });

    it('leaves lowercase words untouched', () => {
      expect(cleaner.cleanText('shahar chegara')).toBe('shahar chegara');
    });
  });
});
