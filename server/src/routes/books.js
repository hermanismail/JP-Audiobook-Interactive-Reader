import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import express from 'express';
import { parseFile } from 'music-metadata';
import {
  listBooks,
  getBookPath,
  listChapters,
  resolveChapterBase,
  chapterNumberFromBase,
} from '../library.js';
import { resolveChapterImages, isRealChapterImage } from '../chapterImages.js';

export const router = express.Router();

// Every route below resolves :bookId/:chapterBase through the in-memory
// allowlists built from config (getBookPath/resolveChapterBase) before
// touching the filesystem - neither ever accepts a raw path from the
// request, which is what keeps this safe once it's internet-facing
// (see the "Hardening" note in the roadmap plan).

export function requireBook(req, res) {
  const bookPath = getBookPath(req.params.bookId);
  if (!bookPath) {
    res.status(404).json({ error: `Unknown book "${req.params.bookId}"` });
    return null;
  }
  return bookPath;
}

function requireChapter(req, res, bookPath) {
  const base = resolveChapterBase(bookPath, req.params.chapterBase);
  if (!base) {
    res.status(404).json({ error: `Unknown chapter "${req.params.chapterBase}"` });
    return null;
  }
  return base;
}

async function sendCoverArt(mp3Path, res) {
  try {
    const metadata = await parseFile(mp3Path);
    const picture = metadata.common.picture?.[0];
    if (!picture) return res.status(404).json({ error: 'No embedded cover art' });
    res.type(picture.format).send(Buffer.from(picture.data));
  } catch (err) {
    res.status(500).json({ error: `Could not read cover art: ${err.message}` });
  }
}

router.get('/books', async (req, res) => {
  res.json({ books: await listBooks() });
});

router.get('/books/:bookId/chapters', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  res.json({ chapters: listChapters(bookPath) });
});

router.get('/books/:bookId/chapters/:chapterBase/sync', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  const syncPath = path.join(bookPath, `${base}.sync.json`);
  if (!existsSync(syncPath)) {
    return res.status(404).json({ error: `No sync.json for "${base}"` });
  }
  res.type('application/json').send(readFileSync(syncPath, 'utf8'));
});

// Optional per-chapter translation subtitle, plain SRT - a book/chapter
// simply doesn't have one unless the file exists in the folder (nothing
// in book.json/sync.json declares it), matching the same
// resolve-or-404 pattern as sync.json above.
router.get('/books/:bookId/chapters/:chapterBase/subtitle', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  const srtPath = path.join(bookPath, `${base}.srt`);
  if (!existsSync(srtPath)) {
    return res.status(404).json({ error: `No subtitle for "${base}"` });
  }
  res.type('text/plain').send(readFileSync(srtPath, 'utf8'));
});

router.get('/books/:bookId/chapters/:chapterBase/images', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  const chapterNum = chapterNumberFromBase(base);
  const images = chapterNum === null ? [] : resolveChapterImages(bookPath, chapterNum);
  res.json({ images });
});

// Serves one chapter-image file's raw bytes, by filename - the /images
// endpoint above only returns the resolved filename list; this is what
// actually fetches one. isRealChapterImage() re-validates the filename
// against a fresh directory scan (not just its regex shape) before
// touching the filesystem, so a request can't be crafted to read
// anything other than a real, already-enumerated chapter image.
router.get('/books/:bookId/images/:fileName', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const { fileName } = req.params;
  if (!isRealChapterImage(bookPath, fileName)) {
    return res.status(404).json({ error: `Unknown chapter image "${fileName}"` });
  }
  res.sendFile(path.join(bookPath, fileName));
});

// Range support (seeking) comes for free from Express's res.sendFile,
// which handles Range/If-Range headers and 206 Partial Content itself -
// this single endpoint is what replaces the Android app's entire
// "fake seek"/virtual-byte-offset workaround, which only existed because
// of SAF+WebView limitations that don't apply to a real file server.
router.get('/books/:bookId/chapters/:chapterBase/audio', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  res.sendFile(path.join(bookPath, `${base}.mp3`), (err) => {
    if (err && !res.headersSent) {
      res.status(404).json({ error: `Could not serve audio for "${base}"` });
    }
  });
});

// JSON companion to /cover below - matches the shape MainActivity.kt's
// onChapterAudioReady() already builds from the same ID3 tags
// (title/artist/album + whether a cover exists), which index.html's
// applyMetadata() expects from window.onAudioPrepareReady's metadataJson.
router.get('/books/:bookId/chapters/:chapterBase/metadata', async (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  const mp3Path = path.join(bookPath, `${base}.mp3`);
  try {
    const metadata = await parseFile(mp3Path);
    res.json({
      title: metadata.common.title || '',
      artist: metadata.common.artist || '',
      album: metadata.common.album || '',
      hasCover: (metadata.common.picture?.length || 0) > 0,
    });
  } catch (err) {
    res.status(500).json({ error: `Could not read metadata: ${err.message}` });
  }
});

router.get('/books/:bookId/chapters/:chapterBase/cover', async (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const base = requireChapter(req, res, bookPath);
  if (!base) return;
  await sendCoverArt(path.join(bookPath, `${base}.mp3`), res);
});

// Book-level cover for the home screen's pill grid - the first chapter's
// embedded cover, same source as the mockup used, just resolved
// server-side now instead of the client picking a chapter itself.
router.get('/books/:bookId/cover', async (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const firstBase = listChapters(bookPath)[0];
  if (!firstBase) return res.status(404).json({ error: 'No chapters in this book' });
  await sendCoverArt(path.join(bookPath, `${firstBase}.mp3`), res);
});
