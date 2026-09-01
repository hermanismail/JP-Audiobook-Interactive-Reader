import crypto from 'node:crypto';
import express from 'express';
import { db } from '../db.js';
import { resolveChapterBase } from '../library.js';
import { requireBook } from './books.js';

export const router = express.Router();

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

function formatLabel(timestampMs) {
  // Intl formats as "Aug 31, 2026, 3:45 PM" - swap the date/time comma for
  // " at " to match saveBookmarkRecord()'s SimpleDateFormat
  // ("MMM d, yyyy 'at' h:mm a") in MainActivity.kt: "Aug 31, 2026 at 3:45 PM".
  return dateFormatter.format(new Date(timestampMs)).replace(/, (\d+:\d+)/, ' at $1');
}

router.get('/books/:bookId/bookmarks-and-last-position', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const { bookId } = req.params;

  const lastPositionRow = db
    .prepare('SELECT chapter_base, position_seconds, updated_at FROM last_position WHERE book_id = ?')
    .get(bookId);
  const lastPosition = lastPositionRow
    ? {
        chapterBase: lastPositionRow.chapter_base,
        positionSeconds: lastPositionRow.position_seconds,
        updatedAt: lastPositionRow.updated_at,
      }
    : null;

  const bookmarkRows = db
    .prepare('SELECT id, chapter_base, position_seconds, label, created_at FROM bookmarks WHERE book_id = ? ORDER BY created_at ASC')
    .all(bookId);
  const bookmarks = bookmarkRows.map((row) => ({
    id: row.id,
    chapterBase: row.chapter_base,
    positionSeconds: row.position_seconds,
    label: row.label,
    createdAt: row.created_at,
  }));

  res.json({ lastPosition, bookmarks });
});

router.post('/books/:bookId/bookmarks', express.json(), (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const { bookId } = req.params;
  const { chapterBase: requestedBase, positionSeconds } = req.body || {};

  const chapterBase = resolveChapterBase(bookPath, requestedBase);
  if (!chapterBase || typeof positionSeconds !== 'number') {
    return res.status(400).json({ error: 'chapterBase (must be a real chapter) and positionSeconds (number) are required' });
  }

  const now = Date.now();
  const record = {
    id: crypto.randomUUID(),
    chapterBase,
    positionSeconds,
    label: formatLabel(now),
    createdAt: now,
  };
  db.prepare(
    'INSERT INTO bookmarks (id, book_id, chapter_base, position_seconds, label, created_at) VALUES (?, ?, ?, ?, ?, ?)'
  ).run(record.id, bookId, record.chapterBase, record.positionSeconds, record.label, record.createdAt);

  res.json(record);
});

router.delete('/books/:bookId/bookmarks/:id', (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const { bookId, id } = req.params;
  db.prepare('DELETE FROM bookmarks WHERE id = ? AND book_id = ?').run(id, bookId);
  res.json({ ok: true });
});

router.put('/books/:bookId/last-position', express.json(), (req, res) => {
  const bookPath = requireBook(req, res);
  if (!bookPath) return;
  const { bookId } = req.params;
  const { chapterBase: requestedBase, positionSeconds } = req.body || {};

  const chapterBase = resolveChapterBase(bookPath, requestedBase);
  if (!chapterBase || typeof positionSeconds !== 'number') {
    return res.status(400).json({ error: 'chapterBase (must be a real chapter) and positionSeconds (number) are required' });
  }

  db.prepare(
    'INSERT OR REPLACE INTO last_position (book_id, chapter_base, position_seconds, updated_at) VALUES (?, ?, ?, ?)'
  ).run(bookId, chapterBase, positionSeconds, Date.now());

  res.json({ ok: true });
});
