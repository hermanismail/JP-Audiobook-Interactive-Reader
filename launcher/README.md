# SHAMA Server launcher

A small desktop window that starts the audiobook server and the Cloudflare
tunnel together, shows a red/green indicator for each, and merges both
logs into one console.

Styled to match JP-Audiobook-Generator's Progress window (same palette,
card radii, chip row and dark Consolas log panel) so the two apps read as
one family.

## Setup (once)

```powershell
cd launcher
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

The venv is deliberately local to this folder rather than installing
CustomTkinter into the system Python.

## Pin it to the taskbar

```powershell
powershell -ExecutionPolicy Bypass -File create-shortcut.ps1
```

That drops **SHAMA Server.lnk** on the Desktop pointing at
`.venv\Scripts\pythonw.exe launcher.py` (pythonw, so no console window
appears behind the GUI). Right-click it → **Pin to taskbar**.

Drop an `icon.ico` in this folder before running the script if you want a
custom taskbar icon — it's gitignored, same as the Android app's icon.

## How it behaves

- **One button** runs the whole lifecycle: Start → Starting… → Stop.
- The header pill is the overall state; each service also has its own
  red/green LED, so "server fine, tunnel dead" is visible as exactly that.
- **Closing the window leaves the server and tunnel running.** Re-opening
  re-attaches: the saved PIDs are verified (by PID *and* image name, so a
  recycled PID can't be mistaken for ours), the server is health-probed on
  `/api/books`, and the log panel backfills from the on-disk logs. Uptime
  keeps counting from the original start.
- **Stop** kills both process trees and clears the saved state.

## Nothing machine-specific is committed

This repo is public, so the launcher hardcodes none of it and discovers
everything at runtime:

| What | Where it comes from |
| --- | --- |
| Server folder | this file's own location (`../server`) |
| Port, book count | `../server/config.json` (gitignored) |
| Tunnel name, public hostname | `~/.cloudflared/config.yml` |
| node, cloudflared binaries | `PATH` |

Gitignored here: `.venv/`, `logs/`, `.state.json`, `launcher.config.json`,
`icon.ico`, `*.lnk`. `launcher.config.example.json` is the committed
template — you only need a real `launcher.config.json` to override
something the auto-detection gets wrong.

## Notes

- The server is spawned as `node src/index.js` rather than `npm start`, so
  there's one clean PID to track and kill instead of npm's wrapper plus a
  child node.
- Child processes write **straight to log files**, never to a pipe the GUI
  holds — the launcher is allowed to close while they keep running, and a
  pipe whose reader died would eventually block the child on Windows. The
  GUI tails those files instead, which is also what makes re-attach show
  real log history.
- `cloudflared tunnel run <name>` resolves `~/.cloudflared/config.yml` on
  its own regardless of working directory, so nothing had to move out of
  that folder.
