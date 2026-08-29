import os
import re
import sys
import time
import shutil
import queue
import threading
import traceback
from datetime import datetime

# When launched with no console attached (pythonw, .pyw, or a --windowed/
# --noconsole PyInstaller build), sys.stdout / sys.stderr are None. Some
# libraries call print()/sys.stdout.write() internally and will crash with
# "AttributeError: 'NoneType' object has no attribute 'write'" if we don't
# give them somewhere harmless to write to.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import yt_dlp
    from yt_dlp.utils import download_range_func
except ImportError:
    # No console is guaranteed to be visible, so a print() here would be
    # silently lost. Show a real dialog instead.
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Missing dependency",
        "yt-dlp is not installed.\n\nInstall it with:\n    pip install -U yt-dlp"
    )
    sys.exit(1)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def format_seconds(total_seconds: float) -> str:
    """Convert seconds (float) into HH:MM:SS or MM:SS string."""
    total_seconds = max(0, int(round(total_seconds)))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_time_to_seconds(text: str):
    """Parse HH:MM:SS, MM:SS or SS into seconds (float). Returns None if invalid."""
    text = text.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if not (2 <= len(parts) <= 3):
        return None
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    h, m, s = parts
    return h * 3600 + m * 60 + s


def human_filesize(num_bytes):
    if not num_bytes:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


# --------------------------------------------------------------------------- #
# Custom dual-handle range slider (Canvas based)
# --------------------------------------------------------------------------- #

class RangeSlider(tk.Canvas):
    """A horizontal slider with two draggable handles representing a start
    and end value between `min_val` and `max_val`."""

    HANDLE_R = 9
    PAD = 16
    TRACK_COLOR = "#3c3f41"
    RANGE_COLOR = "#5aa9e6"
    START_COLOR = "#5aa9e6"
    END_COLOR = "#e67e22"

    def __init__(self, parent, width=560, height=36, min_val=0.0, max_val=100.0,
                 on_change=None, **kwargs):
        super().__init__(parent, width=width, height=height,
                          bg=kwargs.pop("bg", "#2b2b2b"), highlightthickness=0, **kwargs)
        self.w = width
        self.h = height
        self.min_val = min_val
        self.max_val = max_val if max_val > min_val else min_val + 1.0
        self.start_val = min_val
        self.end_val = self.max_val
        self.on_change = on_change
        self.track_y = height // 2
        self._dragging = None  # 'start' | 'end' | None

        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_resize)

        self._draw()

    # -- coordinate mapping -------------------------------------------------
    def _usable_width(self):
        return max(1, self.w - 2 * self.PAD)

    def _val_to_x(self, val):
        span = self.max_val - self.min_val
        ratio = 0.0 if span <= 0 else (val - self.min_val) / span
        return self.PAD + ratio * self._usable_width()

    def _x_to_val(self, x):
        x = max(self.PAD, min(self.w - self.PAD, x))
        ratio = (x - self.PAD) / self._usable_width()
        return self.min_val + ratio * (self.max_val - self.min_val)

    # -- drawing -------------------------------------------------------------
    def _draw(self):
        self.delete("all")
        self.create_line(self.PAD, self.track_y, self.w - self.PAD, self.track_y,
                          fill=self.TRACK_COLOR, width=5, capstyle=tk.ROUND)
        x1 = self._val_to_x(self.start_val)
        x2 = self._val_to_x(self.end_val)
        self.create_line(x1, self.track_y, x2, self.track_y,
                          fill=self.RANGE_COLOR, width=5, capstyle=tk.ROUND)
        r = self.HANDLE_R
        self.create_oval(x1 - r, self.track_y - r, x1 + r, self.track_y + r,
                          fill=self.START_COLOR, outline="white", width=2)
        self.create_oval(x2 - r, self.track_y - r, x2 + r, self.track_y + r,
                          fill=self.END_COLOR, outline="white", width=2)

    def _on_resize(self, event):
        if event.width > 10:
            self.w = event.width
            self._draw()

    # -- interaction -----------------------------------------------------
    def _on_press(self, event):
        x1 = self._val_to_x(self.start_val)
        x2 = self._val_to_x(self.end_val)
        self._dragging = "start" if abs(event.x - x1) <= abs(event.x - x2) else "end"
        self._on_drag(event)

    def _on_drag(self, event):
        if not self._dragging:
            return
        val = self._x_to_val(event.x)
        if self._dragging == "start":
            self.start_val = max(self.min_val, min(val, self.end_val))
        else:
            self.end_val = min(self.max_val, max(val, self.start_val))
        self._draw()
        if self.on_change:
            self.on_change(self.start_val, self.end_val)

    def _on_release(self, event):
        self._dragging = None

    # -- public API -------------------------------------------------------
    def set_range(self, min_val, max_val):
        self.min_val = min_val
        self.max_val = max_val if max_val > min_val else min_val + 1.0
        self.start_val = self.min_val
        self.end_val = self.max_val
        self._draw()

    def set_values(self, start, end, notify=False):
        start = max(self.min_val, min(start, self.max_val))
        end = max(self.min_val, min(end, self.max_val))
        if start > end:
            start, end = end, start
        self.start_val = start
        self.end_val = end
        self._draw()
        if notify and self.on_change:
            self.on_change(self.start_val, self.end_val)


