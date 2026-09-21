import AdmZip from 'adm-zip';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import { ParserService } from './parser.service.js';

function slideXml(...paragraphs: string[][]): string {
  const body = paragraphs
    .map(
      (runs) =>
        `<a:p>${runs.map((r) => `<a:r><a:t>${r}</a:t></a:r>`).join('')}</a:p>`,
    )
    .join('');
  return `<?xml version="1.0"?><p:sld><p:cSld><p:spTree><p:sp><p:txBody>${body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>`;
}

describe('ParserService', () => {
  const parser = new ParserService();
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'parser-'));
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  it('rejects unsupported formats', async () => {
    await expect(parser.parseFile('/tmp/report.xlsx')).rejects.toThrow(
      /Unsupported file format/,
    );
  });

  describe('text files', () => {
    it('splits on blank-line runs and numbers the kept parts sequentially', async () => {
      const file = path.join(tmpDir, 'notes.txt');
      await fs.writeFile(file, 'birinchi\n\n\n\n\nikkinchi\n\n\nuchinchi');

      const parsed = await parser.parseFile(file);

      expect(parsed.chunks.map((c) => c.label)).toEqual([
        'part 1',
        'part 2',
        'part 3',
      ]);
      expect(parsed.chunks[1].text).toBe('ikkinchi');
      expect(parsed.totalChars).toBe(
        'birinchi'.length + 'ikkinchi'.length + 'uchinchi'.length,
      );
    });

    it('falls back to a single part when there are no blank-line runs', async () => {
      const file = path.join(tmpDir, 'flat.md');
      await fs.writeFile(file, '# Sarlavha\nmatn');

      const parsed = await parser.parseFile(file);
      expect(parsed.chunks).toHaveLength(1);
      expect(parsed.chunks[0].label).toBe('part 1');
    });
  });

  describe('pptx files', () => {
    async function writePptx(entries: Record<string, string>): Promise<string> {
      const zip = new AdmZip();
      for (const [name, content] of Object.entries(entries)) {
        zip.addFile(name, Buffer.from(content, 'utf8'));
      }
      const file = path.join(tmpDir, 'deck.pptx');
      zip.writeZip(file);
      return file;
    }

    it('decodes XML entities in slide text', async () => {
      const file = await writePptx({
        'ppt/slides/slide1.xml': slideXml([
          'Turizm &amp; mehmondo&#8216;stlik &lt;asoslar&gt;',
        ]),
      });

      const parsed = await parser.parseFile(file);
      expect(parsed.chunks[0].text).toBe('Turizm & mehmondo‘stlik <asoslar>');
    });

    it('keeps paragraphs on separate lines and joins runs within one', async () => {
      const file = await writePptx({
        'ppt/slides/slide1.xml': slideXml(['Sar', 'lavha'], ['Ikkinchi qator']),
      });

      const parsed = await parser.parseFile(file);
      expect(parsed.chunks[0].text).toBe('Sarlavha\nIkkinchi qator');
    });

    it('sorts slides numerically, not lexically', async () => {
      const file = await writePptx({
        'ppt/slides/slide1.xml': slideXml(['bir']),
        'ppt/slides/slide2.xml': slideXml(['ikki']),
        'ppt/slides/slide10.xml': slideXml(['o‘n']),
      });

      const parsed = await parser.parseFile(file);
      expect(parsed.chunks.map((c) => c.label)).toEqual([
        'slide 1',
        'slide 2',
        'slide 10',
      ]);
    });

    it('matches notes to the slide number, not the slide position', async () => {
      // slide2.xml is absent, so a position-based lookup would attach
      // notesSlide3 to slide 1.
      const file = await writePptx({
        'ppt/slides/slide1.xml': slideXml(['birinchi slayd']),
        'ppt/slides/slide3.xml': slideXml(['uchinchi slayd']),
        'ppt/notesSlides/notesSlide3.xml': slideXml(['uchinchi izoh']),
      });

      const parsed = await parser.parseFile(file);

      expect(parsed.chunks[0].text).toBe('birinchi slayd');
      expect(parsed.chunks[1].text).toContain(
        '[Presenter Notes: uchinchi izoh]',
      );
    });

    it('warns when a presentation holds no slides', async () => {
      const file = await writePptx({ 'docProps/app.xml': '<Properties/>' });

      const parsed = await parser.parseFile(file);
      expect(parsed.chunks).toHaveLength(0);
      expect(parsed.warnings).toContain(
        'No slides found in PPTX presentation.',
      );
    });
  });
});
