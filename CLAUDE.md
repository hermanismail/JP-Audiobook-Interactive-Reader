# CLAUDE.md — JP Audiobook Player (Android)

Context handoff for Claude Code, continuing work started in Claude Desktop
(Chat/Cowork). Read this before touching anything.

## Handoff snapshot

- **As of:** August 27, 2026
- **Git status:** initialized. Branch `main`, remote `origin` →
  https://github.com/hermanismail/JP-Audiobook-Interactive-Reader.git,
  `.gitignore` excludes `.gradle/`, `.idea/`, `.kotlin/`, `app/build/`, and
  `local.properties` (machine-specific SDK path). Commits so far:
  - `c1e9cd1` — initial Phase 4 Android player shell (uncompiled at the time)
  - `472e5ba` — full reader-screen redesign: gesture controls (tap to
    play/pause, triple-tap to library, edge-swipe for prev/next chunk),
    whole-chapter progress bar with drag-to-seek, speed-control overlay,
    cover art/author/title read from the chapters' own ID3 tags
  - `56bfc0f` — dark status/nav bar, autoplay on chapter open + automatic
    continuous playback into the next chapter, character-by-character
    "karaoke" text highlighting during playback
  - `126a9fe` — lock-screen/notification media controls (`PlaybackService`)
  - `f17fca0` — app icon (from the user's own photo) + label ("SHAMA")
  - `add7e0c` — README rewrite for the completed first version
  - `c07cd23` — bottom-bar rework: author on top / book title on bottom
    (each row sizes independently against its own pill instead of sharing
    one column across both rows)
  - (pending) — real chapter-number-based progress counter + persisted
    resume position + named/dated bookmarks, see below
- Treat "Current status" and "Priority testing checklist" below as the
  source of truth for what actually works, independent of what git tracks
  — update both as things get confirmed or change.

## What this project is

An Android app that plays the audiobooks produced by the separate
**JP Audiobook Generator** pipeline (`C:\JP-Audiobook-Generator`, a Windows
desktop tool — different repo, not part of this build). This app is the
"player" half: it reads the generator's output folder (chaptered MP3s +
`sync.json` / `book.json`) and plays them back with a vertical-text,
page-by-page Japanese reading UI.

