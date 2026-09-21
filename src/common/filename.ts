import * as path from 'path';

/**
 * Multipart parsers decode the `filename` in a Content-Disposition header as
 * latin1, so a UTF-8 name such as `Ўзбекистон.pdf` arrives as the mojibake
 * `Ð�Ð·Ð±ÐµÐºÐ¸ÑÑÐ¾Ð½.pdf`. Storing that would corrupt the `source:` frontmatter
 * and every `[MANBA: ...]` grounding marker built from it.
 *
 * Only strings that are entirely within latin1 range are reinterpreted, and
 * only when the result is valid UTF-8 — so genuine latin1 names (`café.pdf`)
 * and already-correct names are returned unchanged.
 */
export function decodeMultipartFilename(name: string): string {
  if (!name) return name;

  // A character above U+00FF means the name was already decoded as UTF-8.
  for (const char of name) {
    if (char.codePointAt(0)! > 0xff) return name;
  }

  const reinterpreted = Buffer.from(name, 'latin1').toString('utf8');
  if (reinterpreted === name) return name;
  // U+FFFD means the bytes were not UTF-8 after all.
  if (reinterpreted.includes('�')) return name;

  return reinterpreted;
}

/**
 * Reduces a name to characters that are safe in a path segment. The extension
 * is preserved separately by the caller, because the pipeline selects its
 * parser from the stored file's extension.
 */
export function sanitizePathSegment(
  value: string,
  fallback = 'unnamed',
): string {
  const safe = value
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^[.\-_]+/, '')
    .slice(0, 120);
  return safe || fallback;
}

/**
 * `{hash12}__{safe-base}{ext}` — the hash prefix keeps two different documents
 * that happen to share a filename from overwriting each other, and the
 * extension is always kept so the parser can be selected from the path.
 */
export function buildStoredFilename(
  originalName: string,
  extension: string,
  contentHash: string,
): string {
  const base = path.basename(originalName, extension);
  return `${contentHash.slice(0, 12)}__${sanitizePathSegment(base)}${extension}`;
}
