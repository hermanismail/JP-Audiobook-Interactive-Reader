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

## Server + web client (branch `server-web-client`, `server/` folder)

A separate, additive, opt-in feature — not a fork or replacement of the
offline Android app, which keeps working completely unchanged. Serves
the same book folders (chaptered MP3s + `sync.json`/`book.json`) over
HTTP so they can be read from a plain browser instead of only via
Android's SAF. Full design rationale lives in the `server-web-client`
plan; this section is the load-bearing summary.

- **Stack**: Node.js + Express + `music-metadata` (same ID3 library the
  Windows Electron sibling app already depends on) + Node's built-in
  `node:sqlite` for bookmarks/resume-position — chosen over
  `better-sqlite3` specifically because it needs zero native compilation
  (no Visual Studio Build Tools dependency, on this dev machine or any
  eventual deployment machine).
- **API** (`server/src/routes/books.js`, `bookmarks.js`): `/api/books`,
  `.../chapters`, `.../sync`, `.../images`, `.../metadata`, `.../cover`,
  `.../audio` (Range-serving via Express's `res.sendFile` — no
  "prepare"/cache-copy step needed at all, since a real file server
  doesn't have the SAF+WebView limitations the Android app's private
  cache copy and virtual-offset "fake seek" exist to work around), plus
  `.../bookmarks` (GET/POST/DELETE) and `.../last-position` (PUT).
  Every route resolves `bookId`/`chapterBase`/chapter-image filenames
  through an in-memory allowlist built from config at startup — never
  builds a filesystem path directly from a request parameter — since
  this is meant to eventually be reachable from the public internet (see
  `server/README.md`'s Cloudflare Tunnel/Access setup), not just a LAN.
- **Web client** (`server/public/index.html`): a **derived copy** of the
  Android asset's `index.html`, not the same file — reuses the vertical-
  text engine, gestures, karaoke highlight, both text presets, and zen
  mode essentially unmodified, fronted by `server/public/bridge-shim.js`,
  which implements the same 12-method `window.Android` bridge shape
  against `fetch()` calls instead of a `JavascriptInterface`. Future UI
  features need to be ported to both copies by hand — an accepted
  tradeoff, not an oversight (see the plan for why this fork was chosen
  over a shared file with runtime branching).
  - The **only real mechanism-level divergence** (not just sync-vs-async
    call sites): the web copy's `seekToTime()` uses plain
    `audio.currentTime = target` directly, since a real Range-serving
    server seeks correctly on its own — none of the Android app's
    virtual-byte-offset "fake seek" workaround applies here.
    `chapterTimeOffset` stays declared (many `+ chapterTimeOffset`
    expressions read it) but is never reassigned away from 0 in this copy.
  - **Bug found via actual browser testing, not just code review**: zen
    mode's `matchMedia('orientation: landscape')` trigger matches nearly
    any normal desktop browser window (width > height is the common
    case), which would make zen mode auto-engage permanently with no way
    to "rotate back" out of it on desktop. Fixed by also requiring a
    coarse (touch) pointer (`matchMedia('(pointer: coarse)')`) before
    auto-engaging — still triggers correctly on an actual mobile browser
    rotated to landscape, never on desktop. Android-only file is
    unaffected (always a touch device).
  - Bookmarks/resume-position are real (SQLite-backed), single-user,
    global text preset stored in `localStorage` instead of the Android
    bridge's global SharedPreferences setting.
  - **Home screen** (`#homeScreen`/`renderHome()`) is the app's actual
    entry point now, replacing the earlier in-library "Books" section
    from the first multi-book pass: a centered, evenly-gapped (50px) grid
    of 400×400 rounded-square pills, one per configured `libraryPaths`
    entry — 300×300 cover, title (18px), author (16px), both Yu Mincho/
    `#d6d6d6`, current book's pill bordered orange (`#e08a3c`), others
    light grey (`#9a97a0`), current book always sorted first regardless
    of `config.json` order. Clicking a pill calls `Android.selectBook`
    then shows the *existing* per-book library view (`#libraryScreen`,
    Continue/chapters/bookmarks, unchanged) for that book; a new
    "← All books" link there (`allBooksBtn`/`goHome()`) goes back to the
    grid. The reader screen's library icon (`goToLibrary()`) still goes
    straight to the per-book view, not all the way home — matches the
    two-level hierarchy design (home → per-book library → reader).
    `listBooks()`/`selectBook(id)`/`currentBookId()` are shim-only
    methods with no Android equivalent (the native app only ever has one
    SAF folder open at a time). Selection persists across reloads in
    `localStorage` (`selectedBookId`); both `renderHome()` and
    `listChapters()` independently fall back to the first configured book
    if nothing's selected yet or a previously-selected id no longer
    exists. Bookmarks/resume-position are already correctly scoped per
    book (SQLite tables keyed by `book_id`), so switching books doesn't
    leak one book's state into another.
  - **Book-level title/author/cover** (for the home screen's pills, and
    `/api/books`'s `title`/`author` fields generally) are resolved
    server-side in `library.js`'s `listBooks()`: `book.json`'s own
    `title` wins if present, else the first chapter's ID3 **album** tag
    (confirmed via real data that these generator-produced folders carry
    the book title there, not in `book.json`, which usually doesn't
    exist), else the raw folder id as a last resort; author always comes
    from the first chapter's ID3 **artist** tag. "First chapter" is
    whichever chapter is numerically lowest in that folder, not a
    hardcoded `chapter_001` — confirmed necessary since one real test
    folder's lowest chapter is `chapter_007`. `GET /api/books/:bookId/cover`
    serves that same first chapter's embedded cover art, sharing a
    `sendCoverArt()` helper with the existing per-chapter cover route.
    `pickFolder` stays a no-op in the shim only because index.html's
    now-unreachable `hasFolder:false` empty-state branch still references
    it — `pickFolder`/"Change folder" are meaningless server-side (the
    server's config decides which folders exist, not a per-session
    picker), fully superseded by the home screen.
  - **Bug found via real browser testing** (not just code review): pills'
    title/author text rendered as illegible garbage regardless of
    font-size. Root cause wasn't a font issue at all —
    `getBoundingClientRect()` showed the title box rendering at 10px tall
    no matter what font-size was set. The pill's padding/gap math left
    only 24px of vertical room for two lines of text (400px pill − 300px
    cover − 48px padding − 28px gaps), and since both label elements need
    `overflow:hidden` for ellipsis truncation, flexbox's
    `min-height:auto → 0` rule let them get crushed to fit whatever space
    remained, squashing the glyphs into slivers. Fixed by tightening
    padding (24→16px) and gap (14→8px) to free real room, plus
    `flex-shrink:0` on both labels as a safety net so a future mistake
    here fails *visibly* (overflow) rather than *invisibly* (crushed
    garbage). Also fixed in the same pass: the grid's `min-height:100vh`
    was letting flex-wrap's default `align-content` distribute leftover
    vertical space *between* wrapped rows instead of packing them
    together — needs explicit `align-content:flex-start`.
  - **Dark/light theme** — a full CSS-custom-property re-skin (`--bg`,
    `--ink`, `--panel-bg`, `--border`, `--muted`, `--accent`,
    `--read-text-base/-highlight-a/-b`, etc., defined on `:root` and
    overridden under `:root.light`), toggled by a new circular
    `#themeToggleBtn` (moon icon) in the reader's top bar, immediately
    left of the preset toggle — same `.iconBtn`/`currentColor` mechanism,
    so the icon and its border invert for free with no separate
    light/dark asset. Dark is the original palette, unchanged; light is
    `#e5decf` background with black ink, only those two values actually
    specified — everything else (panel backgrounds, borders, muted text)
    is a derived fill-in. Only two colors are genuinely theme-dependent
    for the *reading text* itself: preset A's highlighted color (dark:
    `#F6CAC0` salmon, unchanged; light: black ink) and preset B's single
    fade color (dark: `#d6d6d6`; light: black ink) — both read from CSS
    custom properties into the existing `HIGHLIGHT_COLOR`/
    `FADE_BASE_COLOR` JS constants via `updateThemeColors()`, called on
    load and on toggle. The unread/pre-highlighted color
    (`--read-text-base`) is deliberately close in both themes (still a
    light grey either way) — tuned to `#d0d0d0` in light mode after
    `#d6d6d6` proved too low-contrast against `#e5decf` on review.
    Preference persists in `localStorage` (`theme`), same pattern as
    `textPreset`.
  - **Per-book library screen redesign** (`#libraryScreen`) — replaced
    the old single-column chapter-row list with a two-column layout:
    left = the same cover/title/author pill as the home screen (exact
    400×400 at ≥800px container width, `min(400px, 90vw)` below that),
    not clickable here since this already *is* the selected book; right
    = chapter pills (35px tall, full column width by default — one per
    row) + a Bookmarks section below, same pill styling. The old
    "← All books" text link is now a circular icon pill
    (`#allBooksBtn`, home glyph, 50×50), centered above the two-column
    content instead of pinned to the top-left corner. **Continue** (the
    resume-position pill) is *not* part of the chapter grid at all — it's
    appended directly below the album art pill inside a dedicated
    `#libraryLeftColWrap`, so it lands in the same relative spot (right
    under the cover) whether the layout is side-by-side or, below 800px,
    stacked into one column.
    - **Chapter overflow escalation**, verified against real data (a
      confirmed important reordering, see below): `renderLibrary()`
      first renders chapters as a single flush-left column and measures
      its real height via `getBoundingClientRect()`. If that's ≤400px
      (matching the left column's height), it's left alone. If it
      overflows, it's torn down and rebuilt as two explicit side-by-side
      `.pillWrap` sub-columns (`.twoColRow`, 200px each) — the **left**
      sub-column gets as many chapters, *in order*, as fit in 400px
      (`Math.floor((400+gap)/(pillHeight+gap))`), and the right
      sub-column gets whatever's left, allowed to grow past 400px if
      even that overflows (`#libraryBody`'s `align-items:flex-start`
      keeps the left column pinned at the top rather than centering
      against a taller right one). Below 800px, `.twoColRow` switches to
      `flex-direction:column` (not enough width for 200px+200px
      side-by-side), so both sub-columns just stack full-width instead.
    - **Two ordering/sizing bugs found via real testing, not caught by
      code review**: (1) the first cut just flex-wrapped chapter pills
      at their natural (content-based) width, which already fit 3 short
      "Chapter N" labels per row by default — meaning the "overflow to
      two 200px columns" escalation almost never triggered even at 18+
      chapters, and when forced, actually made things *worse* (3-per-row
      natural packing → 2-per-row at 200px = more rows, not fewer).
      Fixed by making pills full-width-by-default (one per row), the
      only way the escalation ladder means anything at realistic chapter
      counts. (2) With Continue still living inside the chapter grid at
      the time, simple row-major flex-wrap interleaved it with Chapter 1
      on row one and Chapter 2/3 on row two — not the "fill left column
      with 1, 2, 3... first" order asked for; solved by pulling Continue
      out of the chapter-capacity math entirely (see above) rather than
      trying to special-case its position within it.
    - **Bug found via real device testing**: `#allBooksBtn` rendered as
      an oval, not a circle, specifically on a viewport where total page
      content exceeded the viewport height. Same root cause as the home
      pill bug above — it's a flex child of `#libraryScreen`
      (`flex-direction:column`) without `flex-shrink:0`, so flexbox
      shrank its height (down to ~23px against a fixed 50px width) to
      make everything fit, rather than letting `overflow-y:auto` scroll.
      Fixed by adding `flex-shrink:0`; the album art pill and right
      column already had this protection, the button just didn't.
  - **Device-specific zen mode** — the mobile/tablet rotation-triggered
    zen mode and desktop's own zen mode are two fully independent
    systems sharing only the underlying `zenImageWrap`/`zenImage`/
    `getAvailableSpace()` mechanism. Two decoupled classes on
    `#readerScreen`: `.zen` (side-image content layout) and
    `.chrome-hidden` (icon row + progress/info row visibility) — the
    original build conflated these into one (`.zen` alone hid
    everything); they're now independently driven per device class.
    - **Mobile/tablet** (`zenMql` + `zenCoarsePointerMql`, unchanged
      trigger): entering zen sets both `.zen` and `.chrome-hidden`
      together (same immediate-hide behavior as before), but now
      **pausing reveals chrome, playing again hides it** — hooked into
      the existing `audio` `play`/`pause` listeners via
      `updateChromeForPlaybackState()`, independent of `.zen` itself
      staying on throughout. A new manual **`#forceZenBtn`** (only
      shown on coarse pointers, `@media (pointer: coarse)`/`(pointer:
      fine)` CSS — not JS — gate the two device-specific icons apart)
      lets rotation-locked users force the same state regardless of
      actual orientation; tapping again releases the override back to
      whatever the real orientation would naturally produce.
    - **Desktop** (fine pointer): two *fully independent* axes, per the
      user's explicit design — resizing alone controls content layout,
      fullscreen alone controls chrome, and they combine freely (e.g.
      wide+non-fullscreen shows the image with chrome always visible).
      `.zen.desktop` engages purely from `window.innerWidth >= 800`
      (`ZEN_DESKTOP_MIN_WIDTH`), live on resize, with **no chrome-hiding
      side effect**. Originally rendered the pair **centered** rather
      than right-anchored, but reverted after a real user report ("the
      image keeps moving left and right") — `justify-content:center`
      packs and centers the `[text, image]` row as a single unit, and
      `#pageText`'s *actual* rendered width varies chunk-to-chunk
      (vertical text wraps into a discrete number of columns, rarely
      filling its budget exactly, and drops to ~0 during a silent gap
      between chunks when `blankPage()` empties it), so the whole row —
      image included — visibly shifted as that width changed. Desktop
      now uses the exact same right-anchored `justify-content:flex-end`
      as mobile/tablet (`getAvailableSpace()`/`recalcZenColumns()` still
      branch on `zenDesktopActive`, just for its own symmetric
      `ZEN_DESKTOP_PADDING_*_FRACTION`/`ZEN_DESKTOP_GAP_FRACTION` padding
      values, not for anchoring anymore) — confirmed via
      `getBoundingClientRect()` that the image's box stays pixel-
      identical even with `#pageText` fully emptied. Below 800px,
      resizing back falls through to the plain non-zen reader untouched
      ("default text-only mode").
      `.chrome-hidden` here is driven entirely separately, by a new
      **`#fullscreenToggleBtn`** (monitor icon, left of the theme
      toggle) calling `requestFullscreen()`/`exitFullscreen()`, reacted
      to via a `fullscreenchange` listener — **not** by the F11 key.
    - **Important finding, confirmed via research and direct testing
      before/while building this**: F11 itself is invisible to a web
      page by design — pressing it fires no DOM event and leaves
      `document.fullscreenElement` null; only a page's own
      `element.requestFullscreen()` call (from a genuine user gesture)
      is observable via `fullscreenchange`. There is no way to detect or
      react to the literal F11 key from JS. Confirmed live in this same
      sandboxed Browser pane too: calling `requestFullscreen()` here
      throws `"Permissions check failed"` (an iframe Permissions-Policy
      restriction specific to this embedded preview tool, not a code
      bug) — real fullscreen + the hover-reveal behavior around it could
      only be verified by faking `document.fullscreenElement` via
      `Object.defineProperty` and dispatching synthetic `mousemove`
      events, not end-to-end with a real click in this environment; a
      real standalone desktop browser tab should behave correctly. Once
      in fullscreen, moving the mouse into the bottom 20% of the
      viewport (`DESKTOP_CHROME_HOVER_ZONE`) reveals chrome, with a
      2.5s inactivity timeout (`DESKTOP_CHROME_HIDE_DELAY`) hiding it
      again — both confirmed via the simulated-fullscreen test above.
    - **Bug found via testing, fixed**: the manual force-zen release
      path set `zenActive = false` right before calling `applyZenState()`
      to force it to re-evaluate — but that function's own no-op guard
      then saw "no change" (since the variable already matched what it
      was about to compute) and returned *before* actually clearing the
      `.zen`/`.chrome-hidden` DOM classes, leaving zen mode stuck on
      visually even though tapping again correctly showed the button as
      inactive. Fixed by setting `zenActive = null` instead — a value
      that can never equal the freshly computed boolean, guaranteeing
      the guard always lets the real state re-apply.
  - **Fixed zen columns** (real user report: the side image "kept moving
    and resizing," not a pleasant reading experience) — the image and
    text columns are now computed once by `recalcZenColumns()` and
    cached (`zenColW`/`zenImgColW`/`zenRowH`), only on genuine
    layout-changing events (resize, fullscreen toggle, zen state
    transitions, the manual force-zen button); `getAvailableSpace()` is
    now just a cheap read of those cached numbers, called every chunk as
    before but no longer *measuring* anything. Root cause: the image's
    width used to be `auto` (aspect-ratio-driven, sized off its own
    natural dimensions) with the text getting "whatever's left" —
    perfectly stable only as long as the same image kept showing, but
    the side image *does* change (chapter-image rotation across
    playback time, a new chapter's own images, or the ID3-cover
    fallback), almost always to a different aspect ratio, which changed
    the image's rendered width and reflowed the text column right along
    with it. Fixed by making the two columns split the available width
    **evenly** (`colW = (innerW - gapW) / 2`, cached) and switching
    `#zenImage` from `width:auto` to `width:100%; object-fit:contain`
    (plus `flex-shrink:0` on `#zenImageWrap`, now given an explicit
    JS-set pixel width/height) — a differently-shaped image just
    letterboxes within its own unchanged box instead of resizing it.
    Confirmed via `getBoundingClientRect()`: swapping to a drastically
    different aspect-ratio image mid-chapter, or jumping several chunks
    ahead, leaves the wrapper's pixel box completely unchanged on both
    the mobile and desktop paths (both right-anchored — see below);
    resizing the window while already in zen correctly recomputes fresh
    even column widths. Text still refits its font size to whatever's
    currently cached (`fitFontSize`), so per-chunk text still adapts, it
    just no longer moves the *columns* themselves. This alone wasn't
    the full fix, though — desktop was still centered at this point, and
    a centered row still visibly shifted as `#pageText`'s actual width
    varied; see the device-specific zen mode entry above for why desktop
    was reverted to right-anchored too.
  - **Player controls row** (prev chapter / prev part / play-pause / next
    part / next chapter) — five `.iconBtn` circles, same size/style as the
    top bar, living inside `#metaRow` itself as its middle grid column
    rather than a row of their own. `#metaRow` was restructured from a
    plain flex row into a 3-column grid (`grid-template-columns: minmax(0,
    220px) 1fr auto`): left = `#metaLeftInfo` (cover + `#metaTextCol`
    title/author, capped at 220px), middle = `#playerControls` (the `1fr`
    track, stretched full-width by default grid `justify-self`), right =
    `#metaPillCol` (chapter pill + speed pill, now stacked vertically
    instead of one-per-text-line as before). Because the middle column's
    box always spans the *entire* leftover gap and the buttons are
    centered inside that box (`justify-content:center`), the button group
    is always a true center between the two info blocks, not just the
    center of the whole row — confirmed via `getBoundingClientRect()`
    (gap midpoint and button-row center matched to sub-pixel precision at
    several widths, including the narrowest one-button tier) and vertical
    centering against both blocks (`#metaRow`'s `align-items:center`).
    Responsive collapse (chapter-skip buttons hide first, then part-skip,
    leaving just play/pause) is driven by `updatePlayerControlsFit()`
    measuring `#playerControls`' actual `clientWidth` (the real grid-track
    width) against the pixel width the current button set needs — not a
    fixed viewport breakpoint — so it can never grow wide enough to crowd
    `#progressTrack` above or the info blocks beside it; recomputed on
    resize and whenever a chapter opens. Play/pause swaps its icon via a
    `play`/`pause` audio-event-driven `updatePlayPauseIcon()`; prev/next
    part reuse the existing `goPrev()`/`goNext()` chunk-seek functions,
    prev/next chapter are new (`goPrevChapter()`/`goNextChapter()`),
    disabled via `updateChapterNavButtons()` at the ends of `allChapters`.
    Built and verified in a throwaway `controls-mockup.html` copy first
    (per the user's explicit "mockup first, I check then only we
    proceed"), then promoted into `index.html` once approved.
  - **Post-launch bug/polish pass** (real user testing after the above
    landed, all fixed directly in `index.html` — small enough not to
    warrant another mockup round):
    - **Book-pill title/author color wrong in light theme** — `.bookTitle`/
      `.bookAuthor` (home grid + per-book library's left pill) used
      `--read-text-base`, the *reading text's* pre-highlight grey, which
      is deliberately close-to-grey in both themes (see the reading-text
      design note above) — fine in dark, illegible-ish in light. Split
      into its own `--book-pill-ink` variable (dark: `#d6d6d6`, same as
      before; light: `#000000`, actual black ink) so the reading text's
      own color relationship stays untouched.
    - **Stale Continue pill / bookmark list after leaving the reader via
      the library icon** — `goToLibrary()` just toggled
      `libraryScreen.style.display`, re-showing whatever DOM
      `renderLibrary()` last built (e.g. from initial book selection) —
      a bookmark just saved, or the resume position just having moved,
      wouldn't show up without detouring through the home screen first
      (which *does* call `renderLibrary()` fresh on re-entry). Fixed by
      calling `renderLibrary()` at the end of `goToLibrary()` too.
    - **Play icon looked off-center** — two compounding causes, only the
      second one being the actual complaint's real-world trigger:
      (1) the play triangle's bounding box (`5 3 19 12 5 21`) was already
      geometrically centered in its 24×24 viewBox, but a right-pointing
      triangle's flat edge reads heavier than its tip, so it looked
      shifted left — nudged 1.5 units right (`6.5 3 20.5 12 6.5 21`), the
      standard optical fix. (2) The real bug: `#metaRow`'s middle grid
      column (`#playerControls`) was a bare `1fr` with `min-width:0` —
      under CSS Grid's sizing algorithm, an unconstrained `1fr` track's
      minimum collapses to 0, so grid happily shrinks the *left* column
      down to fit the left+right columns' own content within the row and
      hands the middle column whatever's left over, which can genuinely
      be 0 when the outer two columns' content alone exceeds the row's
      width (confirmed at real phone width, 375px, with this book's
      unusually long "Chapter: 1/18 Part: 76/117" pill text eating most
      of the right column). With a 0-width track, the play/pause button
      doesn't shrink to fit - it just renders past the track's edge,
      overlapping the pill column, which reads as "not centered." Fixed
      by giving the middle column a real floor, `minmax(36px, 1fr)` (one
      icon button's width) - forces the left column (the only track with
      genuine shrink room; the pill column's text is `nowrap`, so it has
      none) to keep shrinking past where it stopped before.
    - **PC fullscreen: top 10% of the viewport also reveals chrome** —
      previously only the bottom 20% hover zone did. Shares the exact
      same mousemove listener/inactivity-hide timer as the bottom zone,
      just a second Y-position check. The top zone is also roughly where
      a real browser's own "press Esc to exit fullscreen" affordance
      appears as the mouse approaches - accepted as fine, not a conflict,
      since nothing of ours renders there while chrome-hidden (the top
      icon row is part of the same hidden set).
    - **Chrome overlays zen mode instead of pushing it** — real user
      report: revealing chrome (pause on mobile, hover on desktop
      fullscreen) visibly "pushed" the zen image/text layout upward,
      since `#timeRow`/`#progressTrack`/`#metaRow` were normal flex
      siblings of `#frame` (`flex:1`) - showing them reserved real flow
      height, shrinking `#frame` to make room. Fixed by wrapping those
      three in `#zenChromeOverlay`: `display:contents` outside zen (fully
      inert - the three rows stay direct flex children of `#readerScreen`
      exactly as before, unchanged flow/gap), but in zen it becomes a
      `position:absolute` flex column floating over `#frame` instead
      (anchored 16px from the screen edges, translucent blurred
      background via a new theme-aware `--zen-overlay-bg` variable so
      it's legible over arbitrary image/text underneath). `#frame` (still
      `flex:1`) now fills the *entire* available box regardless of chrome
      visibility - confirmed via `getBoundingClientRect()`: identical
      frame box with `.chrome-hidden` toggled on vs. off, in zen. Needed
      a `.zen.chrome-hidden` (not just `.chrome-hidden`) selector to hide
      the overlay, since a bare `.chrome-hidden` rule and the `.zen`
      positioning rule tie at the same specificity (2 IDs + 1 class) -
      without the extra class, whichever rule happened to be later in the
      stylesheet would silently win regardless of which state was
      actually active.
    - **Overlay scoped to only where chrome actually toggles** (real user
      report, screenshot of a normal non-fullscreen desktop window: the
      progress/meta row was floating over the bottom of the zen image
      instead of sitting under it like before) — the overlay's whole
      reason to exist is to avoid reflow when chrome toggles away, but
      desktop zen *outside* fullscreen never toggles chrome at all (it's
      always visible there - `chrome-hidden` is only ever set when
      `document.fullscreenElement` is truthy), so overlaying it there
      just floated it over the image for no reason. Fixed with a new
      `.fullscreen` class (`applyDesktopFullscreenChrome()`, set from
      `document.fullscreenElement` alongside the existing `chrome-hidden`
      toggle) and narrowed `#zenChromeOverlay`'s "should overlay"
      selector to `.zen:not(.desktop)` (mobile/tablet - always toggles)
      or `.zen.desktop.fullscreen` (desktop - only while genuinely
      fullscreen); desktop zen without `.fullscreen` now falls through to
      the base `display:contents` rule, i.e. back to normal flow under
      `#frame` exactly as it worked before the overlay feature existed.
      Confirmed via `getBoundingClientRect()` across all four states
      (windowed/fullscreen × chrome shown/hidden): windowed always stays
      in-flow (`#frame` sharing height with the meta row below it,
      identical box before entering and after exiting fullscreen),
      fullscreen always overlays (`#frame` full-height regardless of
      chrome visibility). This reintroduced the exact same specificity-tie
      class of bug as the entry above, twice - `.zen:not(.desktop)`
      reduces to the same 2-class specificity as `.zen.chrome-hidden`
      (`:not()`'s specificity is its argument's), and
      `.zen.desktop.fullscreen` (3 classes) outranks the original 2-class
      hide rule outright - chasing this with an ever-more-specific hide
      selector for every new show condition doesn't scale. Replaced the
      whole approach with one `!important` rule instead:
      `#readerScreen.chrome-hidden #zenChromeOverlay { display:none
      !important; }` - `chrome-hidden` should unconditionally win over
      "should overlay" regardless of *why* the overlay would otherwise
      show, so it gets a rule that wins unconditionally rather than
      another round of specificity arithmetic.
    - **Force-zen auto-plays on engage** (touch devices) - mobile
      chrome-hidden is otherwise only reachable by playing (see
      `updateChromeForPlaybackState()`), so forcing zen while paused
      previously left the user staring at a frozen, chrome-less screen
      with silent audio, needing a separate tap on the text area to
      actually start playback. `forceZenBtn`'s engage branch now calls
      `audio.play()` when paused, so one tap delivers hidden chrome *and*
      running audio together.
    - **Home screen title block** - "SHAMA" (Yu Mincho, 48px/400,
      `--ink`) + "Stylish Humanlike Audiobook Multiplatform Application"
      (same family, 28px/300, `--ink`) in a new `#homeHeader`, centered,
      above the book-pill grid. (The user's own wording had "Appllication"
      with a double L - corrected to the standard spelling here.)
    - **`#homeTitle` restyled to a large Roboto Black hero treatment**,
      replacing the plain 48px Yu Mincho from the entry above - given as
      a reference CSS block (`font-size:10em; letter-spacing:0.2em;
      font-weight:400; font-family:"roboto black"; margin-bottom:-50px;`)
      to adapt, not paste verbatim. Deviations, each for a concrete
      reason: (1) `font-family:"Roboto Black"` assumes that exact family
      is installed system-side, which isn't guaranteed - loaded Google
      Fonts' `Roboto:wght@900` instead (the real "Black" cut of the
      unified Roboto family) and paired it with `font-weight:900`, not
      the reference's `400` - weight 400 only makes sense if the "Black"
      cut is already baked into a separately-named family, which isn't
      what's actually loaded here. (2) `em`-based `font-size`/
      `margin-bottom` swapped for `rem`/`em`-off-the-computed-value - a
      bare 10em on the title itself is fine (nothing sets a weird
      font-size on `#homeTitle`'s parent), but `rem` is more robust to
      future nesting changes, and keeping `margin-bottom` in `em` (not
      `px`) means the tight title/subtitle coupling scales automatically
      with whatever the fluid font-size below computes, instead of a
      fixed `-50px` gap that would look wrong once the title's shrunk on
      a small screen. (3) Added responsive scaling the reference didn't
      specify a mechanism for, per the user's separate instruction: flat
      at 10rem (160px) for any viewport >=800px (so it's already flat
      well before 1440px, automatically satisfying "stop scaling bigger
      beyond 1440"), fluidly shrinking to a 3rem (48px) floor as width
      drops from 800px to 400px, flat again below that - one
      `clamp(3rem, calc(3rem + (10rem - 3rem) * ((100vw - 400px) /
      (800px - 400px))), 10rem)`, verified at 299/400/600/800/1800px
      (104px measured at 600px, the exact midpoint, confirming the
      linear interpolation math). Getting this calc() right needed two
      passes - the first version divided a px length by a bare unitless
      number pair (`(800 - 400)` instead of `(800px - 400px)`) and
      multiplied by a bare unitless `(10 - 3)` instead of `(10rem -
      3rem)`, which silently produced a tiny fraction-of-a-pixel result
      instead of a proper 0..1 ratio - caught by actually measuring the
      computed font-size at the 600px midpoint rather than trusting the
      formula by inspection.
    - **Home title/subtitle follow-up** (real user feedback after seeing
      the Roboto Black version live): `#homeSubtitle` switched from Yu
      Mincho to the same Roboto family as the title (keeping its own
      existing 300 weight - only the family needed to match, not the
      weight); `#homeTitle` eased from 900 (true Black) down to 700
      (Bold) since 900 read as too heavy; a new Google Fonts request
      loads `Roboto:wght@300;700` accordingly (900 dropped since nothing
      uses it anymore). Also fixed a real centering bug, not just a
      weight tweak: `letter-spacing` adds its gap *after* every
      character, including the last one, so `#homeTitle`'s own box was
      wider on the right than the left (no matching gap before the first
      character) - text-align/flex-centering centers that lopsided BOX,
      not the glyphs themselves, so the visible word sat left of true
      center by half the trailing gap (32px off at this title's 160px
      size, since 0.2em letter-spacing = a lot of absolute px at that
      scale - easily missed at a smaller size). Fixed with
      `margin-right:-0.2em` (matching the letter-spacing value) on
      `#homeTitle`, which shrinks the box used for flex-centering by
      exactly the trailing gap's width, so the box's centered position
      shifts right to compensate - confirmed via
      `getBoundingClientRect()`, subtracting the known trailing-gap
      pixel width from the title's box before computing its visual
      (glyphs-only) center: matched the subtitle's center to within
      0.01px, vs. the ~16px-off box-only comparison that looked wrong at
      first (comparing the two elements' raw bounding-box centers
      doesn't account for the phantom trailing space - the box center
      and the glyph-visual center are different points once
      letter-spacing is involved).
    - **Continue pill left the player fully stuck** (real user report:
      audio never plays, progress bar frozen, play/pause icon toggles
      but does nothing, next/prev part can't recover it either - only
      next/prev chapter did) - root-caused straight from the code, no
      logging needed. `onAudioPrepareReady()`'s resume branch called
      `seekToTime(resumeSeconds)` directly, but `seekToTime()` only ever
      sets `audio.currentTime` - it assumes a source is already loaded,
      true for every other call site (drag-to-seek, next/prev part, all
      act on a chapter that's already playing) but not this one, which
      is opening a chapter fresh. `audio.src` was never set on this path
      at all, so `currentTime`/`play()` were silent no-ops against an
      empty `<audio>` element (`readyState 0`) - matches every symptom:
      frozen progress bar (nothing loaded to seek within), next/prev part
      unable to recover (same `seekToTime()` call, same missing src),
      next/prev chapter "fixing" it (goes through `openChapter()`'s
      plain-open branch instead, which does set `audio.src`). Fixed by
      setting `audio.src`/`playbackRate`/`chapterTimeOffset` in the
      resume branch too, mirroring the plain-open branch, before calling
      `seekToTime()`. Confirmed via a real repro matching the bug report
      exactly (fresh page load → into the book → Continue pill) that
      `audio.src` is now populated, `currentTime` lands at the saved
      position, `paused` is false, and the position keeps advancing
      over real time afterward (not just a one-time seek).
  - **Volume control** (`#volumeToggleBtn` + `#volumePopup`) - went
    through three design rounds before landing, each one mocked up and
    rejected/refined by the user before the next:
    1. A small flyout slider pill below the icon (10×50px, drag to set
       volume 0-1) - rejected outright ("don't like it").
    2. The icon itself morphing into a 400px-tall capsule in place
       (width unchanged, only height/border-radius animate, icon glyph
       fading out to reveal a bottom-up fill) - also rejected.
    3. **What shipped**: clicking the icon drops a stack of four pills
       below it - `+` / level (0-100, step 5) / `-` / mute - each the
       same 36px `.iconBtn` size, right-aligned flush with the icon,
       10px gaps throughout, all using the plain default icon-button
       colors (no accent/active styling). Icon slot order shifted one
       more notch: volume (16) is now the rightmost, preset/theme/
       fullscreen-or-force-zen each pushed out by 44px (60/104/148).
    - Unlike every other flyout in this codebase, this one is
      **icon-toggled only** - no click-outside-to-close, no
      visibility/blur handling (both existed in the discarded capsule
      design and were deliberately dropped here per explicit
      instruction: "clicking other area... will return" was a rule for
      round 2, not this one).
    - Holding `+`/`-` repeats (`startVolumeRepeat()`): fires once
      immediately, waits `VOLUME_REPEAT_DELAY` (400ms), then repeats
      every `VOLUME_REPEAT_INTERVAL` (120ms) until `pointerup`/
      `pointercancel` - bound on `window`, not the buttons themselves,
      so dragging off the button while still holding still stops it
      correctly.
    - **Mute** (`setMuted()`) swaps the main button's icon between two
      stacked SVGs (`#volumeIconNormal`/`#volumeIconMuted`, same
      show/hide-by-`display` pattern as the reader's play/pause icons)
      and remembers the pre-mute level (`volumeBeforeMute`) so clicking
      mute again restores it. Muting always force-closes the popup
      immediately (`volumePopup.classList.remove('show')`), regardless
      of which direction it just toggled. Raising volume via `+` while
      muted is a *second*, independent way to unmute - continues from 0
      (0→5, not a restore of `volumeBeforeMute`) and flips the icon back,
      handled by a one-line check at the top of `startVolumeRepeat()`
      rather than duplicating unmute logic.
    - **Bug found via testing, fixed**: `#volumeLevelPill` reuses
      `.iconBtn` on a plain `<div>` (not a `<button>`) for the numeric
      readout - Chrome's UA stylesheet gives `<button>` a default
      `box-sizing:border-box`, but a `<div>` defaults to `content-box`,
      so the level pill rendered ~2px larger than its button siblings
      (border added on top of the declared 36px instead of being
      absorbed by it) and threw off the stack's alignment. Fixed by
      making `.iconBtn` declare `box-sizing:border-box` explicitly -
      harmless for the existing `<button>`-based icons, which already
      behaved that way by default.
  - **Screen Wake Lock** (`audio` `play`/`pause` listeners in
    `index.html`) — real user report: the screen goes to sleep on
    Android/iPad during playback, unlike the offline Android app (which
    has its own native way of staying awake during playback that a
    browser tab has no equivalent access to). Fixed with the Screen Wake
    Lock API (`navigator.wakeLock.request('screen')` on `play`, released
    on `pause`) — feature-detected and wrapped in try/catch so it's a
    silent no-op wherever unsupported, never breaks playback either way.
    Re-acquired on `visibilitychange` back to `visible` if audio is still
    playing, since the browser auto-releases the lock whenever a tab is
    hidden/backgrounded (per spec) — otherwise switching to another app
    and back mid-chapter would silently lose the behavior for the rest of
    the session. **Confirmed on real hardware**: a real-world test on a
    Samsung Galaxy A52s (SM-A528B, Android 14, Chrome 152) still showed
    the screen sleeping over plain LAN/Wi-Fi use - but re-tested over a
    USB-debugging session (`chrome://inspect` from a desktop, phone
    connected by cable) the screen correctly stayed awake. That split
    result points at Samsung's own per-app battery/sleep management for
    Chrome (a known category of issue on Samsung devices specifically -
    they aggressively suspend background/idle web platform APIs unless
    an app is battery-optimization-exempted or, apparently, unless USB
    debugging is active) rather than a bug in this code - the Wake Lock
    request/release logic itself is doing the right thing. Flagged to
    revisit later (a Samsung-specific "disable battery optimization for
    Chrome" instruction in the README, maybe) rather than chased further
    now. Separately confirmed harmless on this sandbox's own preview pane,
    which blocks the API outright via its Permissions-Policy
    (`NotAllowedError`, same class of restriction as the Fullscreen API
    note above) - the try/catch swallows it and playback is unaffected.
    - **Follow-up bug found via the same real-device test**: at the
      phone's actual 412px viewport width, a real chapter with a long
      "Chapter: 15/16 Part: 111/164" pill string left the lone play/pause
      button (already down to just itself via hide-chapter+hide-part)
      visibly crowding the pill next to it - the middle grid column's
      `minmax(36px, 1fr)` floor guarantees just enough room for the
      button itself, with zero breathing space left over once the outer
      columns are large. Fixed with a fourth, independent tier: a flat
      `window.innerWidth < 450` check (`PLAYER_CONTROLS_MIN_VIEWPORT`,
      a real device measurement, not derived from measuring content)
      hides play/pause too below that width, applied unconditionally
      alongside (not instead of) the existing content-fit checks for
      hide-chapter/hide-part. Tap-anywhere-on-the-text-to-play/pause
      keeps working regardless, since that's `#frame`'s own gesture
      listener, untouched by this. Verified the exact boundary (449px
      hides it, 450px shows it) plus the real 412px width.
    - **Per-book library art pill overflowed its own border on the same
      412px phone** (real screenshot from the user, not just an
      inspected breakpoint): `.libraryBookPill`'s narrow-screen rule
      forces the pill to `min(400px, 90vw)` - a shrunk *square* (370.8px
      at 412px width) - but `.bookCover`/`.bookCoverPlaceholder` stays a
      fixed 300x300 (sized for the ≥800px case, where the pill itself is
      a fixed, roomier 400x400). At 370.8px, fitting a still-300px-tall
      cover plus two text lines plus 32px of padding needs ~392px -
      title and author visibly spilled out past the pill's rounded
      border instead of being clipped or making the pill taller. Fixed
      two ways together rather than tuning yet another magic threshold:
      the pill's `height` switched from another `min(400px, 90vw)` to
      `auto` (grows to fit whatever it actually contains), and the cover
      itself switched to `width:100%; height:auto; aspect-ratio:1/1`
      inside that same narrow-screen media query - scales down with the
      pill instead of staying locked at 300px, and stays visually square
      via the aspect-ratio rather than a hardcoded height. Scoped to only
      `.libraryBookPill` inside the existing `@media (max-width:799px)`
      block, so the ≥800px fixed-400x400/300x300 case (home grid pills,
      and the wide per-book library layout) is completely untouched -
      confirmed via `getBoundingClientRect()` at both 412px (370.8px
      pill, 334.8px square cover, height now auto-sized taller than its
      own width to fit the text below) and 1000px (unchanged 400x400
      pill / 300x300 cover, exactly as before).
    - **Library two-column layout overflowed off the left edge on a real
      iPad 8th gen** (real screenshot, landscape, ~1080px viewport) - the
      two fixed 400px columns plus the original 50px `#libraryBody` gap
      needed 850px, which with `#libraryScreen`'s own 24px×2 padding
      comes to 898px total. That should have cleared 1080px comfortably,
      but real Safari still overflowed, invisibly clipped since
      `html`/`body` have `overflow:hidden` - no scrollbar ever hinted
      anything was cut off. Root-caused two contributing gaps rather than
      chasing the exact Safari-specific rendering delta: (1) `.twoColRow`
      (the chapter-list overflow escalation's two sub-columns) was itself
      408px (2×200px+8px gap) inside its own 400px-wide parent,
      `#libraryRightCol` - an 8px overflow of its own, unrelated to the
      device, just never large enough to notice before. (2) the
      `@media (max-width:799px)` breakpoint gating the whole two-column
      layout was never actually wide enough for what it turns on - even
      the *old* 898px-needed math left every width from 800-898px
      overflowing by design, a latent bug independent of this specific
      device. Fixed with three coordinated changes: `#libraryBody`'s gap
      50px→24px, `.twoColRow`'s sub-columns 200px→196px each (400px
      total, now matching its parent exactly), and the breakpoint itself
      799px→899px (so the two-column layout only ever activates at
      ≥900px, a width its own 824px-plus-padding=872px minimum clears
      with 28px to spare) - the gap/sub-column shrink alone would have
      fixed this one reported device, but not the underlying
      breakpoint-narrower-than-its-own-layout flaw, so both were done
      together. Verified via direct element-position checks (`rect.left`
      going negative is the real overflow signal here - `document.body.
      scrollWidth > innerWidth` reads false-negative once `overflow:hidden`
      is in play, since the clipped content never registers as
      scrollable) at 820px (now correctly falls back to single-column,
      previously the two-column layout's real danger zone), the new
      899/900px boundary (899 still single-column, 900 switches to
      two-column with 38px of margin), and the real 1080px iPad width
      (872px needed, comfortable margin, `.twoColRow` now flush with its
      parent instead of 8px over).
    - **Single tap decoupled from play/pause** (real user feedback: on
      touch devices, revealing the interface meant also pausing playback
      just to look at it - single tap had been doing double duty as both
      "toggle chrome" and "toggle playback"). `registerTap()`'s tap-count
      dispatch shifted down one: 1 tap → `toggleChromeFromTap()` (new),
      2 taps → `togglePlayPause()` (was 1 tap), 3+ → `goToLibrary()`
      (unchanged). Applies uniformly everywhere - mouse and touch already
      shared this one gesture handler via Pointer Events, so desktop
      clicking the text area now also needs a double-click for play/pause,
      any width, fullscreen or not, no separate device branch needed.
      `toggleChromeFromTap()` itself *is* device-branched, matching the
      two existing conditions chrome-hidden can ever apply under: mobile/
      tablet zen (any state, `zenCoarsePointerMql`) toggles `chrome-hidden`
      directly; desktop only while genuinely `document.fullscreenElement`
      (independent of zen, matching `applyDesktopFullscreenChrome()`'s own
      gating) - and there it's wired into the *same* `desktopChromeHideTimer`/
      `DESKTOP_CHROME_HIDE_DELAY` the existing hover-to-reveal already
      uses, so a tap-triggered reveal auto-hides itself again identically
      rather than needing a second explicit tap to dismiss. Elsewhere
      (plain reading mode, desktop zen in a normal window) a single tap
      is a harmless no-op, since chrome is already always shown there.
      The pre-existing pause-reveals-chrome behavior
      (`updateChromeForPlaybackState()`, tied to the `audio` `play`/
      `pause` events themselves, not this gesture) is untouched - it
      still fires from *any* pause source (double-tap, the visible
      play/pause button, a Bluetooth headset button), so resuming
      playback still re-hides chrome on mobile even after a tap-triggered
      peek, exactly as before. The dedicated always-visible play/pause
      *button* also keeps its plain single-click handler unchanged -
      only the ambiguous whole-text-area gesture needed the double-tap
      disambiguation, an explicit button never had that ambiguity to
      begin with. Verified all six combinations directly (paused/
      playing state before and after, `chrome-hidden` class state): plain
      reading mode (single tap no-ops, double-tap toggles playback,
      triple-tap still reaches the library), mobile zen (single tap
      reveals chrome without touching playback, a second single tap
      re-hides it, double-tap still pauses and - via the untouched
      pause-reveals-chrome path - leaves chrome visible), desktop
      fullscreen (single click reveals chrome without pausing, auto-hides
      again after the same `DESKTOP_CHROME_HIDE_DELAY` as hovering,
      double-click still toggles playback), and desktop zen in a normal
      window (single tap changes nothing, `chrome-hidden` never applies
      there regardless).
    - **Book-pill cover art feathered, matching zen mode** - the same
      rectangular vignette mask zen mode's side image already used
      (`#zenImage`'s two-linear-gradient, `intersect`/`source-in`
      composited mask, faded 0-30%/70-100% on both axes) now also
      applies to `.bookCover`/`.bookCoverPlaceholder` - the home grid's
      pills and the library screen's art pill both use this same class.
      Extracted just the mask properties into a shared
      `#zenImage, .bookCover, .bookCoverPlaceholder` rule (kept separate
      from `#zenImage`'s own `height`/`width`/`object-fit`/`border-radius`
      declarations, which stay zen-only) so the setting can't drift
      between the two - deliberately *not* merging the whole rule, since
      `#zenImage`'s `width:100%; height:100%;` would otherwise have
      silently overridden the book covers' own fixed 300x300 sizing
      (same class-level specificity, later in source order wins on ties).
    - **Real-fullscreen-only padding bump to 10%/10%** - explicit
      request scoped to "full screen zen mode" specifically, not desktop
      zen in general: a wide (>=800px) window already gets `.zen.desktop`
      (side-image layout) regardless of whether it's actually fullscreen,
      but only real fullscreen (`.zen.desktop.fullscreen`) now gets the
      more generous `padding:10vh 10vw` - windowed desktop zen keeps the
      original, tighter `3vh 3vw`. The new CSS rule's extra `.fullscreen`
      class gives it higher specificity than the plain `.zen.desktop`
      rule, so it wins regardless of source order. `recalcZenColumns()`
      mirrors this with a `document.fullscreenElement` check choosing
      between `ZEN_DESKTOP_PADDING_*_FRACTION` (3%) and the new
      `ZEN_DESKTOP_FULLSCREEN_PADDING_FRACTION` (10%) before splitting
      the image/text columns - confirmed via `getComputedStyle()` (70px/
      100px on a 700x1000 window, exactly 10%) and the resulting column
      width matching the hand-computed value ((968 - 200 padding - 20
      gap) / 2 = 374px) precisely, then reverting cleanly to 21px/30px
      (3%) on exiting fullscreen.
    - **iPad still had ~1-2% padding after the fix above** - real user
      report, confirmed by directly reproducing it: `zenCoarsePointerMql`
      (`pointer: coarse`) is true for any touchscreen, iPad's included,
      and `applyZenState()`'s `desktopMatch` check explicitly excludes
      coarse pointers regardless of actual screen width - so an iPad in
      landscape zen (1080px wide, plenty roomy) still gets routed through
      the *mobile* code path, never touching the `.zen.desktop.fullscreen`
      rule above at all. Manually forcing `.zen` without `.desktop` while
      faking `document.fullscreenElement` reproduced the exact reported
      symptom (8.1px/21.6px/10.8px - the old 1%/2%/1% mobile numbers).
      Asked the user whether the fix should be tablet-only or apply to
      phones too, since Android phones share this same mobile code path
      and were separately reported as "already good" with their existing
      small padding, before just changing the shared numbers - answer was
      all touch devices. Fixed by recognizing mobile zen has no separate
      "windowed vs fullscreen" state the way desktop does at all - a
      phone/iPad rotating into zen *is* the fullscreen-equivalent
      experience (immersive mode and all), so unlike desktop there's
      nothing to conditionally branch on; `#readerScreen.zen #frame`
      (the mobile/tablet base rule) simply became a flat `10vh 10vw`
      unconditionally, replacing the old asymmetric `1vh 2vw 1vh 1vw`
      (right padding used to be 2x the left, as the side image's own
      buffer - the explicit new request doesn't distinguish left from
      right, so this asymmetry was dropped along with the fix).
      `ZEN_TOP_BOTTOM_FRACTION`/`ZEN_LEFT_FRACTION`/`ZEN_RIGHT_FRACTION`
      all became `0.10` to match. Desktop's own windowed-vs-fullscreen
      distinction (3% vs 10%, from the entry above) is untouched.
      Verified via the same manual-class-simulation technique (81px/108px
      = exactly 10% of a real 810x1080 iPad-landscape-sized viewport),
      plus a regression check confirming genuine fine-pointer desktop
      still gets 3% windowed / 10% fullscreen exactly as before.
      **Follow-up**: once confirmed working, the user asked to halve
      every "full screen zen" padding scheme from 10% to 5% (mobile/
      tablet's flat 10vh/10vw, and desktop's `.zen.desktop.fullscreen`
      override) - desktop's separate windowed 3vh/3vw was untouched,
      since it was never part of the 10% scheme being reduced. Same
      verification approach, same three numbers re-checked at the new
      value (40.5px/54px = exactly 5% of an 810x1080 viewport, both for
      mobile and for desktop fullscreen; desktop windowed unchanged at
      24.3px/32.4px = 3%).
- **Known limitation, deferred on purpose**: `last_position` is keyed
  only by `book_id` (see `server/src/db.js`) — no per-user/session
  column at all. Fine for a single listener (today's actual usage), but
  if a second concurrent listener ever uses the same book, whichever one
  reports its position last silently overwrites the other's Continue
  pill with no merge or warning. Bookmarks don't have this problem (each
  gets its own row), but do share one list with no ownership - anyone
  can delete anyone else's. The real fix, discussed but not yet
  scheduled, is a `user_id`/session column tied to whoever's
  authenticated via Cloudflare Access (already sitting in every request
  as a header once Access is in front of the tunnel) - revisit this
  before actually inviting a second person to use it regularly.
- **Not yet done**: the two other roadmap pieces explicitly deferred to
  build on top of this: a streaming-optimized Android client, and TV
  casting (custom Google Cast receiver).

## Exposing beyond the LAN (in progress, `server/README.md` has the steps)

Domain purchased (`shamareader.online` on GoDaddy) and added to a free
Cloudflare account; `cloudflared` installed via `winget` on the dev
machine. Mid-setup, one real snag worth remembering: GoDaddy's default
"WebsiteBuilder Site" placeholder A record on the bare root (`@`) got
imported into the Cloudflare zone during the "Add a site" scan, which
made `cloudflared tunnel route dns audiobook shamareader.online` fail
with "record already exists" (DNS won't let a CNAME coexist with an A
record at the same name). Resolved by routing a subdomain instead
(`audiobook.shamareader.online`) rather than deleting the root record -
avoids touching the placeholder entirely, and matches the original plan
of not exposing the bare domain directly. `cloudflared tunnel route dns
audiobook audiobook.shamareader.online` succeeded once retried against
the subdomain. Still ahead: point `~/.cloudflared/config.yml`'s
`hostname` at that same subdomain, confirm `cloudflared tunnel run` +
`npm start` together actually serve `https://audiobook.shamareader.online`,
then the Cloudflare Access email-allowlist gate (not yet configured -
the tunnel alone makes this internet-reachable but not yet
access-controlled, so don't treat it as safe to leave running unattended
until Access is confirmed working).

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
