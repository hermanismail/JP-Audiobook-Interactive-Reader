import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { config } from './config.js';
import { router as booksRouter } from './routes/books.js';
import { router as bookmarksRouter } from './routes/bookmarks.js';

const serverRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const app = express();

// TEMPORARY - diagnosing the Chromecast custom receiver not playing audio
// (cast-receiver.html loads fine, but goes blank/silent once LOAD arrives).
// Logs every request this process actually receives, so we can tell
// whether the TV's own audio/receiver fetches ever reach this server at
// all, and with what Range header, vs failing before/after it. Remove
// once cast-to-TV is confirmed working.
app.use((req, res, next) => {
  var startedAt = Date.now();
  console.log(`[${new Date().toISOString()}] --> ${req.method} ${req.originalUrl} Range=${req.headers.range || '(none)'} UA=${req.headers['user-agent'] || '(none)'}`);
  res.on('finish', () => {
    console.log(`[${new Date().toISOString()}] <-- ${req.method} ${req.originalUrl} status=${res.statusCode} content-type=${res.get('Content-Type') || '(none)'} content-range=${res.get('Content-Range') || '(none)'} ${Date.now() - startedAt}ms`);
  });
  next();
});

app.use(express.static(path.join(serverRoot, 'public')));

app.get('/health', (req, res) => {
  res.json({ status: 'ok', libraryCount: config.libraryPaths.length });
});

app.use('/api', booksRouter);
app.use('/api', bookmarksRouter);

app.listen(config.port, () => {
  console.log(`jp-audiobook-server listening on http://localhost:${config.port}`);
});
