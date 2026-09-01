import { readFileSync, readdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { parseFile } from 'music-metadata';
import { config } from './config.js';

// bookId is the folder's own basename (e.g. "test-20260826"), not a raw
// path - every lookup below goes through this fixed, startup-built map
// rather than accepting a filesystem path from a request, which is what
// keeps chapter/book lookups safe from path traversal (see chapters()
// and chapterImages.js for the matching per-chapter check).
const booksById = new Map();
for (const libraryPath of config.libraryPaths) {
  const id = path.basename(libraryPath);
  if (booksById.has(id)) {
    throw new Error(
      `Two configured libraryPaths share the same folder name "${id}" - ` +
      `rename one of the folders so each book gets a unique id.`
    );
  }
  booksById.set(id, libraryPath);
}

const chapterFileRegex = /^(chapter_(\d+))\.mp3$/;

function readBookTitle(bookPath) {
  const bookJsonPath = path.join(bookPath, 'book.json');
  if (!existsSync(bookJsonPath)) return '';
  try {
    return JSON.parse(readFileSync(bookJsonPath, 'utf8')).title || '';
  } catch {
    return '';
  }
}

// Ordered chapter base names (no extension) for one book, e.g.
// ["chapter_001", "chapter_002", ...] - mirrors listChaptersJson() in
// MainActivity.kt exactly (same regex, same numeric sort).
function chapterBases(bookPath) {
  return readdirSync(bookPath)
    .map((name) => chapterFileRegex.exec(name))
    .filter(Boolean)
    .map((m) => ({ base: m[1], num: Number(m[2]) }))
    .sort((a, b) => a.num - b.num)
    .map((c) => c.base);
}

// Title/author-sourcing decision (confirmed against the home-screen
// mockup): book.json's own "title" wins if present; otherwise the first
// chapter's ID3 "album" tag, since that's where these generator-produced
// folders actually carry the book title today; the raw folder id is the
// last resort. Author always comes from the first chapter's ID3 "artist"
// tag - there's no book.json equivalent for that field.
export async function listBooks() {
  const entries = [...booksById.entries()];
  return Promise.all(
    entries.map(async ([id, bookPath]) => {
      const bases = chapterBases(bookPath);
      const bookJsonTitle = readBookTitle(bookPath);
      let title = bookJsonTitle || id;
      let author = '';
      const firstBase = bases[0];
      if (firstBase) {
        try {
          const metadata = await parseFile(path.join(bookPath, `${firstBase}.mp3`));
          if (!bookJsonTitle && metadata.common.album) title = metadata.common.album;
          author = metadata.common.artist || '';
        } catch {
          // Fall back to whatever title we already have; author stays ''.
        }
      }
      return { id, title, author, chapterCount: bases.length };
    })
  );
}

export function getBookPath(bookId) {
  return booksById.get(bookId) || null;
}

export function listChapters(bookPath) {
  return chapterBases(bookPath);
}

// Resolves a requested chapterBase against the *actual* scanned chapter
// list for this book, not just a filename-shape regex - this is the
// hardening step from the plan: a chapterBase that doesn't exactly match
// a real chapter this book actually has is rejected before any path
// gets built from it.
export function resolveChapterBase(bookPath, requestedBase) {
  const bases = chapterBases(bookPath);
  return bases.includes(requestedBase) ? requestedBase : null;
}

export function chapterNumberFromBase(base) {
  const m = /(\d+)$/.exec(base);
  return m ? Number(m[1]) : null;
}
