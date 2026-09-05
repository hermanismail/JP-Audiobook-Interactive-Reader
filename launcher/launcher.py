"""
SHAMA Server launcher - one button that brings up the audiobook server
and the Cloudflare tunnel together, with a red/green indicator per
service and a merged log console.

Visual design deliberately mirrors JP-Audiobook-Generator's Progress
window (same palette, card radii, chip row and dark Consolas log panel)
so the two desktop apps read as one family. The colour constants below
are copied from that project's ui_common.py / progress_window.py.

Closing this window leaves the server and tunnel RUNNING. Re-opening it
re-attaches: PIDs are verified against the state file, the server is
health-probed, and the log panel backfills from the on-disk logs, so the
window comes back showing the state things are actually in rather than
pretending everything is stopped.
"""

import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

import runner

# --------------------------------------------------------------------------
# palette - mirrored from JP-Audiobook-Generator/ui_common.py
# --------------------------------------------------------------------------
COLOR_BG = "#F7F7FA"
COLOR_CARD = "#FFFFFF"
COLOR_CARD_BORDER = "#E7E7EC"
COLOR_TITLE = "#17171C"
COLOR_SUBTITLE = "#8B8B94"
COLOR_ACCENT = "#6C5DD3"
COLOR_ACCENT_HOVER = "#5B4FC0"
COLOR_ACCENT_SOFT = "#EFECFB"
COLOR_ACCENT_DISABLED = "#DEDAF4"
COLOR_BTN_NEUTRAL_BORDER = "#D8D8DE"
COLOR_BTN_NEUTRAL_TEXT = "#3A3A42"

# state colours (progress_window.py's BAR_COLORS / status pill)
COLOR_OK = "#2FB668"
COLOR_OK_SOFT = "#E6F8ED"
COLOR_FAIL = "#D85A5A"
COLOR_FAIL_SOFT = "#FCEAEA"
COLOR_IDLE = "#7A7A85"
COLOR_IDLE_SOFT = "#F0F0F3"
COLOR_WAIT = "#C98A2E"
COLOR_WAIT_SOFT = "#FFF3DD"

# log console (progress_window.py)
COLOR_LOG_BG = "#1C1C22"
COLOR_LOG_BORDER = "#2A2A32"
COLOR_LOG_TS = "#6FD3E6"
COLOR_LOG_TEXT = "#C7C7D1"
COLOR_LOG_OK = "#5FD98A"
COLOR_LOG_ERR = "#F1706E"
COLOR_LOG_LAUNCHER = "#B9A3F7"
COLOR_LOG_SERVER = "#7FB6F5"
COLOR_LOG_TUNNEL = "#E8B968"
COLOR_LOG_IDLE = "#6B6B77"

WINDOW_W, WINDOW_H = 700, 720

# How long each half gets before the launcher calls it a failure.
SERVER_START_TIMEOUT = 25.0
TUNNEL_START_TIMEOUT = 40.0
HEALTH_INTERVAL = 5.0
BACKFILL_LINES = 120

# Don't judge cloudflared dead the instant it's spawned - a freshly created
# process can take a moment to show up in tasklist, and without this grace
# window the very first tick after spawning reports "cloudflared exited"
# before it ever had a chance to start. (Caught by the launcher's own
# functional test, which saw the tunnel flagged dead within one tick.)
TUNNEL_LIVENESS_GRACE = 4.0

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_ERROR = "error"


