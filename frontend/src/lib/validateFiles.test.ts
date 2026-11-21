import config from '../test/fixtures/config';
import { pdfFile } from '../test/mockApi';
import { addFiles, applyCountLimit, checkFile } from './validateFiles';

describe('client-side file checks', () => {
  it('accepts a file that starts with a PDF header', async () => {
    expect(await checkFile(pdfFile('report.pdf'), config)).toBeNull();
  });

  it('rejects a renamed text file by its content, not its name', async () => {
    const fake = new File(['hello, not a pdf'], 'fake.pdf', { type: 'application/pdf' });
    expect(await checkFile(fake, config)).toMatch(/Not a PDF/);
  });

  it('rejects files over the configured size limit', async () => {
    const big = pdfFile('big.pdf', 2 * 1024 * 1024);
    expect(await checkFile(big, { ...config, max_file_mb: 1 })).toMatch(/1 MB limit/);
  });

  it('rejects empty files', async () => {
    expect(await checkFile(new File([], 'empty.pdf'), config)).toMatch(/empty/);
  });

  it('skips exact duplicates and marks files beyond the count limit', async () => {
    const limited = { ...config, max_files: 2 };
    const a = pdfFile('a.pdf');
    let entries = await addFiles([], [a, pdfFile('b.pdf', 5), pdfFile('c.pdf', 9)], limited);
    entries = await addFiles(entries, [a], limited); // duplicate ignored

    expect(entries.map((e) => [e.file.name, e.problem])).toEqual([
      ['a.pdf', null],
      ['b.pdf', null],
      ['c.pdf', 'Over the limit of 2 files per upload.'],
    ]);
    // Removing one frees a slot again.
    expect(applyCountLimit(entries.slice(1), 2).every((e) => e.problem === null)).toBe(true);
  });
});