This repo is standalone. There is no dependency between this Android
project and the generator's Python code at build time — they only share a
file format (the SAF-picked output folder's contents).

## Current status: Phase 4, built and iterating on a real device

The original Phase 4 shell was written blind (no Android SDK/Gradle/Kotlin
compiler available at the time) but has since been opened in Android
Studio, built, and run on a real phone. The reader screen has since gone
through a full gesture-driven redesign (see commit `472e5ba` and its
mockup, `JP-Audiobook-Interactive-Reader-Mockup.png` /
`_explanation.png`), plus several rounds of on-device bug reports and
fixes from the developer (a vertical-text wrapping regression, karaoke
highlight timing tuned twice). Treat what's described below as confirmed
working via direct on-device testing, not just "written."

## Structure

- `app/src/main/java/.../MainActivity.kt` — single Activity hosting a
  `WebView`, dark status/nav bar forced to match the UI. Handles:
  - SAF folder picker (`ActivityResultContracts.OpenDocumentTree`), with
    persisted permission so the folder doesn't need re-picking every launch
  - `window.Android` JS bridge: `pickFolder`, `listChapters`, `readTextFile`
    (for `sync.json` / `book.json` and other small text files),
    `prepareChapterAudio` (async, reports progress/ready/failed back to JS)
  - Chapter audio is copied into app-private cache storage before playing
    (not streamed live from the SAF folder) and served from there through
    `androidx.webkit.WebViewAssetLoader` — an earlier hand-rolled HTTP
    Range approach against the live SAF stream hit
    `PIPELINE_ERROR_READ` in Chromium's media pipeline and was abandoned;
    see the doc comment on `MainActivity` for the full history. Only the
    most recently opened chapter's copy is kept.
  - Next/prev/seek is a "fake seek": since repositioning within an
    already-loaded `<audio>` resource proved unreliable on-device
    regardless of mechanism, a jump instead loads a fresh virtual resource
    (`/internal-audio-offset/<file>/<time>`) that starts partway into the
    cached file's bytes and presents itself as time-0. `chapterTimeOffset`
    in the JS tracks what real chapter time that corresponds to.
  - `/internal-cover/<file>` virtual endpoint serves the chapter's embedded
    ID3 cover image, decoded by a hand-rolled ID3v2.2/2.3/2.4 frame parser
    (`parseId3Tag`) that also reads `TIT2`/`TPE1`/`TALB` for chapter
    title/author/book title — there is no separate cover-art file; it's
    read straight out of each chapter MP3's tag, same as the audiobook
    generator embeds it.
  - Binds `PlaybackService` (see below) in `onCreate`; when a chapter's
    audio finishes preparing, decodes its cover to a downsampled `Bitmap`
    (≤512px — the raw ~1200px covers risk `TransactionTooLargeException`
    crossing the Binder IPC boundary to system UI) and pushes
    title/artist/album/cover to the service natively, before the JS side
    even knows the chapter is ready.
  - Resume position + bookmarks are persisted as flat, folder-URI-suffixed
    SharedPreferences keys (`last_position:<treeUri>`,
    `bookmarks:<treeUri>`) in the same prefs file as `KEY_TREE_URI` — this
    scopes them per-book so switching folders via "Change folder" can't
    leak one book's bookmarks into another. `reportPlaybackState` now
    takes a `chapterBase` param and persists the position on every call
    (already throttled to ~1/sec by the JS side, so no extra native
    throttling); `saveBookmark`/`listBookmarksAndLastPosition`/
    `deleteBookmark` round out the bridge. All hand-rolled
    `JSONObject`/`JSONArray` building, matching `listChaptersJson()` — no
    serialization library in this project.
- `app/src/main/java/.../PlaybackService.kt` — foreground service holding
  the `MediaSessionCompat` behind the lock-screen/notification media
  control. Owns no playback state itself; mirrors whatever the WebView's
  `<audio>` element is doing. Two directions of traffic:
  - MainActivity → service: `updateNowPlaying` (title/artist/cover, called
    natively) and `updatePlaybackState` (play/pause/position/speed, relayed
    from a new JS→Kotlin bridge call, `Android.reportPlaybackState`, fired
    on `play`/`pause`/speed-change and throttled to ~1/sec on `timeupdate`)
  - service → MainActivity → WebView: transport actions (notification
    button taps, but also Bluetooth headset buttons / Android
    Auto / Assistant via `MediaSessionCompat.Callback`) call
    `window.mediaPlay/mediaPause/mediaNext/mediaPrevious/mediaSeekTo`,
    which the JS side already had equivalents of internally
  - Bound (for that two-way channel) *and* independently started once a
    chapter is ready, so both the service and the WebView's still-playing
    audio survive the Activity backgrounding or being destroyed. Triple-tap
    back to the library calls `Android.stopPlaybackSession()`, which tears
    the whole session down rather than just pausing it.
  - Needs `POST_NOTIFICATIONS` (requested at launch, API 33+) and the
    `FOREGROUND_SERVICE_MEDIA_PLAYBACK` permission (manifest-declared, no
    runtime prompt) to actually show anything — the service runs fine
    without either, it just stays invisible.
  - **Known platform ceiling, not a bug**: on Android 13+ the system
    renders its own themed media-player chrome from the session's
    metadata/actions and ignores custom notification layouts entirely —
    the exact rounded-corner/orange-accent design from the proposed mockup
    (`_lockscreen mockup, 2026-08-26`) isn't achievable as literal pixels
    on modern Android. What *is* controllable: which cover art, title,
    author, actions, and live position get handed to the system.
- `app/src/main/assets/web/index.html` — the reader UI:
  - Vertical-text paging with fit-to-page font sizing and
    blank-during-silence, same as the original Phase 3 mockup
  - Gesture-driven: tap the text area to play/pause, triple-tap to return
    to the library, swipe from the left edge to advance a chunk / from the
    right edge to go back
  - Whole-chapter progress bar with a drag-to-seek marker, elapsed/total
    time, and a speed-control overlay (0.25x–8.00x, presets, persists
    across seeks)
  - Chapters autoplay on open and automatically continue into the next
    chapter when one finishes (`audio`'s `ended` event)
  - Text recolors character-by-character as each chunk plays (see
    `updateChunkHighlight`): the first two characters are lit immediately,
    the rest sweep across the remaining characters and finish at 95% of
    the chunk's duration rather than 100%, since audio for a chunk tends
    to actually finish a beat before its own end timestamp
  - **Known browser quirk worth remembering**: splitting chunk text into
    one `<span>` per character (needed for the highlight) silently drops
    the "break almost anywhere" CJK wrapping behavior a plain text node
    gets for free, *and* Chromium can cache the wrapped-column width from
    before the spans went in and never recompute it — both are worked
    around in `showPage()` (`overflow-wrap: anywhere` plus a `display`
    toggle to force real re-layout). If vertical text ever collapses into
    one overflowing column again, start there.
  - The chapter/progress pill (`updateChapterPill`) shows the real chapter
    number parsed from the filename over the highest chapter number
    present in the folder (`chapterNumber()`/`allChapters.reduce(...)`),
    not folder-relative position — chapters get copied to the phone in
    batches and old ones deleted after reading, so the folder is rarely a
    contiguous run.
  - Swipe up on the text area (anywhere, not edge-gated;
    `VSWIPE_MIN_DY = 64`) bookmarks the current chapter+time via
    `Android.saveBookmark`, with a brief fading confirmation
    (`#bookmarkToast`). The library screen (`renderLibrary()`) shows, in
    order: a "Continue" row (if a resume position exists for this folder,
    accent-colored) → the chapter list → "Change folder" → a "Bookmarks"
    section, each row swipe-left-to-reveal a delete button (per-row
    Pointer Events drag, mutual exclusion so only one row is open at a
    time, tap-while-open closes rather than navigates). `openChapter(base,
    resumeSeconds)` takes an optional second param consumed once in
    `onAudioPrepareReady` to seek there instead of starting from 0 — reuses
    the same `seekToTime()` primitive as drag-to-seek/next/prev/lock-screen
    scrubbing.

## Build setup

- AGP 9.3.2, Kotlin's built-in compiler support (no separate Kotlin
  plugin needed) — requires **JDK 17** and an Android Studio release
  supporting AGP 9.x (Otter or later)
- No committed `gradlew` / `gradle-wrapper.jar` as of last handoff —
  Android Studio generates it on first open, or via
  `File → Sync Project with Gradle Files`. If Claude Code needs to build
  from the CLI rather than through Studio, check whether the wrapper has
  been generated yet; if not, flag it rather than assuming `./gradlew` exists.
- **Building from Claude Code's Bash tool without a committed wrapper**:
  confirmed working on 2026-08-26. Android Studio's own Gradle download
  cache already has the right distribution locally once the project's been
  opened there once — find the `gradle` binary under
  `~/.gradle/wrapper/dists/gradle-<version>-bin/*/gradle-<version>/bin/`
  (version must match `gradle/wrapper/gradle-wrapper.properties`) and set
  `JAVA_HOME` to Android Studio's bundled JBR (`.../Android Studio/jbr`)
  before invoking it — no separate JDK install needed. `:app:assembleDebug`
  validates Kotlin, the manifest, and resources (including vector
  drawables) all together; use it to actually verify changes instead of
  just reading the code, the way earlier phases of this project had to.
- Target: Android 8.0 (API 26) and newer

## Priority testing checklist

**Confirmed working on-device** (real phone, real output folder): folder
picker + library listing, chapter open + autoplay, gesture controls (tap,
triple-tap, both edge-swipe directions), drag-to-seek, speed overlay,
cover/author/title from ID3 tags, chapter/chunk progress pill, continuous
autoplay into the next chapter, vertical-text wrapping and the
character-by-character highlight (including the long-chunk wrapping bug
and its fix).

**Still not explicitly confirmed:**

1. **Folder picker persistence across a full restart** — pick the real
   output folder, force-kill the app, relaunch, confirm it remembers the
   folder without re-prompting. (The mechanism — persisted SAF URI
   permission — hasn't changed since Phase 4 and is likely fine, just
   hasn't been re-verified this round.)
2. **Seeking under stress** — repeated far jumps in quick succession,
   including jumping while a previous seek's virtual resource is still
   loading. If seeking misbehaves, start in `serveAudioFromTime()`.
3. **130-char hard-limit chunk** on a real device screen.
4. **A chapter whose ID3 tag has no embedded cover** — confirm the
   placeholder (music-note icon) shows correctly rather than a broken
   image or blank space.
5. **Lock-screen / notification media controls** (new, built
   2026-08-26, `PlaybackService.kt` — passes a full `:app:assembleDebug`,
   never run on a device): the notification/lock-screen widget should
   appear once a chapter opens, show the right cover/title/author, its
   play/pause/prev/next should control the same audio the WebView is
   playing, dragging its seekbar should actually seek, it should survive
   backgrounding the app and the screen locking, and triple-tapping back
   to the library should make it disappear. Also worth checking:
   Android's own notification-permission prompt actually appears on first
   launch (API 33+), and a Bluetooth headset's play/pause button (if one's
   available to test with) reaches the same code path as the notification
   buttons.
6. **Resume position surviving a real process kill** (new, built
   2026-08-27 — functionally verified in-browser with a mocked bridge and
   passes `:app:assembleDebug`, but the actual "survives Android killing
   the app" scenario this was built for can only be checked on a device):
   pick a folder, play into a chapter for a bit, `adb shell am force-stop
   com.misao.jpaudiobookplayer` (or just leave the phone idle long enough
   for the OS to reclaim it), relaunch, confirm the library screen's
   "Continue" row shows the right chapter and time.
7. **Bookmarks** (same build, same caveat): swipe up while reading saves
   one (confirm the toast appears with a sensible date/time label);
   confirm it shows up under "Change folder" after returning to the
   library; swipe a bookmark row left, confirm the delete button appears
   and actually deletes it; confirm tapping a bookmark resumes at the
   exact saved time; confirm a bookmark/last-position pointing at a
   chapter file since deleted from the folder falls through gracefully to
   the existing "could not prepare audio" alert rather than crashing.

## Known gaps

- Chapter audio is served from a private cache copy, not re-listed from
  the SAF folder per request (this superseded the original
  Range-streaming-from-SAF design before Phase 4 was ever committed) —
  fine at one-book scale, worth revisiting if it ever feels slow.

## Working style (carried over from Desktop/Cowork sessions)

- **Spec-first, mockup-before-code, isolate-before-wire**: confirm a
  design/approach before implementation; validate UI standalone before
  wiring to real data; wire backend only after UI is confirmed.
- **Consult before changes** — ask before non-trivial edits, especially
  anything touching build config, the manifest, or the JS bridge contract
  between Kotlin and the WebView.
- **One topic at a time** when asking clarifying questions.
- Update this file when a phase closes out or a testing item above gets
  confirmed, so future sessions (Code or Desktop) start from the same page.

## Related project (separate repo, for context only)

`C:\JP-Audiobook-Generator` — the Python/CustomTkinter desktop tool that
produces this app's input folders. Two-venv architecture (lightweight GUI
venv + separate `C:\Irodori-TTS` heavy ML venv for the TTS engine). Not
part of this Android build; mentioned only so file-format assumptions
(chapter MP3 naming, `sync.json`/`book.json` schema) can be traced back to
their source if something looks off.
