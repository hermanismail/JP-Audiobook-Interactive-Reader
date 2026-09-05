"""
Process + settings plumbing for the SHAMA Server launcher.

Deliberately dependency-free (stdlib only) so the launcher's venv needs
nothing but customtkinter for the UI itself.

Two design decisions worth knowing before reading:

1. Child processes write straight to LOG FILES, never to a pipe the GUI
   holds. The launcher is explicitly allowed to close while the server
   and tunnel keep running, so a pipe whose read end dies with the GUI
   would eventually block or kill the child on Windows. Writing to a file
   handle the child owns survives the GUI closing, and gives one uniform
   way to show output whether this launcher session spawned the process
   or is re-attaching to one an earlier session started.

2. Nothing machine-specific is hardcoded here. The server directory is
   derived from this file's own location, the port/book count come from
   ../server/config.json, and the tunnel name + public hostname are read
   out of ~/.cloudflared/config.yml at runtime. That keeps this file
   safe to commit to a public repo - see launcher/README.md.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

# Windows process-creation flags. CREATE_NO_WINDOW keeps a console from
# flashing up behind the GUI; NEW_PROCESS_GROUP stops a Ctrl+C aimed at
# the launcher from tearing the children down with it.
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
_SPAWN_FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP

LAUNCHER_DIR = Path(__file__).resolve().parent
REPO_DIR = LAUNCHER_DIR.parent
SERVER_DIR = REPO_DIR / "server"
LOG_DIR = LAUNCHER_DIR / "logs"
STATE_PATH = LAUNCHER_DIR / ".state.json"

SERVER_LOG = LOG_DIR / "server.log"
TUNNEL_LOG = LOG_DIR / "tunnel.log"

# Logs are append-only across sessions; trim on startup so they can't grow
# without bound. Keeping the tail (not the head) is what matters - the
# recent lines are the ones the log panel backfills from.
MAX_LOG_BYTES = 2 * 1024 * 1024
KEEP_LOG_BYTES = 200 * 1024

DEFAULT_PORT = 3939


# --------------------------------------------------------------------------
# settings discovery
# --------------------------------------------------------------------------

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _read_cloudflared_config():
    """
    Pull the tunnel name and first ingress hostname out of
    ~/.cloudflared/config.yml.

    Hand-parsed rather than pulling in PyYAML: the file is a handful of
    lines in a fixed shape (tunnel / credentials-file / ingress list), and
    a missing value just falls back to a placeholder in the UI rather than
    breaking anything.
    """
    path = Path.home() / ".cloudflared" / "config.yml"
    result = {"tunnel": None, "hostname": None, "config_path": str(path)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return result

    m = re.search(r"^\s*tunnel:\s*(\S+)\s*$", text, re.MULTILINE)
    if m:
        result["tunnel"] = m.group(1).strip().strip('"').strip("'")

    m = re.search(r"^\s*-?\s*hostname:\s*(\S+)\s*$", text, re.MULTILINE)
    if m:
        result["hostname"] = m.group(1).strip().strip('"').strip("'")

    return result


def load_settings():
    """
    Everything the UI needs to describe itself, resolved at runtime.

    launcher.config.json (gitignored, optional) can override any of it -
    see launcher.config.example.json.
    """
    server_cfg = _read_json(SERVER_DIR / "config.json")
    cf = _read_cloudflared_config()
    overrides = _read_json(LAUNCHER_DIR / "launcher.config.json")

    settings = {
        "port": server_cfg.get("port", DEFAULT_PORT),
        "book_count": len(server_cfg.get("libraryPaths") or []),
        "tunnel_name": cf["tunnel"],
        "hostname": cf["hostname"],
        "cloudflared_config": cf["config_path"],
        "server_dir": str(SERVER_DIR),
        "node": shutil.which("node"),
        "cloudflared": shutil.which("cloudflared"),
    }
    settings.update({k: v for k, v in overrides.items() if v not in (None, "")})
    settings["local_url"] = "http://localhost:%s" % settings["port"]
    settings["public_url"] = (
        "https://%s" % settings["hostname"] if settings["hostname"] else None
    )
    return settings


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------

def _run_quiet(args):
    return subprocess.run(
        args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
    )


def process_matches(pid, image_name):
    """
    True when `pid` is alive AND is actually the image we expect.

    The image-name check is what makes re-attaching safe: a bare
    "does this PID exist" test would happily latch onto whatever unrelated
    process Windows recycled that number onto after a reboot.
    """
    if not pid:
        return False
    try:
        out = _run_quiet(["tasklist", "/FI", "PID eq %d" % int(pid), "/FO", "CSV", "/NH"])
    except Exception:
        return False
    return image_name.lower() in (out.stdout or "").lower()


def kill_tree(pid):
    """Kill a PID and anything it spawned. Best-effort; never raises."""
    if not pid:
        return
    try:
        _run_quiet(["taskkill", "/PID", str(int(pid)), "/T", "/F"])
    except Exception:
        pass


def pid_on_port(port):
    """
    PID of whatever is LISTENING on `port`, or None.

    This is what lets the launcher adopt a server it didn't start - an
    orphan from a previous session, or one started by hand - instead of
    spawning a second node that dies instantly on EADDRINUSE while the
    health probe cheerfully succeeds against the *other* process. (That
    exact false-green was caught by the launcher's functional test.)
    """
    try:
        out = _run_quiet(["netstat", "-ano", "-p", "TCP"])
    except Exception:
        return None
    needle = ":%s" % port
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        # e.g.  TCP    0.0.0.0:3939   0.0.0.0:0   LISTENING   1324
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(needle):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def first_pid_for_image(image_name):
    """PID of the first running process with this image name, or None."""
    try:
        out = _run_quiet(["tasklist", "/FI", "IMAGENAME eq %s" % image_name, "/FO", "CSV", "/NH"])
    except Exception:
        return None
    for line in (out.stdout or "").splitlines():
        fields = [f.strip('"') for f in line.split('","')]
        if len(fields) >= 2 and fields[0].lower() == image_name.lower():
            try:
                return int(fields[1].replace(",", ""))
            except ValueError:
                continue
    return None


def probe_server(port, timeout=1.5):
    """
    Liveness check for the audiobook server specifically - not just
    "something is bound to the port". /api/books is the cheapest route
    that only our own server would answer.
    """
    url = "http://127.0.0.1:%s/api/books" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _trim_log(path):
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            data = path.read_bytes()[-KEEP_LOG_BYTES:]
            path.write_bytes(b"[log trimmed]\n" + data)
    except Exception:
        pass


def ensure_log_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def spawn(cmd, cwd, log_path):
    """
    Start a child with its output appended to `log_path`.

    Returns the PID. The child intentionally outlives this process (see
    the module docstring) - closing the launcher leaves it running.
    """
    ensure_log_dir()
    _trim_log(log_path)
    # Opened here and left to the child: once handed to Popen the OS keeps
    # the handle alive for the child's lifetime regardless of what this
    # process does afterwards.
    fh = open(log_path, "a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=_SPAWN_FLAGS,
            close_fds=True,
        )
    finally:
        fh.close()  # the child holds its own duplicated handle
    return proc.pid


def append_note(log_path, text):
    """Write a launcher-side line into a service's log file."""
    ensure_log_dir()
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(text.rstrip() + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# state file - what lets a fresh launcher session re-attach
# --------------------------------------------------------------------------

def save_state(server_pid, tunnel_pid, started_at):
    try:
        STATE_PATH.write_text(
            json.dumps(
                {
                    "server_pid": server_pid,
                    "tunnel_pid": tunnel_pid,
                    "started_at": started_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_state():
    return _read_json(STATE_PATH)


def clear_state():
    try:
        STATE_PATH.unlink(missing_ok=True)
    except Exception:
        pass


# --------------------------------------------------------------------------
# log tailing
# --------------------------------------------------------------------------

class LogTail(threading.Thread):
    """
    Follows one log file and pushes ("source", "line") onto a queue.

    `backfill_lines` seeds the queue with the tail of what's already in the
    file - that's what gives the log panel continuity when the launcher is
    re-opened against services an earlier session started.
    """

    def __init__(self, path, out_queue, source, backfill_lines=0):
        super().__init__(daemon=True)
        self.path = Path(path)
        self.queue = out_queue
        self.source = source
        self.backfill_lines = backfill_lines
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        # Wait for the file to appear - a just-spawned child may not have
        # written anything yet.
        while not self._stop.is_set() and not self.path.exists():
            time.sleep(0.25)
        if self._stop.is_set():
            return

        try:
            fh = open(self.path, "r", encoding="utf-8", errors="replace")
        except Exception:
            return

        with fh:
            if self.backfill_lines:
                try:
                    existing = fh.readlines()
                    for line in existing[-self.backfill_lines:]:
                        self.queue.put((self.source, line.rstrip("\n")))
                except Exception:
                    pass
            else:
                fh.seek(0, os.SEEK_END)

            while not self._stop.is_set():
                line = fh.readline()
                if line:
                    self.queue.put((self.source, line.rstrip("\n")))
                else:
                    time.sleep(0.2)


def new_log_queue():
    return queue.Queue()
