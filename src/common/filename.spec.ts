import {
  buildStoredFilename,
  decodeMultipartFilename,
  sanitizePathSegment,
} from './filename.js';

describe('decodeMultipartFilename', () => {
  it('recovers a UTF-8 name that arrived decoded as latin1', () => {
    const utf8Name = 'Ўзбекистон Конституцияси.pdf';
    const asLatin1 = Buffer.from(utf8Name, 'utf8').toString('latin1');

    expect(asLatin1).not.toBe(utf8Name);
    expect(decodeMultipartFilename(asLatin1)).toBe(utf8Name);
  });

  it('leaves plain ASCII names untouched', () => {
    expect(decodeMultipartFilename('Constitution.pdf')).toBe(
      'Constitution.pdf',
    );
  });

  it('leaves an already correctly decoded name untouched', () => {
    expect(decodeMultipartFilename('Меҳнат кодекси.docx')).toBe(
      'Меҳнат кодекси.docx',
    );
  });

  it('leaves a genuine latin1 name untouched', () => {
    // 0xE9 on its own is not valid UTF-8, so no reinterpretation happens.
    expect(decodeMultipartFilename('café.pdf')).toBe('café.pdf');
  });

  it('handles an empty name', () => {
    expect(decodeMultipartFilename('')).toBe('');
  });
});

describe('sanitizePathSegment', () => {
  it('replaces unsafe characters', () => {
    expect(sanitizePathSegment('my report (v2).txt')).toBe('my_report_v2_.txt');
  });

  it('strips leading dots and dashes so no segment can traverse', () => {
    expect(sanitizePathSegment('../../etc')).toBe('etc');
    expect(sanitizePathSegment('..')).toBe('unnamed');
  });

  it('falls back when nothing safe remains', () => {
    expect(sanitizePathSegment('Ўзбекистон')).toBe('unnamed');
  });
});

describe('buildStoredFilename', () => {
  const hash =
    'fdc303ce1833de296eebe3acfd00da59be5ba96a2684e72e11da3334a7cfa6fa';

  it('keeps the extension so the parser can still be selected', () => {
    expect(
      buildStoredFilename('Ўзбекистон Конституцияси.txt', '.txt', hash),
    ).toBe('fdc303ce1833__unnamed.txt');
  });

  it('keeps an ASCII base name readable', () => {
    expect(buildStoredFilename('Constitution.pdf', '.pdf', hash)).toBe(
      'fdc303ce1833__Constitution.pdf',
    );
  });

  it('gives different content under the same name different paths', () => {
    const other = 'aaaa'.repeat(16);
    expect(buildStoredFilename('same.pdf', '.pdf', hash)).not.toBe(
      buildStoredFilename('same.pdf', '.pdf', other),
    );
  });
});
