import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const serverRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const configPath = path.join(serverRoot, 'config.json');

function loadConfig() {
  if (!existsSync(configPath)) {
    throw new Error(
      `Missing server/config.json - copy server/config.example.json to ` +
      `server/config.json and point "libraryPaths" at your book folder(s).`
    );
  }
  const raw = JSON.parse(readFileSync(configPath, 'utf8'));
  if (!Array.isArray(raw.libraryPaths) || raw.libraryPaths.length === 0) {
    throw new Error('server/config.json must have a non-empty "libraryPaths" array.');
  }
  return {
    port: raw.port || 3939,
    libraryPaths: raw.libraryPaths,
  };
}

export const config = loadConfig();
