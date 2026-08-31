# Porting spec: text presets + Zen mode (Windows → Android)

Source of truth: `hermanismail/JP-Audiobook-Reader-for-Windows`, branch
`text-animation-preset` (commit `795c932`). File/line references below
point there. This spec describes *behavior*, not code, so it should
translate directly regardless of how the Android app structures its own
reader view.

---

## 1. Text animation presets

Two presets for how chunk text reveals itself as it's read. Toggle is a
single icon; state is a global app setting (not per-book), restored on
launch.

### Shared look (both presets)

- **Font**: Yu Mincho (游明朝). Windows CSS stack, for reference:
  `"Yu Mincho","YuMincho","游明朝","Hiragino Mincho ProN","MS Mincho",serif`
  → on Android, use whatever the platform's actual Yu Mincho / Mincho
  fallback chain is (`Typeface` lookup by name, falling back to a serif
  default if unavailable).
- **Not-yet-read character color**: light grey, `#d6d6d6`.
- The first **2 characters** of every chunk are pre-lit the instant the
  page appears (not waiting for playback to reach them) — matches the
  narration's natural lead-in beat. Constant: `PRELIT_COUNT = 2`.
- Highlight/reveal progress is rescaled so it completes at **95%** of the
  chunk's own duration, not 100% (`COMPLETE_AT_FRACTION = 0.95`) — chunk
  audio tends to actually finish a beat before its timestamped end, so
  waiting for true 100% left the last couple of characters visibly
  lagging.

### Preset A — Color sweep (default)

- Already-read characters recolor to a warm salmon, `#F6CAC0`
  (`HIGHLIGHT_COLOR`). Unread characters stay the shared light grey.
- Progress is **discrete per character** (not a gradient): as playback
  crosses each character's position, that character's color flips
  instantly from grey to `#F6CAC0`.
- Formula (index.html:983): given `remaining = totalChars - 2`, and
  `adjustedFrac = min(1, (t - chunkStart)/(chunkEnd - chunkStart) / 0.95)`,
  the lit count is `2 + floor(adjustedFrac * remaining)`.

### Preset B — Fade reveal

- Color never changes (always the shared grey) — only **opacity**
  changes, 0 → 1, per character, as it's read.
- Progress is **continuous**, not discrete: each character's own opacity
  ramps smoothly rather than snapping on. Formula: with the same
  `remaining`/`adjustedFrac` as above, `continuous = adjustedFrac *
  remaining`; character `i` (0-indexed among the non-prelit chars) gets
  `opacity = clamp(continuous - i, 0, 1)`. E.g. `continuous = 3.4` means
  characters 0–2 are fully revealed (opacity 1), character 3 is 40% faded
  in, everything after is still opacity 0.
- The 2 pre-lit characters are opacity 1 immediately, same as color sweep
  lights them immediately.

### Toggle icon

- あ (hiragana "a") inside a circular icon button, same size/style as the
  existing library/bookmark icon buttons, top-right of the reader screen.
- Tap toggles preset A ↔ B immediately, re-rendering the current chunk
  under the new preset without waiting for the next chunk.
- Active-state visual cue: when fade reveal (B) is engaged, the icon
  itself gets an accent border/glyph color, `#e08a3c` (a subtle "you're in
  fade mode" indicator — no change to the reading area itself beyond what's
  described above).
- Persistence: a single global setting (e.g. one SharedPreferences key),
  read once at launch, written on every toggle. Not scoped per book.

---

## 2. Zen mode (new concept for Android — no existing equivalent)

A distraction-free reading layout: real fullscreen, everything hidden
except the vertical text and a per-chapter side image.

### Trigger (needs an Android-native equivalent — there's no keyboard)

On Windows this is bound to the `Enter` key (previously `F11`), toggling
on/off, with `Esc` also exiting it (and returning to the library, unlike
a plain toggle-off). **Android has no keyboard for this** — pick a
touch-native trigger for entering/exiting instead (e.g. a dedicated icon,
a long-press on the text area, or a swipe gesture) since the existing
Android gesture vocabulary (triple-tap, swipe-up — see the main README)
already occupies several obvious candidates. This is a UX decision for
the Android side, not something to copy 1:1.

### What zen mode hides

Everything except the vertical text block and the side image: top icon
row (library/bookmark/text-style), the whole-chapter progress bar +
elapsed/total time, and the bottom metadata row (cover thumbnail, title,
author, speed pill, volume). Play/pause, next/prev chunk, and bookmark
actions all keep working while zen mode is active — only the chrome is
hidden, not the functionality.

### Layout — right-anchored, not centered

This is the part most likely to be fiddly to port correctly, so the
exact geometry:

- The side image and the text block sit **together**, anchored to the
  screen's right edge, with a buffer so neither touches the true edge.
- **Right-edge buffer**: 3% of screen width, between the image's right
  edge and the screen's right edge.
- **Gap between text and image**: 3% of screen width, between the text
  block's right edge and the image's left edge.
- Left-to-right order: `[empty space] [text block] [gap] [image]
  [buffer] [screen edge]`.