# --------------------------------------------------------------------------- #
# Main Application
# --------------------------------------------------------------------------- #

class FD2ProgressInterceptor:
    """Intercepts OS-level stderr (file descriptor 2) to capture real-time ffmpeg progress lines."""
    def __init__(self, clip_duration, queue_put):
        self.clip_duration = clip_duration
        self.queue_put = queue_put
        self.running = False
        self.old_fd2 = None
        self.pipe_r = None
        self.pipe_w = None

    def start(self):
        try:
            self.old_fd2 = os.dup(2)
            self.pipe_r, self.pipe_w = os.pipe()
            os.dup2(self.pipe_w, 2)
            os.close(self.pipe_w)
            self.running = True
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception:
            pass

    def stop(self):
        self.running = False
        if self.old_fd2 is not None:
            try:
                os.dup2(self.old_fd2, 2)
                os.close(self.old_fd2)
            except Exception:
                pass
            self.old_fd2 = None

    def _reader(self):
        last_push = 0.0
        try:
            file_r = os.fdopen(self.pipe_r, "r", errors="ignore")
            while self.running:
                line = file_r.readline()
                if not line:
                    break
                if self.old_fd2 is not None:
                    try:
                        os.write(self.old_fd2, line.encode("utf-8", errors="ignore"))
                    except Exception:
                        pass

                m_time = re.search(r"time=(\d+:\d+:\d+(?:\.\d+)?|\d+:\d+(?:\.\d+)?)", line)
                if m_time and self.clip_duration > 0:
                    time_str = m_time.group(1)
                    parts = [float(p) for p in time_str.split(":")]
                    sec = parts[0]*3600 + parts[1]*60 + parts[2] if len(parts) == 3 else parts[0]*60 + parts[1]
                    pct = min(100.0, (sec / self.clip_duration) * 100)
                    now = time.monotonic()
                    if now - last_push >= 0.1:
                        last_push = now
                        m_speed = re.search(r"speed=\s*([\d\.\w]+)", line)
                        speed = m_speed.group(1) if m_speed else ""
                        status_text = f"Processing/Trimming — {pct:.0f}%"
                        if speed:
                            status_text += f"  speed={speed}"
                        self.queue_put(("progress", pct))
                        self.queue_put(("status", status_text))
        except Exception:
            pass


class AppLogger:
    """Custom logger to capture real-time progress from yt-dlp and ffmpeg subprocesses."""
    def __init__(self, app):
        self.app = app
        self.last_push = 0.0

    def debug(self, msg):
        try:
            now = time.monotonic()
            # 1. Parse yt-dlp percentage logs like "[download]  45.2% of ..."
            m_pct = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", msg)
            if m_pct:
                pct = float(m_pct.group(1))
                if now - self.last_push >= 0.15:
                    self.last_push = now
                    self.app.msg_queue.put(("progress", min(pct, 100.0)))
                    m_speed = re.search(r"at\s+([\d\.\w/]+)", msg)
                    m_eta = re.search(r"ETA\s+([\d:]+)", msg)
                    speed_str = m_speed.group(1) if m_speed else ""
                    eta_str = m_eta.group(1) if m_eta else ""
                    status_text = f"Downloading — {pct:.0f}%"
                    if speed_str:
                        status_text += f"  speed={speed_str}"
                    if eta_str:
                        status_text += f"  eta={eta_str}"
                    self.app.msg_queue.put(("status", status_text))
                return

            # 2. Parse ffmpeg time progress logs like "time=00:01:23.45"
            m_time = re.search(r"time=(\d+:\d+:\d+(?:\.\d+)?|\d+:\d+(?:\.\d+)?)", msg)
            if m_time and self.app._current_clip_duration > 0:
                time_str = m_time.group(1)
                parts = [float(p) for p in time_str.split(":")]
                sec = parts[0]*3600 + parts[1]*60 + parts[2] if len(parts) == 3 else parts[0]*60 + parts[1]
                pct = min(100.0, (sec / self.app._current_clip_duration) * 100)
                if now - self.last_push >= 0.15:
                    self.last_push = now
                    self.app.msg_queue.put(("progress", pct))
                    m_speed = re.search(r"speed=\s*([\d\.\w]+)", msg)
                    speed_str = m_speed.group(1) if m_speed else ""
                    status_text = f"Processing/Trimming — {pct:.0f}%"
                    if speed_str:
                        status_text += f"  speed={speed_str}"
                    self.app.msg_queue.put(("status", status_text))
        except Exception:
            pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.app._log(f"yt-dlp: {msg}", "ERROR")


