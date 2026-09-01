# jp-audiobook-server

HTTP server + web client for streaming the same audiobook folders the
Android app and its Windows sibling read locally (chaptered MP3s +
`chapter_XXX.sync.json` + an optional `book.json`) to a browser instead.

This is an additive, opt-in feature living in the main
`JP-Audiobook-Interactive-Reader` repo (branch `server-web-client`) - it
doesn't change or depend on the Android app's offline folder-picker flow
at all. See the root `CLAUDE.md` for the full design writeup and the
`server-web-client` roadmap plan for how this was scoped.

## Setup

1. `cd server && npm install`
2. Copy `config.example.json` to `config.json` and point `libraryPaths`
   at your book folder(s) - each entry is one book, and the folder's own
   name becomes its id/URL segment, so give each a unique name:
   ```json
   {
     "port": 3939,
     "libraryPaths": [
       "F:\\AUDIOBOOK-FINAL\\after-dark\\interactive"
     ]
   }
   ```
3. `npm start`, then open `http://localhost:3939/` in a browser.

`config.json` is gitignored (machine-specific paths, same spirit as the
Android project's `local.properties`) - `config.example.json` is the
committed template.

## Current scope

- Multi-book: configure as many `libraryPaths` entries as you like, each
  becomes its own book. The home screen (`http://localhost:3939/`) shows
  every configured book as a pill with its cover/title/author - sourced
  from `book.json`'s `title` if present, otherwise the first chapter's
  ID3 `album`/`artist` tags. Clicking a pill goes to that book's usual
  library view (Continue/chapters/bookmarks); "← All books" goes back.
  The selection persists in the browser's `localStorage`, separately from
  the resume-position/bookmarks stored server-side per book.
- Bookmarks and resume position are stored server-side in SQLite
  (`server/data.sqlite`, gitignored) via Node's built-in `node:sqlite` -
  no separate database install needed.
- No authentication. Fine on a trusted LAN; **do not expose this
  directly to the internet without the setup below.**

## Exposing this beyond your LAN

This app is meant to run on your own desktop, only reachable when you
choose to run it - not a standing internet service. The recommended
setup for occasional, invite-only access from outside your network:

1. **Buy a domain** (any registrar - GoDaddy, Namecheap, etc. all work
   the same way here).
2. **Add the domain to a free Cloudflare account** and switch its
   nameservers to Cloudflare's (Cloudflare's own "Add a site" flow walks
   through this).
3. **Create a named Cloudflare Tunnel** (not the random
   `trycloudflare.com` quick-tunnel, which changes URL every run) mapping
   a subdomain - e.g. `audiobook.yourdomain.com` - to this server's local
   port. This is an outbound-only connection from your desktop to
   Cloudflare: no router port-forwarding, no static IP, and your home IP
   is never exposed to visitors. Cloudflare handles TLS automatically.
4. **Put Cloudflare Access in front of that subdomain**, gated by an
   allowlist of specific invited email addresses. This is the actual
   "who's allowed in" layer, enforced at Cloudflare's edge *before* a
   request ever reaches this Node process - the server itself has no
   auth code, deliberately, because Access is doing that job instead.
5. Run `cloudflared` and `npm start` together whenever you want it
   reachable; stop either one and the domain goes dark again. There's no
   standing exposure between sessions.

Because this becomes internet-facing, every route that looks up a file
by id (`bookId`/`chapterBase`/chapter-image filename) validates the
value against a real, freshly-scanned allowlist before touching the
filesystem - never builds a path directly from an unvalidated request
parameter. See the hardening comments in `src/routes/books.js` and
`src/chapterImages.js` if you're adding a new route that reads a file.
