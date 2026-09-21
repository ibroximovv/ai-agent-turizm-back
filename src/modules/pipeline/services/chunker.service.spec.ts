import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import { ChunkerService } from './chunker.service.js';
import type { GroundingMetadata } from './chunker.service.js';

const META: GroundingMetadata = {
  materialId: '11111111-1111-4111-8111-111111111111',
  moduleCode: 'module-01',
  moduleName: 'Turizm asoslari',
  topicCode: 'topic-01',
  topicName: 'Qonunchilik asoslari',
  materialType: 'literature',
  originalFilename: 'Constitution.pdf',
  detectedScript: 'uz-latn',
};

describe('ChunkerService', () => {
  const chunker = new ChunkerService();
  let outDir: string;

  beforeEach(async () => {
    outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'chunker-'));
  });

  afterEach(async () => {
    await fs.rm(outDir, { recursive: true, force: true });
  });

  it('writes frontmatter and a marker for a short chunk', async () => {
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 14', text: 'Qisqa matn.' }],
      META,
      outDir,
    );

    expect(result.markdown).toContain('module_id: "module-01"');
    expect(result.markdown).toContain('topic_id: "topic-01"');
    expect(result.markdown).toContain('source: "Constitution.pdf"');
    expect(result.markdown).toContain('chunks: 1');
    expect(result.markdown).toContain(
      '[MANBA: Constitution.pdf | page 14 | topic-01 | literature]',
    );
    expect(result.chunkCount).toBe(1);
    expect(result.markerCount).toBe(1);

    const onDisk = await fs.readFile(result.filePath, 'utf8');
    expect(onDisk).toBe(result.markdown);
  });

  it('repeats the marker roughly every 600 characters', async () => {
    const text = 'abcdefghij '.repeat(300); // ~3300 chars, no newlines
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text }],
      META,
      outDir,
    );

    const markers = result.markdown.match(/\[MANBA: /g) ?? [];
    expect(markers.length).toBe(result.markerCount);
    expect(markers.length).toBeGreaterThanOrEqual(5);
  });

  it('never loses text while splitting', async () => {
    const text = 'x'.repeat(2500);
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text }],
      META,
      outDir,
    );

    const body = result.markdown
      .split('---')
      .slice(2)
      .join('---')
      .replace(/\[MANBA:[^\]]*\]/g, '')
      .replace(/##.*/g, '')
      .replace(/\s/g, '');
    expect(body).toBe(text);
  });

  it('gives non-ASCII filenames distinct, stable output paths', async () => {
    const first = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'matn' }],
      {
        ...META,
        materialId: '22222222-2222-4222-8222-222222222222',
        originalFilename: 'Ўзбекистон Конституцияси.pdf',
      },
      outDir,
    );
    const second = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'matn' }],
      {
        ...META,
        materialId: '33333333-3333-4333-8333-333333333333',
        originalFilename: 'Меҳнат кодекси.pdf',
      },
      outDir,
    );

    expect(first.filePath).not.toBe(second.filePath);

    // Re-processing the same material must overwrite the same file.
    const again = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'boshqa matn' }],
      {
        ...META,
        materialId: '22222222-2222-4222-8222-222222222222',
        originalFilename: 'Ўзбекистон Конституцияси.pdf',
      },
      outDir,
    );
    expect(again.filePath).toBe(first.filePath);

    const written = await fs.readdir(path.join(outDir, 'module-01'));
    expect(written).toHaveLength(2);
  });

  it('keeps two materials that share a filename in separate files', async () => {
    const shared = { ...META, originalFilename: 'Qonun.pdf' };

    const first = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'birinchi hujjat' }],
      { ...shared, materialId: '44444444-4444-4444-8444-444444444444' },
      outDir,
    );
    const second = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'ikkinchi hujjat' }],
      { ...shared, materialId: '55555555-5555-4555-8555-555555555555' },
      outDir,
    );

    expect(first.filePath).not.toBe(second.filePath);
    expect(await fs.readFile(first.filePath, 'utf8')).toContain(
      'birinchi hujjat',
    );
    expect(await fs.readFile(second.filePath, 'utf8')).toContain(
      'ikkinchi hujjat',
    );
  });

  it('keeps codes from escaping the output directory', async () => {
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'matn' }],
      { ...META, moduleCode: '../../etc', topicCode: '../evil' },
      outDir,
    );

    expect(path.resolve(result.filePath).startsWith(path.resolve(outDir))).toBe(
      true,
    );
    expect(result.filePath).not.toContain('..');
  });

  it('escapes quotes and backslashes in frontmatter values', async () => {
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'matn' }],
      { ...META, topicName: 'He said "hi"\\done', moduleName: 'Line\nbreak' },
      outDir,
    );

    expect(result.markdown).toContain('topic_name: "He said \\"hi\\"\\\\done"');
    expect(result.markdown).toContain('module_name: "Line break"');

    // The frontmatter block must still be exactly three lines of delimiters.
    const [, frontmatter] = result.markdown.split('---');
    expect(frontmatter.split('\n').filter((l) => l.trim()).length).toBe(8);
  });

  it('strips marker delimiters out of the source filename', async () => {
    const result = await chunker.buildGroundedMarkdown(
      [{ label: 'page 1', text: 'matn' }],
      { ...META, originalFilename: 'we|ird]name.pdf' },
      outDir,
    );

    const marker = /\[MANBA:[^\]]*\]/.exec(result.markdown)?.[0] ?? '';
    expect(marker.split('|')).toHaveLength(4);
    expect(marker.endsWith('literature]')).toBe(true);
  });
});