class YTDownloaderApp:
    BG = "#1e1e1e"
    PANEL_BG = "#252526"
    FG = "#e8e8e8"
    ACCENT = "#5aa9e6"
    SUCCESS = "#39d353"
    ERROR = "#ff6b6b"
    INFO = "#c9c9c9"

    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader — yt-dlp + ffmpeg")
        self.root.geometry("980x800")
        self.root.minsize(880, 720)
        self.root.configure(bg=self.BG)

        self.msg_queue = queue.Queue()
        self.video_info = None
        self.duration = 0.0
        self.audio_formats = []
        self.video_formats = []
        self.all_video_formats = []
        self.selected_format = None       # dict
        self.selected_kind = None         # 'audio' | 'video'
        self.output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self._syncing_slider = False
        self._download_thread = None
        self._last_status_push = 0.0
        self._current_clip_duration = 0.0

        self._check_ffmpeg()
        self._build_style()
        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def _check_ffmpeg(self):
        self.ffmpeg_available = shutil.which("ffmpeg") is not None

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL_BG)
        style.configure("TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=self.PANEL_BG, foreground=self.FG, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Accent.TButton", foreground="white", background=self.ACCENT)
        style.map("Accent.TButton", background=[("active", "#4a8fc2")])
        style.configure("TEntry", fieldbackground="#333333", foreground=self.FG)
        style.configure("Treeview", background="#2a2a2a", fieldbackground="#2a2a2a",
                         foreground=self.FG, rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", self.ACCENT)])
        style.configure("TProgressbar", troughcolor="#333333", background=self.ACCENT)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        # 1. URL input row --------------------------------------------------
        url_frame = ttk.Frame(self.root)
        url_frame.pack(fill="x", **pad)
        ttk.Label(url_frame, text="YouTube URL:", style="Header.TLabel").pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.url_entry.bind("<Return>", lambda e: self.fetch_formats())

        self.fetch_btn = ttk.Button(url_frame, text="Fetch Formats", style="Accent.TButton",
                                     command=self.fetch_formats)
        self.fetch_btn.pack(side="left")

        # Video title / duration display
        self.title_var = tk.StringVar(value="No video loaded.")
        ttk.Label(self.root, textvariable=self.title_var, wraplength=920).pack(fill="x", padx=14)

        # 2. Format lists (audio left / video right) ------------------------
        fmt_frame = ttk.Frame(self.root)
        fmt_frame.pack(fill="both", expand=False, **pad)
        fmt_frame.columnconfigure(0, weight=1)
        fmt_frame.columnconfigure(1, weight=1)

        audio_box = ttk.Frame(fmt_frame, style="Panel.TFrame")
        audio_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(audio_box, text="🎵 Audio Formats", style="Panel.TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=6)
        self.audio_tree = ttk.Treeview(
            audio_box, columns=("abr", "ext", "size", "note"), show="headings", height=8, selectmode="browse")
        for col, text, w in (("abr", "Bitrate", 80), ("ext", "Ext", 60),
                             ("size", "Size", 90), ("note", "Info", 140)):
            self.audio_tree.heading(col, text=text)
            self.audio_tree.column(col, width=w, anchor="center")
        self.audio_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.audio_tree.bind("<<TreeviewSelect>>", self._on_audio_select)

        video_box = ttk.Frame(fmt_frame, style="Panel.TFrame")
        video_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        video_header = ttk.Frame(video_box, style="Panel.TFrame")
        video_header.pack(fill="x", padx=8, pady=6)
        ttk.Label(video_header, text="🎬 Video Formats", style="Panel.TLabel",
                  font=("Segoe UI", 11, "bold")).pack(side="left")
        self.show_all_variants_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(video_header, text="Show all codec variants",
                         variable=self.show_all_variants_var,
                         command=self._refresh_video_tree).pack(side="right")
        self.video_tree = ttk.Treeview(
            video_box, columns=("res", "codec", "fps", "ext", "size", "note"),
            show="headings", height=8, selectmode="browse")
        for col, text, w in (("res", "Resolution", 85), ("codec", "Codec", 65), ("fps", "FPS", 45),
                             ("ext", "Ext", 55), ("size", "Size", 85), ("note", "Info", 110)):
            self.video_tree.heading(col, text=text)
            self.video_tree.column(col, width=w, anchor="center")
        self.video_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.video_tree.bind("<<TreeviewSelect>>", self._on_video_select)

        self.selection_label_var = tk.StringVar(value="No format selected.")
        ttk.Label(self.root, textvariable=self.selection_label_var,
                  foreground=self.ACCENT, background=self.BG).pack(fill="x", padx=14, pady=(0, 4))

        # 3. Crop section -----------------------------------------------------
        crop_box = ttk.Frame(self.root, style="Panel.TFrame")
        crop_box.pack(fill="x", **pad)
        ttk.Label(crop_box, text="✂ Crop Range",
                  style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 4))

        crop_controls = ttk.Frame(crop_box, style="Panel.TFrame")
        crop_controls.pack(fill="x", padx=8, pady=(0, 10))

        self.start_var = tk.StringVar(value="00:00")
        self.end_var = tk.StringVar(value="00:00")

        self.start_entry = ttk.Entry(crop_controls, textvariable=self.start_var, width=10, justify="center")
        self.start_entry.pack(side="left")
        self.start_entry.bind("<Return>", self._on_start_entry_change)
        self.start_entry.bind("<FocusOut>", self._on_start_entry_change)

        self.range_slider = RangeSlider(crop_controls, width=560, height=36, min_val=0, max_val=100,
                                         on_change=self._on_slider_change)
        self.range_slider.pack(side="left", fill="x", expand=True, padx=10)

        self.end_entry = ttk.Entry(crop_controls, textvariable=self.end_var, width=10, justify="center")
        self.end_entry.pack(side="left")
        self.end_entry.bind("<Return>", self._on_end_entry_change)
        self.end_entry.bind("<FocusOut>", self._on_end_entry_change)

        self.crop_duration_var = tk.StringVar(value="Selected clip length: 00:00")
        ttk.Label(crop_box, textvariable=self.crop_duration_var, style="Panel.TLabel").pack(
            anchor="w", padx=8, pady=(0, 8))

        # 4. Output folder + Download row -------------------------------------
        out_frame = ttk.Frame(self.root)
        out_frame.pack(fill="x", **pad)
        ttk.Label(out_frame, text="Save to:").pack(side="left")
        self.out_dir_var = tk.StringVar(value=self.output_dir)
        ttk.Entry(out_frame, textvariable=self.out_dir_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8)
        ttk.Button(out_frame, text="Browse…", command=self._choose_output_dir).pack(side="left")

        dl_frame = ttk.Frame(self.root)
        dl_frame.pack(fill="x", **pad)
        self.download_btn = ttk.Button(dl_frame, text="⬇ Download", style="Accent.TButton",
                                        command=self.start_download)
        self.download_btn.pack(side="left")

        self.progress = ttk.Progressbar(dl_frame, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=12)
        self.progress_pct_var = tk.StringVar(value="0%")
        ttk.Label(dl_frame, textvariable=self.progress_pct_var, width=6).pack(side="left")

        # Live status line (speed/eta/postprocessing) - updated far more often
        # than the log, so it must NOT go through the log panel.
        self.status_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.status_var, foreground="#9a9a9a").pack(
            fill="x", padx=14, pady=(0, 4))

        # 5. Log panel ----------------------------------------------------------
        log_frame = ttk.Frame(self.root, style="Panel.TFrame")
        log_frame.pack(fill="both", expand=True, **pad)
        ttk.Label(log_frame, text="📋 Logs", style="Panel.TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=6)

        log_container = ttk.Frame(log_frame, style="Panel.TFrame")
        log_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_text = tk.Text(log_container, height=10, bg="#1a1a1a", fg=self.INFO,
                                 insertbackground=self.FG, wrap="word", font=("Consolas", 9), state="disabled")
        log_scroll = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("INFO", foreground=self.INFO)
        self.log_text.tag_configure("SUCCESS", foreground=self.SUCCESS)
        self.log_text.tag_configure("ERROR", foreground=self.ERROR)
        self.log_text.tag_configure("TIME", foreground="#888888")

        if not self.ffmpeg_available:
            self._log("ffmpeg was not found on PATH. Install ffmpeg or cropping/merging will fail.", "ERROR")
        self._log("Ready. Paste a YouTube URL and click 'Fetch Formats'.", "INFO")

    # ------------------------------------------------------------------ #
    # Logging (thread-safe via queue)
    # ------------------------------------------------------------------ #
    def _log(self, message, level="INFO"):
        self.msg_queue.put(("log", message, level))

    def _write_log(self, message, level):
        self.log_text.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] ", "TIME")
        self.log_text.insert("end", f"{level}: {message}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, message, level = item
                    self._write_log(message, level)
                elif kind == "progress":
                    _, pct = item
                    try:
                        if str(self.progress.cget("mode")) != "determinate":
                            self.progress.stop()
                            self.progress.configure(mode="determinate")
                    except Exception:
                        pass
                    self.progress["value"] = pct
                    self.progress_pct_var.set(f"{pct:.0f}%")
                elif kind == "status":
                    _, text = item
                    self.status_var.set(text)
                elif kind == "postprocessing_start":
                    self.status_var.set("Post-processing with ffmpeg (cropping/merging)… this can take a while")
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(12)
                elif kind == "postprocessing_done":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress["value"] = 100
                    self.progress_pct_var.set("100%")
                    self.status_var.set("Post-processing complete.")
                elif kind == "formats_ready":
                    _, info = item
                    self._populate_formats(info)
                elif kind == "download_done":
                    _, ok, path_or_err = item
                    self._on_download_finished(ok, path_or_err)
                elif kind == "fetch_error":
                    _, err = item
                    self.fetch_btn.configure(state="normal")
                    messagebox.showerror("Fetch failed", err)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------------ #
    # Fetch formats
    # ------------------------------------------------------------------ #
    def fetch_formats(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube URL first.")
            return
        if not re.match(r"^https?://", url):
            messagebox.showwarning("Invalid URL", "URL must start with http:// or https://")
            return

        self.fetch_btn.configure(state="disabled")
        self.title_var.set("Fetching video info…")
        self._log(f"Fetching formats for: {url}", "INFO")

        thread = threading.Thread(target=self._fetch_formats_worker, args=(url,), daemon=True)
        thread.start()

    def _fetch_formats_worker(self, url):
        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info is None:
                raise RuntimeError("Could not retrieve video information.")
            self.msg_queue.put(("formats_ready", info))
            self._log("Formats fetched successfully.", "SUCCESS")
        except yt_dlp.utils.DownloadError as e:
            self.msg_queue.put(("fetch_error", f"yt-dlp could not process this URL:\n{e}"))
            self._log(f"Fetch failed: {e}", "ERROR")
        except Exception as e:
            self.msg_queue.put(("fetch_error", f"Unexpected error:\n{e}"))
            self._log(f"Unexpected error while fetching: {e}\n{traceback.format_exc()}", "ERROR")
        finally:
            self.root.after(0, lambda: self.fetch_btn.configure(state="normal"))

    # Standard resolution "buckets" YouTube's own quality menu uses. Real
    # DASH encodes are often a few px off (e.g. 1072 instead of 1080) - in
    # simplified mode we snap to the nearest of these for the label.
    _STANDARD_HEIGHTS = [144, 240, 360, 480, 720, 1080, 1440, 2160, 4320]

    @staticmethod
    def _codec_label(vcodec):
        if not vcodec or vcodec == "none":
            return "-"
        vcodec = vcodec.lower()
        if vcodec.startswith("avc1") or vcodec.startswith("h264"):
            return "H.264"
        if vcodec.startswith(("vp9", "vp09")):
            return "VP9"
        if vcodec.startswith("av01"):
            return "AV1"
        if vcodec.startswith("vp8"):
            return "VP8"
        return vcodec.split(".")[0].upper()

    def _estimate_filesize(self, f):
        """Best-effort file size. Real 'filesize'/'filesize_approx' fields
        are often missing for some codec variants even when a bitrate is
        known, so fall back to estimating from bitrate * duration ourselves.
        Returns (size_in_bytes_or_None, is_estimate)."""
        size = f.get("filesize") or f.get("filesize_approx")
        if size:
            return size, False
        tbr = f.get("tbr")  # kbit/s
        if tbr and self.duration:
            estimated = tbr * 1000 / 8 * self.duration
            return estimated, True
        return None, False

    def _populate_formats(self, info):
        self.video_info = info
        self.duration = float(info.get("duration") or 0)
        title = info.get("title", "Unknown title")
        self.title_var.set(f"{title}   (Duration: {format_seconds(self.duration)})")

        for row in self.audio_tree.get_children():
            self.audio_tree.delete(row)
        self.audio_formats.clear()
        self.all_video_formats.clear()
        self.selected_format = None
        self.selected_kind = None
        self.selection_label_var.set("No format selected.")

        formats = info.get("formats") or []
        for f in formats:
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            ext = f.get("ext", "?")
            fmt_id = f.get("format_id")

            if vcodec == "none" and acodec != "none":
                abr = f.get("abr")
                abr_txt = f"{int(abr)}kbps" if abr else "?"
                note = f.get("format_note", "") or acodec
                size, is_estimate = self._estimate_filesize(f)
                size_txt = ("~" if is_estimate else "") + human_filesize(size)
                self.audio_tree.insert("", "end", iid=fmt_id,
                                        values=(abr_txt, ext, size_txt, note))
                self.audio_formats.append(f)
            elif vcodec != "none" and f.get("height"):
                self.all_video_formats.append(f)

        self._sort_tree(self.audio_tree, "abr")
        self._refresh_video_tree()

        # reset crop slider to full duration
        self.range_slider.set_range(0, max(self.duration, 1))
        self.range_slider.set_values(0, self.duration)
        self.start_var.set(format_seconds(0))
        self.end_var.set(format_seconds(self.duration))
        self._update_crop_label(0, self.duration)

    def _refresh_video_tree(self):
        """Rebuild the video format list, either as the full raw set of
        codec variants, or a YouTube-style simplified list with just the
        best format per standard resolution bucket."""
        for row in self.video_tree.get_children():
            self.video_tree.delete(row)

        if self.show_all_variants_var.get():
            display_list = list(self.all_video_formats)
        else:
            buckets = {}
            for f in self.all_video_formats:
                height = f.get("height")
                bucket = min(self._STANDARD_HEIGHTS, key=lambda h: abs(h - height))
                size, _ = self._estimate_filesize(f)
                proto = f.get("protocol", "")
                # Prefer direct HTTP/HTTPS DASH streams over HLS (m3u8_native) playlists
                proto_score = 2 if proto.startswith("http") else (1 if "m3u8" in proto else 0)
                score = (proto_score, 1 if size else 0, f.get("tbr") or 0)
                if bucket not in buckets or score > buckets[bucket][0]:
                    buckets[bucket] = (score, f)
            display_list = [f for _, f in buckets.values()]

        self.video_formats = display_list

        for f in display_list:
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            ext = f.get("ext", "?")
            fmt_id = f.get("format_id")
            height = f.get("height")
            fps = f.get("fps") or "-"
            has_audio = "with audio" if acodec != "none" else "video-only"
            size, is_estimate = self._estimate_filesize(f)
            size_txt = ("~" if is_estimate else "") + human_filesize(size)

            if self.show_all_variants_var.get():
                res_txt = f"{height}p" if height else "?"
            else:
                bucket = min(self._STANDARD_HEIGHTS, key=lambda h: abs(h - height))
                res_txt = f"{bucket}p"
                if height != bucket:
                    has_audio += f" ({height}px)"

            self.video_tree.insert("", "end", iid=fmt_id,
                                    values=(res_txt, self._codec_label(vcodec), fps, ext,
                                            size_txt, has_audio))

        self._sort_tree(self.video_tree, "res")

    @staticmethod
    def _sort_tree(tree, key_col):
        def sort_key(iid):
            val = tree.set(iid, key_col)
            digits = re.sub(r"[^\d.]", "", val)
            try:
                return -float(digits) if digits else 0
            except ValueError:
                return 0
        items = sorted(tree.get_children(""), key=sort_key)
        for idx, iid in enumerate(items):
            tree.move(iid, "", idx)

    # ------------------------------------------------------------------ #
    # Format selection (mutually exclusive)
    # ------------------------------------------------------------------ #
    def _on_audio_select(self, event=None):
        sel = self.audio_tree.selection()
        if not sel:
            return
        self.video_tree.selection_remove(self.video_tree.selection())
        fmt_id = sel[0]
        fmt = next((f for f in self.audio_formats if f.get("format_id") == fmt_id), None)
        self.selected_format = fmt
        self.selected_kind = "audio"
        abr = fmt.get("abr")
        label = f"Selected AUDIO format: {fmt_id} ({int(abr)}kbps)" if abr else f"Selected AUDIO format: {fmt_id}"
        self.selection_label_var.set(label)
        self._log(label, "INFO")

    def _on_video_select(self, event=None):
        sel = self.video_tree.selection()
        if not sel:
            return
        self.audio_tree.selection_remove(self.audio_tree.selection())
        fmt_id = sel[0]
        fmt = next((f for f in self.video_formats if f.get("format_id") == fmt_id), None)
        self.selected_format = fmt
        self.selected_kind = "video"
        height = fmt.get("height")
        label = f"Selected VIDEO format: {fmt_id} ({height}p)" if height else f"Selected VIDEO format: {fmt_id}"
        self.selection_label_var.set(label)
        self._log(label, "INFO")

    # ------------------------------------------------------------------ #
    # Crop sync: slider <-> entries
    # ------------------------------------------------------------------ #
    def _update_crop_label(self, start, end):
        self.crop_duration_var.set(f"Selected clip length: {format_seconds(max(0, end - start))} "
                                    f"(from {format_seconds(start)} to {format_seconds(end)})")

    def _on_slider_change(self, start, end):
        if self._syncing_slider:
            return
        self._syncing_slider = True
        self.start_var.set(format_seconds(start))
        self.end_var.set(format_seconds(end))
        self._update_crop_label(start, end)
        self._syncing_slider = False

    def _on_start_entry_change(self, event=None):
        seconds = parse_time_to_seconds(self.start_var.get())
        if seconds is None:
            messagebox.showwarning("Invalid time", "Start time must look like MM:SS or HH:MM:SS.")
            self.start_var.set(format_seconds(self.range_slider.start_val))
            return
        seconds = max(0, min(seconds, self.duration))
        self._syncing_slider = True
        self.range_slider.set_values(seconds, max(seconds, self.range_slider.end_val))
        self.start_var.set(format_seconds(seconds))
        self._update_crop_label(self.range_slider.start_val, self.range_slider.end_val)
        self._syncing_slider = False

    def _on_end_entry_change(self, event=None):
        seconds = parse_time_to_seconds(self.end_var.get())
        if seconds is None:
            messagebox.showwarning("Invalid time", "End time must look like MM:SS or HH:MM:SS.")
            self.end_var.set(format_seconds(self.range_slider.end_val))
            return
        seconds = max(0, min(seconds, self.duration))
        self._syncing_slider = True
        self.range_slider.set_values(min(seconds, self.range_slider.start_val), seconds)
        self.end_var.set(format_seconds(seconds))
        self._update_crop_label(self.range_slider.start_val, self.range_slider.end_val)
        self._syncing_slider = False

    # ------------------------------------------------------------------ #
    # Output directory
    # ------------------------------------------------------------------ #
    def _choose_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir)
        if chosen:
            self.output_dir = chosen
            self.out_dir_var.set(chosen)
            self._log(f"Output folder set to: {chosen}", "INFO")

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #
    def start_download(self):
        if self._download_thread and self._download_thread.is_alive():
            messagebox.showinfo("Busy", "A download is already in progress.")
            return
        if not self.video_info:
            messagebox.showwarning("No video", "Fetch formats before downloading.")
            return
        if not self.selected_format:
            messagebox.showwarning("No format selected", "Please select an audio or video format.")
            return
        if not self.ffmpeg_available:
            messagebox.showerror("ffmpeg missing", "ffmpeg was not found on PATH. Install it and try again.")
            return

        start = self.range_slider.start_val
        end = self.range_slider.end_val
        if end <= start:
            messagebox.showwarning("Invalid crop range", "End time must be after start time.")
            return

        url = self.url_var.get().strip()
        os.makedirs(self.output_dir, exist_ok=True)

        self.download_btn.configure(state="disabled")
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0
        self.progress_pct_var.set("0%")
        self.status_var.set("")
        self._last_status_push = 0.0
        self._log("Starting download…", "INFO")

        self._download_thread = threading.Thread(
            target=self._download_worker, args=(url, start, end), daemon=True)
        self._download_thread.start()

    def _progress_hook(self, d):
        # NOTE: yt-dlp can call this dozens of times per second. Never push a
        # "log" message on every call - the log panel would flood the queue
        # and the GUI thread would appear to freeze/lag until the backlog
        # drains (which looks exactly like "progress bar only moves at the
        # end"). Both the status line AND the progress value itself are
        # throttled here, and the whole body is guarded so a hook-side
        # exception (e.g. an unexpected/missing field) can never abort the
        # download silently.
        try:
            status = d.get("status")
            now = time.monotonic()

            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0) or 0

                pct = None
                if total > 0:
                    pct = downloaded / total * 100
                else:
                    # Fragmented/DASH streams often don't expose total_bytes
                    # until later (or never) - fall back to fragment counts.
                    frag_idx = d.get("fragment_index")
                    frag_cnt = d.get("fragment_count")
                    if frag_idx is not None and frag_cnt:
                        pct = frag_idx / frag_cnt * 100

                throttled = (now - self._last_status_push) < 0.2
                if pct is not None and not throttled:
                    self.msg_queue.put(("progress", min(pct, 100)))

                if not throttled:
                    self._last_status_push = now
                    speed = d.get("speed")
                    eta = d.get("eta")
                    speed_txt = human_filesize(speed) + "/s" if speed else "?"
                    eta_txt = f"{eta}s" if eta is not None else "?"
                    which = (d.get("info_dict") or {}).get("format_id", "")
                    if pct is not None:
                        self.msg_queue.put(("status",
                                             f"Downloading {which} — {pct:.0f}%  speed={speed_txt}  eta={eta_txt}"))
                    else:
                        self.msg_queue.put(("status", f"Downloading {which} — speed={speed_txt}  eta={eta_txt}"))

            elif status == "finished":
                self.msg_queue.put(("progress", 100))
                self.msg_queue.put(("status", "Stream downloaded. Preparing post-processing…"))
                self._log("Download stream finished.", "INFO")
            elif status == "error":
                self._log("yt-dlp reported an error during download.", "ERROR")
        except Exception as e:
            # Never let a bug in progress reporting abort the actual download.
            self._log(f"(progress display glitch, download continues): {e}", "INFO")

    def _postprocessor_hook(self, d):
        # ffmpeg-based steps (cropping to keyframes, merging audio+video,
        # remuxing) don't report byte progress at all, so this is the ONLY
        # signal we get during that phase. Switch the bar to indeterminate
        # so it's clear work is still happening instead of looking stalled.
        try:
            status = d.get("status")
            name = d.get("postprocessor", "ffmpeg")
            if status == "started":
                self.msg_queue.put(("postprocessing_start",))
                self._log(f"Post-processing started: {name}", "INFO")
            elif status == "finished":
                self.msg_queue.put(("postprocessing_done",))
                self._log(f"Post-processing finished: {name}", "SUCCESS")
        except Exception as e:
            self._log(f"(post-processing display glitch, continues): {e}", "INFO")

    def _download_worker(self, url, start, end):
        full_range = (start <= 0.01 and end >= self.duration - 0.01)
        clip_dur = (end - start) if not full_range else self.duration
        self._current_clip_duration = clip_dur

        interceptor = FD2ProgressInterceptor(clip_dur, self.msg_queue.put)
        interceptor.start()

        try:
            fmt = self.selected_format
            fmt_id = fmt.get("format_id")

            if self.selected_kind == "audio":
                format_str = fmt_id
            else:
                vcodec = fmt.get("vcodec", "none")
                acodec = fmt.get("acodec", "none")
                if acodec == "none" and vcodec != "none":
                    # For H.264 (avc1) video-only streams, prefer M4A (AAC) audio for MP4 container compatibility
                    if "avc1" in vcodec.lower() or "h264" in vcodec.lower():
                        format_str = f"{fmt_id}+bestaudio[ext=m4a]/bestaudio/best"
                    else:
                        format_str = f"{fmt_id}+bestaudio/best"
                    self._log("Selected video has no audio track; merging with audio automatically.", "INFO")
                else:
                    format_str = fmt_id

            title = sanitize_filename(self.video_info.get("title", "video"))
            outtmpl = os.path.join(self.output_dir, f"{title}.%(ext)s")

            ydl_opts = {
                "format": format_str,
                "outtmpl": outtmpl,
                "progress_hooks": [self._progress_hook],
                "postprocessor_hooks": [self._postprocessor_hook],
                "logger": AppLogger(self),
                "no_warnings": True,
                "merge_output_format": "mp4" if self.selected_kind == "video" else None,
                "noplaylist": True,
            }
            if not full_range:
                ydl_opts["download_ranges"] = download_range_func(None, [(start, end)])
                self._log(f"Cropping to range {format_seconds(start)} - {format_seconds(end)}", "INFO")
            else:
                self._log("Full media selected (no crop applied).", "INFO")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            self.msg_queue.put(("download_done", True, self.output_dir))
        except yt_dlp.utils.DownloadError as e:
            self.msg_queue.put(("download_done", False, str(e)))
        except Exception as e:
            self.msg_queue.put(("download_done", False, f"{e}\n{traceback.format_exc()}"))
        finally:
            interceptor.stop()

    def _on_download_finished(self, ok, path_or_err):
        self.download_btn.configure(state="normal")
        # Defensive cleanup: make sure the bar isn't left spinning in
        # indeterminate mode if a postprocessor "finished" event never fired.
        self.progress.stop()
        self.progress.configure(mode="determinate")
        if ok:
            self.progress["value"] = 100
            self.progress_pct_var.set("100%")
            self.status_var.set("Done.")
            self._log(f"Download complete! Saved in: {path_or_err}", "SUCCESS")
            messagebox.showinfo("Done", f"Download complete!\nSaved in:\n{path_or_err}")
        else:
            self.status_var.set("Failed.")
            self._log(f"Download failed: {path_or_err}", "ERROR")
            messagebox.showerror("Download failed", path_or_err)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main():
    root = tk.Tk()
    app = YTDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
