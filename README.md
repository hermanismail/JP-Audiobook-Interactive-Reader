# JP Audiobook Player — Android shell (Phase 4)

## Important: this has not been compiled

Everything up through Phase 3 (Python pipeline changes, the JS in the
browser preview) was actually run and syntax-checked in a real interpreter
before being handed over. This Android project **could not be** — there's
no Android SDK, Gradle, or Kotlin compiler available in the environment
this was written in, only a bare JDK. I checked what I could (every XML
file parses, the JS in the WebView asset is syntactically valid, the
Kotlin file's braces/parens/brackets balance and I reviewed it carefully
against the Android APIs it calls), but a Gradle sync in Android Studio is
the first real compile this code will see. Please treat this phase as
"written and reasoned through," not "tested," until you've built it.

## What's in here

- **`app/src/main/java/.../MainActivity.kt`** — single Activity hosting a
  `WebView`. Handles:
  - the SAF folder picker (`ActivityResultContracts.OpenDocumentTree`),
    with the picked folder's permission persisted so you don't have to
    re-pick it every launch
  - a `window.Android` JS bridge (`pickFolder`, `listChapters`,
    `readTextFile`) for the folder listing and small text files
    (`sync.json`, `book.json`)
  - a virtual `https://appassets.androidplatform.net/chapter-audio/<name>`
    URL space that streams the actual MP3 straight out of the SAF-picked
    folder, **with HTTP Range support** — this matters because the
    prev/next buttons work by setting `audio.currentTime` directly, and
    Chromium's `<audio>` needs range support to seek reliably rather than
    just play sequentially from the start
- **`app/src/main/assets/web/index.html`** — the same vertical-text
  player logic you already tested and approved in the Phase 3 browser
  preview (fit-to-page font sizing, blank-during-silence, prev/next/play),
  plus a plain chapter-list screen in front of it so picking a folder goes
  somewhere sensible.

## Building it

1. Open the `JPAudiobookPlayer` folder in Android Studio (File → Open).
2. Let it sync Gradle. It's configured for **AGP 9.1.1** with Kotlin's
   built-in compiler support (no separate Kotlin plugin needed) — this
   requires **JDK 17** and an Android Studio release that supports AGP 9.x
   (Otter or later; if your Studio predates that, it'll likely prompt you
   to update the Gradle/AGP version, which should be safe to accept).
3. There's no committed `gradlew`/`gradle-wrapper.jar` — I couldn't
   generate a working one without network access. Android Studio should
   offer to create the wrapper automatically on first open; if not,
   `File → Sync Project with Gradle Files` should do it using its bundled
   Gradle.
4. Run on a device or emulator running Android 8.0 (API 26) or newer.

## Things worth specifically testing first

- **The folder picker and persistence** — pick your real output folder,
  kill the app fully, relaunch, and confirm it remembers the folder
  without re-prompting.
- **Seeking** — this is the part I'm least certain about without a real
  device to try it on. Play a chapter, jump around with Prev/Next several
  times in a row (including jumping to a chunk far from the current one),
  and listen for any glitching, silence, or the audio not actually moving
  to the right spot. If seeking misbehaves, the Range-handling code in
  `serveChapterAudio()` is the first place to look.
- **A chapter with the 130-char hard-limit chunk** — same check as the
  Phase 2/3 mockups, now on a real device screen size instead of my
  360×720 approximation.
- **Book title / cover** — only wired up if you already have a
  `book.json` in the output folder; if not, the library screen just shows
  "JP Audiobook Player" as a fallback title, which is expected.

## Known gaps (not attempted this phase, by design)

- No lock-screen / notification media controls — audio only plays while
  the app is in the foreground.
- No swipe gesture for paging, only the Prev/Next buttons.
- `serveChapterAudio()` re-lists the folder on every audio request rather
  than caching the lookup — fine at one-book scale, worth revisiting if
  it ever feels slow.
