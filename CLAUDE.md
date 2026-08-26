# CLAUDE.md — JP Audiobook Player (Android)

Context handoff for Claude Code, continuing work started in Claude Desktop
(Chat/Cowork). Read this before touching anything.

## Handoff snapshot

- **As of:** August 26, 2026
- **Git status:** this folder is **not yet a git repository** — no `.git`
  directory present. There's no branch or commit history to compare
  against yet. If you initialize git here, do it deliberately (check
  `.gitignore` covers `.gradle/`, `.idea/`, `.kotlin/`, and `app/build/`
  before the first commit) and update this section afterward.
- This file describes the state of the code on disk right now, not a
  point-in-time commit — treat the "Current status" and "Priority testing
  checklist" sections below as the source of truth, and update them as
  things get confirmed or change.

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

## Current status: Phase 4, uncompiled

This code was written and reasoned through in an environment with **no
Android SDK, Gradle, or Kotlin compiler** — only a bare JDK. Every XML file
was checked to parse, the WebView's JS was checked for syntax validity, and
the Kotlin file was manually reviewed against the Android APIs it calls,
but **none of it has been through a real Gradle build yet**. Treat this as
"written," not "tested."

Initial mechanics have since been smoke-tested via Android Studio connected
to a real phone (per the developer, "done testing initial mechanics") — but
this was exploratory, not a full pass through the checklist below. Don't
assume anything in "Things worth specifically testing" is confirmed working
just because the app launches.

## Structure

- `app/src/main/java/.../MainActivity.kt` — single Activity hosting a
  `WebView`. Handles:
  - SAF folder picker (`ActivityResultContracts.OpenDocumentTree`), with
    persisted permission so the folder doesn't need re-picking every launch
  - `window.Android` JS bridge: `pickFolder`, `listChapters`, `readTextFile`
    (for `sync.json` / `book.json` and other small text files)
  - Virtual URL space
    `https://appassets.androidplatform.net/chapter-audio/<name>` that
    streams MP3s straight out of the SAF-picked folder, **with HTTP Range
    support** — required because Prev/Next work by setting
    `audio.currentTime` directly, and Chromium's `<audio>` needs Range
    support to seek reliably instead of just playing sequentially
- `app/src/main/assets/web/index.html` — the vertical-text player UI
  (fit-to-page font sizing, blank-during-silence, prev/next/play), same
  logic already approved in the Phase 3 browser mockup, plus a chapter-list
  screen in front of it

## Build setup

- AGP 9.1.1, Kotlin's built-in compiler support (no separate Kotlin
  plugin needed) — requires **JDK 17** and an Android Studio release
  supporting AGP 9.x (Otter or later)
- No committed `gradlew` / `gradle-wrapper.jar` as of last handoff —
  Android Studio generates it on first open, or via
  `File → Sync Project with Gradle Files`. If Claude Code needs to build
  from the CLI rather than through Studio, check whether the wrapper has
  been generated yet; if not, flag it rather than assuming `./gradlew` exists.
- Target: Android 8.0 (API 26) and newer

## Priority testing checklist (not yet confirmed)

1. **Folder picker persistence** — pick the real output folder, force-kill
   the app, relaunch, confirm it remembers the folder without re-prompting.
2. **Seeking** — least-confident area without a real device at write time.
   Play a chapter, jump around with Prev/Next repeatedly, including jumps
   to a chunk far from the current position. Watch for glitching, silence,
   or audio not actually moving to the right spot. If seeking misbehaves,
   start in `serveChapterAudio()`'s Range-handling code.
3. **130-char hard-limit chunk** — same check as Phase 2/3 mockups, now on
   a real device screen instead of a 360×720 approximation.
4. **Book title / cover fallback** — only wired up if a `book.json` exists
   in the output folder; without one, the library screen should show "JP
   Audiobook Player" as a fallback title (expected, not a bug).

## Known gaps (by design, not yet attempted)

- No lock-screen / notification media controls — audio only plays in
  foreground.
- No swipe gesture for paging, only Prev/Next buttons.
- `serveChapterAudio()` re-lists the folder on every audio request rather
  than caching the lookup — fine at one-book scale, worth revisiting if it
  ever feels slow.

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
