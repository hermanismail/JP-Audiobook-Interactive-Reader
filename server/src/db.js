import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const serverRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// node:sqlite (built into Node 22.5+/24) - no native compilation needed,
// unlike better-sqlite3 (see Phase 0 notes for why that swap happened).
export const db = new DatabaseSync(path.join(serverRoot, 'data.sqlite'));

db.exec(`
  CREATE TABLE IF NOT EXISTS bookmarks (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    chapter_base TEXT NOT NULL,
    position_seconds REAL NOT NULL,
    label TEXT NOT NULL,
    created_at INTEGER NOT NULL
  );

  -- One row per (book, chapter) - every chapter remembers its own last-
  -- played position independently, not just the single most-recently-
  -- played chapter in the whole book. The "Continue" pill's book-level
  -- position is derived from this table too (MAX(updated_at) per book),
  -- rather than needing a separate book-level row.
  CREATE TABLE IF NOT EXISTS chapter_progress (
    book_id TEXT NOT NULL,
    chapter_base TEXT NOT NULL,
    position_seconds REAL NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (book_id, chapter_base)
  );
`);

// One-time migration off the old single-row-per-book last_position table
// (each book could only ever remember its single most-recently-played
// chapter) - carry over whatever's there, then drop it. No-op on a fresh
// install where last_position was never created.
const oldLastPositionTable = db
  .prepare(`SELECT name FROM sqlite_master WHERE type='table' AND name='last_position'`)
  .get();
if (oldLastPositionTable) {
  db.exec(`
    INSERT OR IGNORE INTO chapter_progress (book_id, chapter_base, position_seconds, updated_at)
    SELECT book_id, chapter_base, position_seconds, updated_at FROM last_position;
    DROP TABLE last_position;
  `);
}
