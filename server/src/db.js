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

  CREATE TABLE IF NOT EXISTS last_position (
    book_id TEXT PRIMARY KEY,
    chapter_base TEXT NOT NULL,
    position_seconds REAL NOT NULL,
    updated_at INTEGER NOT NULL
  );
`);
