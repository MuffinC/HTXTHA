// Client-side checks on files before upload (CLAUDE.md section 10).
//
// These are a convenience, not a security boundary: the backend re-validates
// everything. Limits come from GET /api/config, so the two sides always agree.
// Like the backend, the type check reads the file's first bytes ("%PDF-")
// rather than trusting the extension or the browser-reported MIME type.
import type { ConfigResponse } from '../api/types';

export interface FileEntry {
  id: string;
  file: File;
  /** null when the file passed every check. */
  problem: string | null;
}

const PDF_MAGIC = '%PDF-';
let nextId = 0;

/** Read the first bytes as text. FileReader rather than Blob.arrayBuffer(): it also works in jsdom. */
function readHead(file: File, bytes: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file.'));
    reader.readAsText(file.slice(0, bytes), 'latin1');
  });
}

async function startsWithPdfHeader(file: File): Promise<boolean> {
  try {
    return (await readHead(file, PDF_MAGIC.length)) === PDF_MAGIC;
  } catch {
    return false; // unreadable: let the "not a PDF" message explain
  }
}

/** Check one file against type and size limits. Returns a reason, or null if fine. */
export async function checkFile(file: File, config: ConfigResponse): Promise<string | null> {
  if (file.size > config.max_file_mb * 1024 * 1024) {
    return `Larger than the ${config.max_file_mb} MB limit.`;
  }
  if (file.size === 0) return 'The file is empty.';
  if (!(await startsWithPdfHeader(file))) {
    return 'Not a PDF. Only PDF files are supported, whatever the file name says.';
  }
  return null;
}

/**
 * Add new files to an existing list: check each one, skip exact duplicates
 * (same name and size), and mark files beyond the per-upload limit.
 */
export async function addFiles(
  existing: FileEntry[],
  incoming: File[],
  config: ConfigResponse,
): Promise<FileEntry[]> {
  const seen = new Set(existing.map((e) => `${e.file.name}:${e.file.size}`));
  const added: FileEntry[] = [];
  for (const file of incoming) {
    const key = `${file.name}:${file.size}`;
    if (seen.has(key)) continue;
    seen.add(key);
    added.push({ id: `f${nextId++}`, file, problem: await checkFile(file, config) });
  }
  return applyCountLimit([...existing, ...added], config.max_files);
}

/** Mark valid files beyond `maxFiles` as over the limit (and clear that mark if room returns). */
export function applyCountLimit(entries: FileEntry[], maxFiles: number): FileEntry[] {
  const overLimit = `Over the limit of ${maxFiles} files per upload.`;
  let valid = 0;
  return entries.map((entry) => {
    if (entry.problem && entry.problem !== overLimit) return entry;
    valid += 1;
    return { ...entry, problem: valid > maxFiles ? overLimit : null };
  });
}
