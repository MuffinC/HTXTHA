// Minimal Markdown pipe-table parser for model-produced tables. Output is
// rendered as text cells (never HTML).

/** Parse a simple Markdown pipe table into rows of cells; null if it is not one. */
export function parseMarkdownTable(markdown: string): string[][] | null {
  const lines = markdown
    .trim()
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length < 2 || !lines.every((l) => l.startsWith('|'))) return null;
  const rows = lines
    .filter((l) => !/^\|[\s:|-]+\|$/.test(l)) // drop the |---|---| separator
    .map((l) =>
      l
        .replace(/^\||\|$/g, '')
        .split('|')
        .map((c) => c.trim()),
    );
  return rows.length ? rows : null;
}
