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
  - `401849c` — real chapter-number-based progress counter + persisted
    resume position + named/dated bookmarks
  - `9da716b`/`de0afc0`/`9c8fc26`/`971ff88`/`ef05573` — README rewrite,
    copyright/content disclaimer, and the app icon's history (added, then
    purged from git history entirely and gitignored - personal photo not
    yet cleared for public redistribution, see the "Local-only app icon"
    section near the end of this file)
  - Branch `preset-text-animation` (not yet merged to `main`) — visible
    library/bookmark/text-preset icon buttons (replicating the Windows
    sibling app's layout, see below), a second text-reveal preset (fade
    instead of color-sweep), and a new orientation-triggered "Zen mode"
    reading layout with a per-chapter side image - see the Structure
    section below for how each piece works
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
  - **`preset-text-animation` branch** (ported from the Windows sibling
    app's `text-animation-preset` branch, per `androidportspec.md`):
    - Visible icon buttons — `#readerTopBar` (library + bookmark, top-left)
      and `#presetToggleBtn` (あ glyph, top-right) — replicate the Windows
      app's overlay row exactly (same 36px circular `.iconBtn`, same
      `top:16px`/`left:16px`/`right:16px` positions), as a *second*, visible
      entry point alongside the existing gestures (triple-tap/swipe-up),
      which still work unchanged. They're DOM siblings of `#frame`, not
      descendants — `#frame`'s gesture listeners classify taps/swipes by
      coordinate math with no `stopPropagation()` anywhere in this file, so
      a button nested inside it would have its clicks misread as gestures.
      `#frame`'s padding is `64px 26px 26px` normally (dropping to zen
      mode's own, unrelated padding scheme — see below — once the icons
      are hidden) specifically to clear these icons — the JS constants
      `PAD_X`/`PAD_TOP`/`PAD_BOTTOM` in `getAvailableSpace()` must stay
      numerically in sync with the CSS, since that function (not just the
      CSS) is what actually guarantees text can't render underneath the
      icons.
    - Text is Yu Mincho (`"Yu Mincho","YuMincho","游明朝","Hiragino Mincho
      ProN","MS Mincho",serif` — same fallback stack as the Windows app,
      set on both `#pageText` and `#measure` so the font-fit math measures
      against what actually renders) on `#d6d6d6` light grey — both presets
      share this same base/unread color now, matching Windows exactly.
    - Text preset A (color sweep, pre-existing) vs B (fade reveal, new) —
      `textPreset` is a global (not per-book) setting via
      `Android.getTextPreset()`/`setTextPreset()`. `applyInitialSpanState()`
      and `updateChunkHighlight()` both branch on it; toggling
      (`#presetToggleBtn`) re-applies to the *currently shown* chunk
      immediately via the same two functions, without rebuilding spans via
      `showPage()`. **Watch for this bug class if you touch either
      preset's code again**: switching presets rewrites `.style.color`
      *and* `.style.opacity` per span — clearing only one of the two when
      switching back leaves stale styling from whichever preset was active
      before (this bit us once already: A→B→A left B's grey color stuck on
      not-yet-lit spans until `applyInitialSpanState()`'s A branch was
      fixed to clear color for every span, not just the lit ones).
    - **Zen mode** — distraction-free layout (only vertical text + a
      per-chapter side image), entered by *physically rotating the phone to
      landscape* (`zenMql = matchMedia('(orientation: landscape)')`), not a
      manual toggle — the Activity has no `android:screenOrientation` lock,
      so it's already free to rotate, and the OS's own rotation pipeline
      already refuses to rotate at all when the user has rotation-lock on —
      so "never trigger zen mode when locked" is automatic, with zero raw
      `SensorManager` code. `applyZenState()` toggles a `.zen` class on
      `#readerScreen`; CSS hides the icon row/progress bar/meta row and
      switches `#frame` to `justify-content:flex-end` (right-anchored, not
      centered — leftover width collects on the left, the natural side for
      right-to-left vertical Japanese text). Zen's padding, revised once
      more after on-device testing showed content flush against the true
      screen edges once the status/nav bars also hide (see immersive-mode
      note below) felt too tight: `#frame { padding:1vh 2vw 1vh 1vw;
      gap:2vw; }` — 1% of screen *height* top+bottom, 2% of screen
      *width* for the image's own buffer from the true right screen edge,
      1% of screen width for the text block's buffer from the true left
      screen edge (unchanged from the previous pass), and a 2%-of-width
      gap between text and image (up from 1%). All four numbers are kept
      numerically in sync with `ZEN_TOP_BOTTOM_FRACTION`/
      `ZEN_RIGHT_FRACTION`/`ZEN_LEFT_FRACTION`/`ZEN_GAP_FRACTION` in the
      script. This is the second revision of this scheme — an even more
      aggressive zero-padding-except-1%-left version came first, then
      got walked back once hiding the system bars made that feel too
      tight; a `2vh`/`26px`/`3vw` scheme came before that, which wasted
      too much of a tall/narrow 20:9 screen. `getAvailableSpace()` sizes
      the side image to the row height *after* subtracting the top+bottom
      padding (no more 85% rule), then gives the text whatever's left
      after the image + the gap + the right buffer. Feather/vignette is a
      `mask-image`/`-webkit-mask-image` with two independent linear
      gradients (one per axis, `intersect`/`source-in` composited) for a
      rectangular fade with sharp corners, not an oval vignette.
      Status/nav bars hide on entering zen mode and reappear on leaving it
      or returning to the library — `applyZenState()` calls a new bridge
      method, `Android.setImmersiveMode(enabled)`
      (`MainActivity.kt`'s `LibraryBridge`), which drives the existing
      `insetsController` (promoted from an `onCreate`-local `val` to a
      class property so this method can reach it) via
      `WindowInsetsControllerCompat.hide/show(WindowInsetsCompat.Type.systemBars())`,
      with `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE` so a swipe-in still
      reveals them temporarily rather than permanently exiting immersive
      mode. `goToLibrary()` also calls it with `false` unconditionally, so
      leaving the reader screen can't strand the bars hidden.
      Per-chapter image resolution (`chapter_<N>_img_<index>.(png|jpe?g)`
      files living alongside the chapter audio in the SAF folder — PNG
      wins ties, walks backward to the nearest chapter with any images,
      rotates through a chapter's own image set across its playback time,
      falls back to the existing ID3 cover art if nothing's found from
      chapter 1 up to the current one) is native
      (`resolveChapterImages`/`/internal-chapter-image/` in
      `MainActivity.kt`, modeled on the existing chapter-file-listing and
      `/internal-cover/` patterns) — nothing here needed a new Android
      permission (no `INTERNET`, no sensors), it's pure local SAF file
      access plus riding the OS's existing rotation behavior.

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
8. **`preset-text-animation` branch** (new, built 2026-08-28/29 on that
   branch, not yet merged to `main` — functionally verified in-browser
   with a mocked bridge, including the orientation trigger by resizing an
   actual desktop browser window across the aspect-ratio threshold, and
   passes a full `:app:assembleDebug`, but never run on a device):
   - Library/bookmark/preset-toggle icon buttons show up, don't overlap
     the vertical text (check especially with a very short chunk, where
     the text column is short enough that the top-padding buffer matters
     visually), and each does the same thing its existing gesture does.
   - Toggling the あ icon switches between color-sweep and fade-reveal
     immediately, persists across a full app restart (global setting, not
     per-book), and doesn't leave stale styling behind after a few
     back-and-forth toggles mid-chunk.
   - **Rotate to landscape with rotation-lock off** → zen mode engages:
     chrome hides, layout is right-anchored with the image inset 1%
     (height) top/bottom and 2% (width) from the true right screen edge,
     text inset 1% (width) from the true left edge, a 2%-width gap
     between them, and rectangular feather looking right, gestures
     (tap/edge-swipe/
     swipe-up-bookmark) still work with `#frame`'s touchable area now
     mostly empty space left of the packed text+image. **Rotate with
     rotation-lock on** → zen mode must never engage — this is the one
     piece of reasoning (relying on the OS's own rotation pipeline rather
     than a raw sensor) that's architecturally sound but has not been
     confirmed against real OEM WebView behavior on an actual device.
   - Also check the status/nav bars actually hide on entering zen and
     reappear on exiting it or triple-tapping back to the library — new,
     built 2026-08-31, only compile-verified so far.
   - A real folder with `chapter_<N>_img_<index>` files across more than
     one chapter, to see the backward-search (chapters with no images of
     their own falling back to an earlier chapter's last image, static)
     and same-chapter rotation-across-playback-time behavior on real
     content — this session's testing could only verify the resolution
     *logic* with a mocked bridge, not real image bytes rendering.
   - Known, accepted limitation carried over from the porting spec: an
     extremely long chunk in zen mode could in principle still push text
     past the left screen edge (no hard font-size floor) — not fixed in
     this pass, matching the spec's own "not necessarily fixing in v1" note.

## Known gaps

- Chapter audio is served from a private cache copy, not re-listed from
  the SAF folder per request (this superseded the original
  Range-streaming-from-SAF design before Phase 4 was ever committed) —
  fine at one-book scale, worth revisiting if it ever feels slow.

## Local-only app icon (not in git, don't try to "fix" this)

`AndroidManifest.xml` on this machine has `android:icon`/`android:roundIcon`
pointing at `@mipmap/ic_launcher`, and `icon.jpg` + the `mipmap-*/
ic_launcher.png` files exist on disk — but none of that is tracked. The
icon is a personal photo not cleared for public redistribution (purged
from git history entirely earlier), the image files are `.gitignore`d,
and the manifest is marked `git update-index --skip-worktree` so this
local edit can never show up in `git status` or get picked up by a
commit. `git log`/`git diff` on the manifest will look clean even though
the working copy differs from what's committed — that's expected, not a
bug. If the manifest ever needs a *real* shared edit (a new permission,
etc.), run `git update-index --no-skip-worktree
app/src/main/AndroidManifest.xml` first, make the edit, commit, then
re-apply the icon lines and re-mark it skip-worktree — otherwise the
edit will silently never be tracked.

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