- Both percentages were originally 10% (buffer) and 5% (gap), then both
  trimmed to 3% after long chunks were overflowing past the *left* screen
  edge on real content — worth keeping an eye on for Android too if chunk
  text runs long, since this is ultimately a soft mitigation, not a hard
  overflow guarantee (see "Known limitation" below).
- **Why right-anchored at all**: Japanese vertical text reads
  right-to-left. Centering the [image, text] pair made a square/portrait
  image look lopsided (only one side had breathing room). Anchoring the
  whole cluster to the right means any leftover width collects on the
  *left* side of the screen instead — which reads naturally for
  right-to-left content.
- **Why the image (not the text block) is the anchor**: the text block's
  width changes on every single chunk (different chunk text wraps into a
  different number of vertical columns at a given font size). If the
  image were positioned relative to the text block, it would visibly
  shift position on every page turn. Instead, the image is anchored
  directly to the fixed screen-relative position (buffer from the edge),
  and the *text* trails to the left of it, absorbing all the per-chunk
  width changes itself. The image holds still; the text is what moves.
- **Vertical alignment**: image and text block are vertically centered as
  a pair, with the text block's top/bottom edges aligned to the image's
  own top/bottom edges (both scaled to the same height — see below).

### Image scaling — 85% height rule

- Whatever the source image's native resolution, it is always scaled
  (up or down) so its rendered height is exactly **85%** of the
  available row height. This applies regardless of whether the source is
  a large photo or a small embedded album-art thumbnail — a tiny cover
  image is scaled *up* to fill the same visual proportion a full photo
  would, accepting quality loss rather than rendering at native (tiny)
  size.
- The text block's own height is synced to match the image's rendered
  height exactly, so their top/bottom edges align.

### Feather / vignette effect

- All four edges of the image fade softly into the dark background — a
  **rectangular** feather (straight edges fading independently), not an
  oval/radial vignette. Corners stay sharp corners, just faded like the
  edges.
- Fades over the outer **30%** of the image on each axis (i.e. the
  gradient is: transparent at the very edge → fully opaque from 30%
  to 70% of the way in → transparent again at the far edge, per axis,
  combined by intersection so both axes fade independently rather than
  producing an oval).

### Side image resolution (which image shows for a given chapter)

Images are optional per-chapter files living in the same folder as the
chapter audio, named `chapter_<N>_img_<index>.(png|jpg|jpeg)` — e.g.
`chapter_003_img_001.jpg`, `chapter_003_img_002.png`. Case-insensitive
extension matching.

Resolution algorithm, run once when a chapter is opened:

1. Scan the book folder for all filenames matching
   `chapter_(\d+)_img_(\d+)\.(png|jpe?g)`, grouped by chapter number,
   sub-grouped by image index.
2. **PNG wins over JPG/JPEG** for the same chapter+index if both exist.
3. Starting at the *current* chapter number and walking backward toward
   chapter 1, find the nearest chapter number (≤ current) that has *any*
   images at all. Call it the source chapter.
   - If no chapter from 1 up to the current one has any images:
     fall back to the current chapter's own embedded ID3 cover art. (No
     side image scan needed further back than the very first chapter.)
4. If the source chapter **is** the current chapter: use its *entire*
   sorted image set, rotating through all of them across this chapter's
   own playback (see rotation below).
5. If the source chapter is an **earlier** chapter (current chapter has
   no images of its own): use only that source chapter's *last*
   (highest-index) image, statically — no rotation, since that image set
   belongs to a different chapter's own timeline.
   - Example: chapters 1–2 have images, chapter 2's images are
     `chapter_002_img_001.jpg`, `chapter_002_img_002.jpg`. Chapters 3, 4,
     5 have no images of their own → all three show the static
     `chapter_002_img_002.jpg` (last image of chapter 2). If chapter 6
     has its own `chapter_006_img_*` files, chapter 6 switches to its own
     rotating set the moment it starts playing.

### Rotation across a chapter's own playback

When a chapter has N of its own images, they switch evenly across that
chapter's total duration:

- `segment = floor(min(0.999999, currentTime / chapterDuration) * N)`,
  clamped to `[0, N-1]`.
- N=2: image 1 for the first half, image 2 for the second half (switch
  at 50%).
- N=3: switches at 33%/67% (each third gets one image).
- General case: N images divide the chapter into N equal-duration
  segments.
- Re-evaluated on every playback-time tick, but the actual `<img>`
  source is only reassigned when the computed target actually changes
  (avoid redundant reloads within the same segment).

### Known limitation (flag for Android too)

The 3%/3% trim reduces overflow risk for long chunks but isn't a hard
guarantee — an extremely long chunk (many vertical columns even at the
smallest allowed font size) can still in principle push past the left
screen edge, since there's currently no hard cap forcing text to shrink
below its font-size floor to fit available width. Worth the same
consideration on Android if chunk lengths can vary a lot.

---

## 3. Out of scope for this port

- The `Enter`/`F11` keyboard binding itself and the focus/blur bug fix
  around it are desktop-input-model-specific (keyboard shortcuts +
  focusable buttons) and don't apply to Android's touch model — no
  equivalent needed there.
- Real OS-level fullscreen (`BrowserWindow.setFullScreen`) — Android's
  equivalent is whatever fullscreen/immersive-mode API the app already
  uses elsewhere, if any.
