import { readdirSync } from 'node:fs';

const chapterImageRegex = /^chapter_(\d+)_img_(\d+)\.(png|jpe?g)$/i;

function scanChapterImages(bookPath) {
  return readdirSync(bookPath)
    .map((name) => {
      const m = chapterImageRegex.exec(name);
      if (!m) return null;
      return {
        chapter: Number(m[1]),
        index: Number(m[2]),
        isPng: m[3].toLowerCase() === 'png',
        fileName: name,
      };
    })
    .filter(Boolean);
}

// Port of MainActivity.kt's resolveChapterImagesJson(): walks backward
// from currentChapter to the nearest chapter (<= current) with any
// images at all. If that source chapter *is* the current chapter,
// returns its whole (PNG-wins-ties, index-sorted) image set, for
// rotation across playback. If it's an earlier chapter, returns only
// that chapter's last (highest-index) image, statically.
export function resolveChapterImages(bookPath, currentChapter) {
  const images = scanChapterImages(bookPath);
  const byChapter = new Map();
  for (const img of images) {
    if (!byChapter.has(img.chapter)) byChapter.set(img.chapter, []);
    byChapter.get(img.chapter).push(img);
  }

  let sourceChapter = null;
  for (let c = currentChapter; c >= 1; c--) {
    if (byChapter.has(c)) {
      sourceChapter = c;
      break;
    }
  }
  if (sourceChapter === null) return [];

  const byIndex = new Map();
  for (const img of byChapter.get(sourceChapter)) {
    const existing = byIndex.get(img.index);
    if (!existing || (img.isPng && !existing.isPng)) byIndex.set(img.index, img);
  }
  const orderedFileNames = [...byIndex.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, img]) => img.fileName);

  return sourceChapter === currentChapter ? orderedFileNames : [orderedFileNames.at(-1)];
}

// Hardening check for the /images/:fileName route: only serves a name
// that both matches the expected shape AND was actually found by scanning
// the folder - never builds a path directly from an unchecked request
// param.
export function isRealChapterImage(bookPath, fileName) {
  if (!chapterImageRegex.test(fileName)) return false;
  return scanChapterImages(bookPath).some((img) => img.fileName === fileName);
}
