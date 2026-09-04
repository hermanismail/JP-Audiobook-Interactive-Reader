import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { config } from './config.js';
import { router as booksRouter } from './routes/books.js';
import { router as bookmarksRouter } from './routes/bookmarks.js';
import { attachSyncServer, debugSnapshot } from './sync.js';

const serverRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const app = express();
app.use(express.static(path.join(serverRoot, 'public')));

app.get('/health', (req, res) => {
  res.json({ status: 'ok', libraryCount: config.libraryPaths.length });
});

// TEMPORARY - see sync.js's debugSnapshot() comment. Remove together.
app.get('/api/debug/sync', (req, res) => {
  res.json(debugSnapshot());
});

app.use('/api', booksRouter);
app.use('/api', bookmarksRouter);

const server = app.listen(config.port, () => {
  console.log(`jp-audiobook-server listening on http://localhost:${config.port}`);
});
attachSyncServer(server);