class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings = runner.load_settings()
        self.state_name = STATE_STOPPED
        self.server_pid = None
        self.tunnel_pid = None
        self.started_at = None
        self.start_deadline = None
        self.tunnel_deadline = None
        self.tunnel_spawned_at = None
        self.server_ready = False
        self.tunnel_ready = False
        self.last_health = 0.0

        self.log_queue = runner.new_log_queue()
        self.tails = []

        self.title("SHAMA Server")
        self.geometry("%dx%d" % (WINDOW_W, WINDOW_H))
        self.minsize(WINDOW_W, 560)
        self.configure(fg_color=COLOR_BG)

        # Optional local icon (gitignored - see launcher/README.md); the app
        # falls back to the default Tk icon when it isn't there.
        icon = Path(__file__).resolve().parent / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass

        self._build_ui()
        self._attach_existing()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_job = self.after(200, self._tick)

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=24, pady=22)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(3, weight=1)  # log card takes the slack

        self._build_header(root)
        self._build_control_card(root)
        self._build_chips(root)
        self._build_log_card(root)

    def _build_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(
            header, width=46, height=46, corner_radius=12, fg_color=COLOR_ACCENT_SOFT
        )
        badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        badge.grid_propagate(False)
        self.badge_label = ctk.CTkLabel(
            badge, text="◉", font=ctk.CTkFont(size=22), text_color=COLOR_ACCENT
        )
        self.badge_label.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            header,
            text="SHAMA Server",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLOR_TITLE,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            header,
            text="Audiobook server & Cloudflare tunnel",
            font=ctk.CTkFont(size=14),
            text_color=COLOR_SUBTITLE,
            anchor="w",
        ).grid(row=1, column=1, sticky="w")

        self.pill = ctk.CTkLabel(
            header,
            text="Stopped",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=14,
            fg_color=COLOR_IDLE_SOFT,
            text_color=COLOR_IDLE,
            width=112,
            height=30,
        )
        self.pill.grid(row=0, column=2, rowspan=2, sticky="e")

    def _build_control_card(self, parent):
        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=16,
            border_width=1,
            border_color=COLOR_CARD_BORDER,
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        card.grid_columnconfigure(0, weight=1)

        self.main_btn = ctk.CTkButton(
            card,
            text="▶  Start Server",
            command=self._on_main_button,
            height=48,
            corner_radius=8,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#FFFFFF",
        )
        self.main_btn.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 16))

        self.svc_server = self._service_row(
            card, row=1, name="Audiobook Server", url=self.settings["local_url"]
        )
        self.svc_tunnel = self._service_row(
            card,
            row=2,
            name="Cloudflare Tunnel",
            url=self.settings["hostname"] or "(no tunnel configured)",
            pady=(0, 18),
        )

    def _service_row(self, parent, row, name, url, pady=(0, 11)):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row, column=0, sticky="ew", padx=20, pady=pady)
        line.grid_columnconfigure(2, weight=1)

        led_holder = ctk.CTkFrame(line, fg_color="transparent", width=14, height=14)
        led_holder.grid(row=0, column=0, sticky="w", padx=(0, 9))
        led_holder.grid_propagate(False)
        led = ctk.CTkFrame(
            led_holder, width=10, height=10, corner_radius=5, fg_color=COLOR_FAIL
        )
        led.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            line,
            text=name,
            font=ctk.CTkFont(size=14),
            text_color=COLOR_TITLE,
            anchor="w",
            width=150,
        ).grid(row=0, column=1, sticky="w")

        url_label = ctk.CTkLabel(
            line,
            text=url,
            font=ctk.CTkFont(size=13),
            text_color=COLOR_SUBTITLE,
            anchor="w",
        )
        url_label.grid(row=0, column=2, sticky="w")

        state_label = ctk.CTkLabel(
            line,
            text="Stopped",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_IDLE,
            anchor="e",
            width=86,
        )
        state_label.grid(row=0, column=3, sticky="e")

        return {"led": led, "url": url_label, "state": state_label}

    def _build_chips(self, parent):
        chips = ctk.CTkFrame(parent, fg_color="transparent")
        chips.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        for i in range(4):
            chips.grid_columnconfigure(i, weight=1, uniform="chip")

        self.chip_uptime = self._chip(chips, 0, "--:--:--", "Uptime")
        self._chip(chips, 1, str(self.settings["port"]), "Local Port")
        self._chip(chips, 2, str(self.settings["book_count"]), "Books")
        self.chip_public = self._chip(
            chips, 3, "Offline", "Public URL", size=17, color=COLOR_IDLE
        )

    def _chip(self, parent, col, value, caption, size=24, color=COLOR_TITLE):
        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=14,
            border_width=1,
            border_color=COLOR_CARD_BORDER,
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))

        value_label = ctk.CTkLabel(
            card,
            text=value,
            font=ctk.CTkFont(size=size, weight="bold"),
            text_color=color,
        )
        value_label.pack(pady=(14, 0))
        ctk.CTkLabel(
            card, text=caption, font=ctk.CTkFont(size=12), text_color=COLOR_SUBTITLE
        ).pack(pady=(3, 13))
        return value_label

    def _build_log_card(self, parent):
        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=16,
            border_width=1,
            border_color=COLOR_CARD_BORDER,
        )
        card.grid(row=3, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 12))
        head.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            head,
            text="\U0001f4c4  Log",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TITLE,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            head,
            text="\U0001f5d1  Clear Log",
            command=self._clear_log,
            width=100,
            height=30,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_CARD,
            hover_color=COLOR_BG,
            text_color=COLOR_BTN_NEUTRAL_TEXT,
            border_width=1,
            border_color=COLOR_BTN_NEUTRAL_BORDER,
        ).grid(row=0, column=1, sticky="e")

        self.log_box = ctk.CTkTextbox(
            card,
            corner_radius=10,
            fg_color=COLOR_LOG_BG,
            border_width=1,
            border_color=COLOR_LOG_BORDER,
            text_color=COLOR_LOG_TEXT,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 18))

        for tag, colour in (
            ("ts", COLOR_LOG_TS),
            ("launcher", COLOR_LOG_LAUNCHER),
            ("server", COLOR_LOG_SERVER),
            ("tunnel", COLOR_LOG_TUNNEL),
            ("ok", COLOR_LOG_OK),
            ("err", COLOR_LOG_ERR),
            ("idle", COLOR_LOG_IDLE),
            ("text", COLOR_LOG_TEXT),
        ):
            try:
                self.log_box.tag_config(tag, foreground=colour)
            except Exception:
                try:
                    self.log_box._textbox.tag_config(tag, foreground=colour)
                except Exception:
                    pass

        self.log_box.configure(state="disabled")
        self._log_raw(
            "Idle. Press Start Server to launch the audiobook server and Cloudflare tunnel.",
            "idle",
        )

    # -------------------------------------------------------------- logging
    def _log_raw(self, text, tag="text"):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", (tag,))
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _log(self, source, text):
        """One coloured, timestamped line: HH:MM:SS [source] message."""
        body_tag = "text"
        low = text.lower()
        if any(k in low for k in ("err ", "error", "failed", "fatal", "refused")):
            body_tag = "err"
        elif any(
            k in low
            for k in ("listening on", "registered tunnel connection", "ready —", "ready -")
        ):
            body_tag = "ok"

        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("%H:%M:%S") + "  ", ("ts",))
        self.log_box.insert("end", "[%s]" % source, (source,))
        self.log_box.insert("end", " " * max(1, 10 - len(source)), ("text",))
        self.log_box.insert("end", text + "\n", (body_tag,))
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log_raw("Log cleared.", "idle")

    # ---------------------------------------------------------- state paint
    def _set_state(self, name):
        self.state_name = name

        pill_map = {
            STATE_STOPPED: ("Stopped", COLOR_IDLE_SOFT, COLOR_IDLE),
            STATE_STARTING: ("Starting", COLOR_WAIT_SOFT, COLOR_WAIT),
            STATE_RUNNING: ("Running", COLOR_OK_SOFT, COLOR_OK),
            STATE_ERROR: ("Tunnel error", COLOR_FAIL_SOFT, COLOR_FAIL),
        }
        text, bg, fg = pill_map[name]
        self.pill.configure(text=text, fg_color=bg, text_color=fg)
        self.badge_label.configure(text="◐" if name == STATE_STARTING else "◉")

        if name == STATE_STARTING:
            self.main_btn.configure(
                text="◐  Starting…",
                state="disabled",
                fg_color=COLOR_ACCENT_DISABLED,
                text_color=COLOR_ACCENT,
                border_width=0,
            )
        elif name in (STATE_RUNNING, STATE_ERROR):
            self.main_btn.configure(
                text="■  Stop Server",
                state="normal",
                fg_color=COLOR_CARD,
                hover_color=COLOR_FAIL_SOFT,
                text_color=COLOR_FAIL,
                border_width=2,
                border_color=COLOR_FAIL,
            )
        else:
            self.main_btn.configure(
                text="▶  Start Server",
                state="normal",
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="#FFFFFF",
                border_width=0,
            )

    def _set_service(self, svc, label, colour):
        svc["led"].configure(fg_color=colour)
        svc["state"].configure(text=label, text_color=colour)
        svc["url"].configure(
            text_color=COLOR_ACCENT if colour == COLOR_OK else COLOR_SUBTITLE
        )

    def _set_public(self, online):
        self.chip_public.configure(
            text="Online" if online else "Offline",
            text_color=COLOR_OK if online else COLOR_IDLE,
        )

    # ------------------------------------------------------------- lifecycle
    def _attach_existing(self):
        """
        Re-attach to a server/tunnel an earlier launcher session started.

        Both halves are verified independently, so "server up, tunnel dead"
        (the failure that actually matters) comes back looking exactly like
        that rather than as a blanket green or grey.
        """
        state = runner.load_state()
        server_pid = state.get("server_pid")
        tunnel_pid = state.get("tunnel_pid")

        server_alive = runner.process_matches(server_pid, "node.exe") and runner.probe_server(
            self.settings["port"]
        )
        tunnel_alive = runner.process_matches(tunnel_pid, "cloudflared.exe")

        # No usable state file, but something is already serving on our port
        # (an orphan from a killed session, or a server started by hand) -
        # adopt it rather than ignoring it and later double-starting.
        if not server_alive and runner.probe_server(self.settings["port"]):
            found = runner.pid_on_port(self.settings["port"])
            if runner.process_matches(found, "node.exe"):
                server_pid, server_alive = found, True
        if not tunnel_alive:
            found = runner.first_pid_for_image("cloudflared.exe")
            if found:
                tunnel_pid, tunnel_alive = found, True

        if not server_alive and not tunnel_alive:
            runner.clear_state()
            return

        self.server_pid = server_pid if server_alive else None
        self.tunnel_pid = tunnel_pid if tunnel_alive else None
        self.server_ready = server_alive
        self.tunnel_ready = tunnel_alive
        self.started_at = state.get("started_at") or time.time()

        self._start_tails(backfill=True)
        self._log("launcher", "Re-attached to services started earlier.")

        if server_alive:
            self._set_service(self.svc_server, "Listening", COLOR_OK)
        else:
            self._set_service(self.svc_server, "Stopped", COLOR_FAIL)
        if tunnel_alive:
            self._set_service(self.svc_tunnel, "Connected", COLOR_OK)
        else:
            self._set_service(self.svc_tunnel, "Stopped", COLOR_FAIL)

        self._set_public(bool(tunnel_alive))
        self._set_state(STATE_RUNNING if (server_alive and tunnel_alive) else STATE_ERROR)

    def _start_tails(self, backfill=False):
        self._stop_tails()
        lines = BACKFILL_LINES if backfill else 0
        for path, source in (
            (runner.SERVER_LOG, "server"),
            (runner.TUNNEL_LOG, "tunnel"),
        ):
            tail = runner.LogTail(path, self.log_queue, source, backfill_lines=lines)
            tail.start()
            self.tails.append(tail)

    def _stop_tails(self):
        for tail in self.tails:
            tail.stop()
        self.tails = []

    def _on_main_button(self):
        if self.state_name in (STATE_STOPPED, STATE_ERROR) and not (
            self.server_pid or self.tunnel_pid
        ):
            self._start_all()
        else:
            self._stop_all()

    def _start_all(self):
        node = self.settings.get("node")
        if not node:
            self._log("launcher", "node.exe not found on PATH - cannot start the server.")
            return

        self._set_state(STATE_STARTING)
        self._set_service(self.svc_server, "Starting", COLOR_WAIT)
        self._set_service(self.svc_tunnel, "Waiting", COLOR_WAIT)
        self.server_ready = False
        self.tunnel_ready = False
        self.started_at = time.time()
        self.start_deadline = time.time() + SERVER_START_TIMEOUT
        self.tunnel_deadline = None
        self.tunnel_spawned_at = None

        self._start_tails(backfill=False)

        # Something already on the port? Adopt it. Spawning a second node
        # would die instantly on EADDRINUSE while the health probe still
        # answered (from the *other* process), leaving a convincing green
        # light attached to a dead PID.
        if runner.probe_server(self.settings["port"], timeout=0.8):
            existing = runner.pid_on_port(self.settings["port"])
            if runner.process_matches(existing, "node.exe"):
                self.server_pid = existing
                self._log(
                    "launcher",
                    "Server already running on port %s (pid %s) - attached."
                    % (self.settings["port"], existing),
                )
                return  # _tick_starting sees the probe succeed and chains the tunnel
            self._log(
                "launcher",
                "Port %s is in use by something that isn't our server."
                % self.settings["port"],
            )
            self._set_service(self.svc_server, "Port busy", COLOR_FAIL)
            self._set_service(self.svc_tunnel, "Stopped", COLOR_IDLE)
            self._set_state(STATE_STOPPED)
            return

        self._log("launcher", "Starting audiobook server…")
        runner.append_note(
            runner.SERVER_LOG, "--- launcher start %s ---" % time.strftime("%Y-%m-%d %H:%M:%S")
        )
        try:
            self.server_pid = runner.spawn(
                [node, "src/index.js"], runner.SERVER_DIR, runner.SERVER_LOG
            )
            self._log("launcher", "node src/index.js  (pid %s)" % self.server_pid)
        except Exception as exc:
            self._log("launcher", "Failed to start server: %s" % exc)
            self._set_state(STATE_STOPPED)
            self._set_service(self.svc_server, "Stopped", COLOR_FAIL)
            self._set_service(self.svc_tunnel, "Stopped", COLOR_FAIL)

    def _start_tunnel(self):
        cloudflared = self.settings.get("cloudflared")
        tunnel_name = self.settings.get("tunnel_name")
        if not cloudflared or not tunnel_name:
            self._log(
                "launcher",
                "No cloudflared binary or tunnel name found - running LAN-only.",
            )
            self._set_service(self.svc_tunnel, "Skipped", COLOR_IDLE)
            self._finish_start(tunnel_ok=False)
            return

        # cloudflared resolves ~/.cloudflared/config.yml itself regardless of
        # working directory, so nothing here has to live in a special folder.
        self._log("launcher", "Starting Cloudflare tunnel ‘%s’…" % tunnel_name)
        self._set_service(self.svc_tunnel, "Connecting", COLOR_WAIT)
        runner.append_note(
            runner.TUNNEL_LOG, "--- launcher start %s ---" % time.strftime("%Y-%m-%d %H:%M:%S")
        )
        try:
            self.tunnel_pid = runner.spawn(
                [cloudflared, "tunnel", "run", tunnel_name],
                runner.LAUNCHER_DIR,
                runner.TUNNEL_LOG,
            )
            self.tunnel_spawned_at = time.time()
            self.tunnel_deadline = self.tunnel_spawned_at + TUNNEL_START_TIMEOUT
            self._log("launcher", "cloudflared tunnel run %s  (pid %s)" % (tunnel_name, self.tunnel_pid))
        except Exception as exc:
            self._log("launcher", "Failed to start tunnel: %s" % exc)
            self._set_service(self.svc_tunnel, "Failed", COLOR_FAIL)
            self._finish_start(tunnel_ok=False)

    def _finish_start(self, tunnel_ok):
        self.tunnel_ready = tunnel_ok
        # We just established the truth about both halves, so start the
        # periodic health cycle from now rather than letting it fire
        # immediately on the next tick (which would re-probe redundantly and
        # stall the UI thread right at the transition).
        self.last_health = time.time()
        self._set_public(tunnel_ok)
        self._set_state(STATE_RUNNING if tunnel_ok else STATE_ERROR)
        runner.save_state(self.server_pid, self.tunnel_pid, self.started_at)
        if tunnel_ok and self.settings.get("public_url"):
            self._log("launcher", "Ready — %s" % self.settings["public_url"])
        elif not tunnel_ok:
            self._log("launcher", "Tunnel unavailable — server still reachable on the LAN.")

    def _stop_all(self):
        self._log("launcher", "Stopping…")
        if self.tunnel_pid:
            runner.kill_tree(self.tunnel_pid)
            self._log("tunnel", "Tunnel stopped.")
        if self.server_pid:
            runner.kill_tree(self.server_pid)
            self._log("server", "Server stopped.")

        self.server_pid = None
        self.tunnel_pid = None
        self.server_ready = False
        self.tunnel_ready = False
        self.started_at = None
        self.start_deadline = None
        self.tunnel_deadline = None
        self.tunnel_spawned_at = None
        runner.clear_state()
        self._stop_tails()

        self._set_service(self.svc_server, "Stopped", COLOR_FAIL)
        self._set_service(self.svc_tunnel, "Stopped", COLOR_FAIL)
        self._set_public(False)
        self.chip_uptime.configure(text="--:--:--")
        self._set_state(STATE_STOPPED)
        self._log("launcher", "All processes stopped.")

    # ------------------------------------------------------------- main loop
    def _tick(self):
        self._drain_logs()
        self._update_uptime()

        now = time.time()
        if self.state_name == STATE_STARTING:
            self._tick_starting(now)
        elif self.state_name in (STATE_RUNNING, STATE_ERROR):
            if now - self.last_health > HEALTH_INTERVAL:
                self.last_health = now
                self._tick_health()

        self._tick_job = self.after(250, self._tick)

    def _tick_starting(self, now):
        if not self.server_ready:
            if runner.probe_server(self.settings["port"], timeout=0.4):
                self.server_ready = True
                self._set_service(self.svc_server, "Listening", COLOR_OK)
                self._start_tunnel()
            elif self.start_deadline and now > self.start_deadline:
                self._log("launcher", "Server did not come up in time.")
                self._set_service(self.svc_server, "Failed", COLOR_FAIL)
                self._set_state(STATE_ERROR)
            return

        # Server is up; waiting on the tunnel to register an edge connection.
        if self.tunnel_deadline:
            if self.tunnel_ready:
                return
            past_grace = (
                self.tunnel_spawned_at
                and now - self.tunnel_spawned_at > TUNNEL_LIVENESS_GRACE
            )
            if past_grace and not runner.process_matches(self.tunnel_pid, "cloudflared.exe"):
                self._log("launcher", "cloudflared exited during startup.")
                self._set_service(self.svc_tunnel, "Failed", COLOR_FAIL)
                self._finish_start(tunnel_ok=False)
            elif now > self.tunnel_deadline:
                self._log("launcher", "Tunnel did not register a connection in time.")
                self._set_service(self.svc_tunnel, "Failed", COLOR_FAIL)
                self._finish_start(tunnel_ok=False)

    def _tick_health(self):
        server_ok = runner.probe_server(self.settings["port"], timeout=0.6)
        tunnel_ok = runner.process_matches(self.tunnel_pid, "cloudflared.exe")

        if server_ok != self.server_ready:
            self.server_ready = server_ok
            self._set_service(
                self.svc_server,
                "Listening" if server_ok else "Stopped",
                COLOR_OK if server_ok else COLOR_FAIL,
            )
            if not server_ok:
                self._log("launcher", "Server is no longer responding.")

        if tunnel_ok != self.tunnel_ready:
            self.tunnel_ready = tunnel_ok
            self._set_service(
                self.svc_tunnel,
                "Connected" if tunnel_ok else "Stopped",
                COLOR_OK if tunnel_ok else COLOR_FAIL,
            )
            self._set_public(tunnel_ok)
            if not tunnel_ok:
                self._log("launcher", "Cloudflare tunnel is no longer running.")

        if not server_ok and not tunnel_ok:
            self._stop_all()
        else:
            self._set_state(STATE_RUNNING if (server_ok and tunnel_ok) else STATE_ERROR)

    def _drain_logs(self):
        drained = 0
        while drained < 60:
            try:
                source, line = self.log_queue.get_nowait()
            except Exception:
                break
            drained += 1
            if not line.strip():
                continue
            self._log(source, line)

            # cloudflared announces readiness in its own log rather than
            # anywhere queryable, so that line is what flips the tunnel green.
            if (
                source == "tunnel"
                and not self.tunnel_ready
                and "registered tunnel connection" in line.lower()
            ):
                self._set_service(self.svc_tunnel, "Connected", COLOR_OK)
                self._finish_start(tunnel_ok=True)

    def _update_uptime(self):
        if not self.started_at or self.state_name == STATE_STOPPED:
            return
        secs = int(time.time() - self.started_at)
        self.chip_uptime.configure(
            text="%02d:%02d:%02d" % (secs // 3600, (secs // 60) % 60, secs % 60)
        )

    def _on_close(self):
        """Leave the services running; just remember them for next time."""
        if self.server_pid or self.tunnel_pid:
            runner.save_state(self.server_pid, self.tunnel_pid, self.started_at)
        # Cancel the pending tick before tearing the window down, otherwise
        # Tk fires it against a destroyed widget and complains on stderr.
        if getattr(self, "_tick_job", None):
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self._stop_tails()
        self.destroy()


def main():
    ctk.set_appearance_mode("light")
    LauncherApp().mainloop()


if __name__ == "__main__":
    main()
