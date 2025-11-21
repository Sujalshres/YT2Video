import sys
import os
import subprocess
from PyQt6 import QtWidgets, QtCore, QtGui
from yt_dlp import YoutubeDL

class RangeSlider(QtWidgets.QWidget):
    """
    Custom dual-handle range slider.
    Emits valueChanged with (start_value, end_value).
    """

    valueChanged = QtCore.pyqtSignal(int, int)

    def __init__(self, min_val=0, max_val=100, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(50)
        self.min_val = min_val
        self.max_val = max_val
        self.start_pos = min_val
        self.end_pos = max_val
        self.moving_start = False
        self.moving_end = False
        self.handle_radius = 10
        self.bar_height = 5

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        rect = self.rect()
        # Draw background bar
        bar_rect = QtCore.QRect(
            self.handle_radius,
            rect.center().y() - self.bar_height // 2,
            rect.width() - 2 * self.handle_radius,
            self.bar_height
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(200, 200, 200))
        painter.drawRect(bar_rect)

        # Draw selection bar
        start_x = self.value_to_pos(self.start_pos)
        end_x = self.value_to_pos(self.end_pos)
        selection_rect = QtCore.QRect(
            start_x,
            rect.center().y() - self.bar_height // 2,
            end_x - start_x,
            self.bar_height
        )
        painter.setBrush(QtGui.QColor(100, 180, 255))
        painter.drawRect(selection_rect)

        # Draw handles
        painter.setBrush(QtGui.QColor(50, 120, 215))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(QtCore.QPoint(start_x, rect.center().y()), self.handle_radius, self.handle_radius)
        painter.drawEllipse(QtCore.QPoint(end_x, rect.center().y()), self.handle_radius, self.handle_radius)

    def value_to_pos(self, val):
        """Convert value in [min_val,max_val] to x position in pixels."""
        span = self.max_val - self.min_val
        width = self.width() - 2 * self.handle_radius
        rel_pos = (val - self.min_val) / span if span > 0 else 0
        return int(self.handle_radius + rel_pos * width)

    def pos_to_value(self, x):
        """Convert x position in pixels to value."""
        x = max(self.handle_radius, min(x, self.width() - self.handle_radius))
        width = self.width() - 2 * self.handle_radius
        rel_pos = (x - self.handle_radius) / width if width > 0 else 0
        span = self.max_val - self.min_val
        val = int(self.min_val + rel_pos * span)
        return val

    def mousePressEvent(self, event):
        x = event.position().x()
        start_x = self.value_to_pos(self.start_pos)
        end_x = self.value_to_pos(self.end_pos)
        if abs(x - start_x) <= self.handle_radius:
            self.moving_start = True
        elif abs(x - end_x) <= self.handle_radius:
            self.moving_end = True

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self.moving_start:
            val = self.pos_to_value(x)
            if val < self.min_val:
                val = self.min_val
            if val > self.end_pos:
                val = self.end_pos
            if val != self.start_pos:
                self.start_pos = val
                self.valueChanged.emit(self.start_pos, self.end_pos)
                self.update()
        elif self.moving_end:
            val = self.pos_to_value(x)
            if val > self.max_val:
                val = self.max_val
            if val < self.start_pos:
                val = self.start_pos
            if val != self.end_pos:
                self.end_pos = val
                self.valueChanged.emit(self.start_pos, self.end_pos)
                self.update()

    def mouseReleaseEvent(self, event):
        self.moving_start = False
        self.moving_end = False

    def setRange(self, min_val, max_val):
        self.min_val = min_val
        self.max_val = max_val
        if self.start_pos < min_val or self.start_pos > max_val:
            self.start_pos = min_val
        if self.end_pos > max_val or self.end_pos < min_val:
            self.end_pos = max_val
        self.update()

    def setValues(self, start, end):
        if start < self.min_val:
            start = self.min_val
        if end > self.max_val:
            end = self.max_val
        if start > end:
            start, end = end, start
        self.start_pos = start
        self.end_pos = end
        self.valueChanged.emit(self.start_pos, self.end_pos)
        self.update()

    def values(self):
        return self.start_pos, self.end_pos


def seconds_to_hms(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    else:
        return f"{m}:{s:02d}"

def hms_to_seconds(time_str):
    parts = time_str.strip().split(':')
    try:
        parts = [int(p) for p in parts]
    except:
        return None
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    elif len(parts) == 2:
        return parts[0]*60 + parts[1]
    elif len(parts) == 1:
        return parts[0]
    else:
        return None


class WorkerFetchInfo(QtCore.QThread):
    fetched = QtCore.pyqtSignal(object)  # emits video_info dict or None on error
    error = QtCore.pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'nocheckcertificate': True,
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.fetched.emit(info)
        except Exception as e:
            self.error.emit(str(e))


class WorkerDownload(QtCore.QThread):
    progress_percent = QtCore.pyqtSignal(int)  # emits percent int 0-100
    progress_text = QtCore.pyqtSignal(str)  # emits status string updates
    finished = QtCore.pyqtSignal(str)  # emits final saved filename or error message

    def __init__(self, url, format_selector, selected_meta, ffmpeg_path, start_time, end_time, outtmpl):
        """
        selected_meta: dictionary describing chosen format (type: 'audio'|'video', ext, format_id, audio flag)
        format_selector: string to pass to yt-dlp (format id or combo)
        """
        super().__init__()
        self.url = url
        self.format_selector = format_selector
        self.selected_meta = selected_meta
        self.ffmpeg_path = ffmpeg_path
        self.start_time = start_time
        self.end_time = end_time
        self.outtmpl = outtmpl

    def ydl_hook(self, d):
        if d.get('status') == 'downloading':
            percent_raw = d.get('_percent_str', '0.0%').strip()
            try:
                percent = float(percent_raw.strip('%'))
            except:
                percent = 0
            self.progress_percent.emit(int(percent))
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            self.progress_text.emit(f"Downloading... {percent_raw} at {speed}, ETA: {eta}")
        elif d.get('status') == 'finished':
            self.progress_percent.emit(100)
            self.progress_text.emit("Download finished, processing...")

    def run_ffmpeg(self, cmd):
        """Run ffmpeg command and return (returncode, stdout, stderr)."""
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc.returncode, proc.stdout.decode(errors='ignore'), proc.stderr.decode(errors='ignore')
        except Exception as e:
            return 1, '', str(e)

    def run(self):
        # Prepare yt-dlp options
        ydl_opts = {
            'format': self.format_selector,
            'outtmpl': self.outtmpl,
            'ffmpeg_location': os.path.dirname(self.ffmpeg_path) or None,
            'progress_hooks': [self.ydl_hook],
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',  # used if merging video+audio
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                # Download according to selected format
                ydl.download([self.url])
                info_dict = ydl.extract_info(self.url, download=False)
                downloaded_filename = ydl.prepare_filename(info_dict)
                # If yt-dlp merged to mp4 it may already have mp4 extension; ensure we pick file that exists
                if not os.path.exists(downloaded_filename):
                    # try common extensions
                    base = os.path.splitext(downloaded_filename)[0]
                    for ext in (self.selected_meta.get('ext') or '').split(',') + ['mp4','m4a','webm','mp3','mkv','m4v','aac','opus']:
                        candidate = f"{base}.{ext}"
                        if os.path.exists(candidate):
                            downloaded_filename = candidate
                            break
                    else:
                        # fallback: choose any file that matches the base
                        dir_files = os.listdir(os.path.dirname(self.outtmpl) or '.')
                        for fn in dir_files:
                            if fn.startswith(os.path.basename(base)):
                                downloaded_filename = os.path.join(os.path.dirname(self.outtmpl) or '.', fn)
                                break

            # At this point downloaded_filename should point to the downloaded file
            if not os.path.exists(downloaded_filename):
                self.finished.emit(f"Error: downloaded file not found: {downloaded_filename}")
                return

            # If no trimming requested and chosen type is video and no post-processing necessary, optionally convert audio etc.
            # Trimming logic (if requested):
            trimmed_filename = None
            if self.start_time is not None or self.end_time is not None:
                # If both None nothing to do; else compute
                ss = str(self.start_time or 0)
                if self.end_time is not None:
                    duration = self.end_time - (self.start_time or 0)
                    t_arg = str(duration)
                else:
                    t_arg = None

                # Build trimmed filename
                base, ext = os.path.splitext(downloaded_filename)
                trimmed_filename = f"{base}_trimmed{ext}"

                # Try lossless stream copy first (fast and lossless) using -c copy
                cmd = [self.ffmpeg_path, '-hide_banner', '-loglevel', 'error']
                if self.start_time:
                    cmd += ['-ss', ss]
                if t_arg:
                    cmd += ['-t', t_arg]
                cmd += ['-i', downloaded_filename, '-c', 'copy', trimmed_filename]
                self.progress_text.emit(f"Trimming (stream-copy) from {ss} length {t_arg or 'until end'} ...")
                rc, out, err = self.run_ffmpeg(cmd)
                if rc != 0:
                    # fallback: re-encode (still functional)
                    self.progress_text.emit("Stream-copy trimming failed, falling back to re-encode trimming...")
                    cmd = [self.ffmpeg_path, '-hide_banner', '-loglevel', 'error']
                    if self.start_time:
                        cmd += ['-ss', ss]
                    if t_arg:
                        cmd += ['-t', t_arg]
                    cmd += ['-i', downloaded_filename, '-c:a', 'aac', '-c:v', 'libx264', '-strict', '-2', trimmed_filename]
                    rc2, out2, err2 = self.run_ffmpeg(cmd)
                    if rc2 != 0:
                        self.finished.emit(f"FFmpeg trimming error: {err2 or err}")
                        return
                # If stream-copy succeeded or re-encode succeeded, optionally remove the original
                try:
                    os.remove(downloaded_filename)
                except Exception:
                    pass
                working_file = trimmed_filename
            else:
                working_file = downloaded_filename

            final_output = working_file

            # If user selected an audio format, convert to mp3 per your choice
            if self.selected_meta.get('type') == 'audio':
                # target mp3 filename
                base, _ = os.path.splitext(working_file)
                mp3_filename = base + '.mp3'
                # Convert to mp3 (re-encode) at reasonable bitrate
                self.progress_text.emit("Converting to MP3...")
                cmd = [
                    self.ffmpeg_path,
                    '-hide_banner', '-loglevel', 'error',
                    '-i', working_file,
                    '-vn',  # no video
                    '-ab', '192k',
                    '-ar', '44100',
                    mp3_filename
                ]
                rc, out, err = self.run_ffmpeg(cmd)
                if rc != 0:
                    self.finished.emit(f"FFmpeg conversion to mp3 failed: {err}")
                    return
                # Remove intermediate working file if different
                if os.path.exists(mp3_filename):
                    try:
                        if working_file != mp3_filename:
                            os.remove(working_file)
                    except Exception:
                        pass
                    final_output = mp3_filename

            # If user picked a video format that was audio-less and we asked yt-dlp to combine, that was done by yt-dlp.

            # Done
            self.finished.emit(final_output)

        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")


class YouTubeDownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader (Video + Audio)")
        self.setGeometry(300, 300, 800, 500)
        # Try to locate ffmpeg in a packaged folder or fallback to 'ffmpeg' in PATH
        possible_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg', 'ffmpeg.exe')
        if os.path.exists(possible_ffmpeg):
            self.ffmpeg_path = possible_ffmpeg
        else:
            self.ffmpeg_path = 'ffmpeg'  # assume in PATH
        self.video_info = None
        self.formats = []
        self.duration = 0  # in seconds
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        url_label = QtWidgets.QLabel("YouTube URL:")
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter YouTube video URL here...")

        self.fetch_button = QtWidgets.QPushButton("Fetch Video Qualities")
        self.fetch_button.clicked.connect(self.fetch_qualities)

        quality_label = QtWidgets.QLabel("Select Quality (video or audio):")
        self.quality_dropdown = QtWidgets.QComboBox()
        self.quality_dropdown.setEnabled(False)

        # Progress Bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        # Range slider and time inputs
        time_controls_layout = QtWidgets.QHBoxLayout()

        self.start_time_input = QtWidgets.QLineEdit()
        self.start_time_input.setFixedWidth(75)
        self.start_time_input.setPlaceholderText("Start Time")
        self.start_time_input.editingFinished.connect(self.on_start_time_input_changed)

        self.end_time_input = QtWidgets.QLineEdit()
        self.end_time_input.setFixedWidth(75)
        self.end_time_input.setPlaceholderText("End Time")
        self.end_time_input.editingFinished.connect(self.on_end_time_input_changed)

        self.range_slider = RangeSlider()
        self.range_slider.valueChanged.connect(self.on_slider_changed)

        time_controls_layout.addWidget(QtWidgets.QLabel("Start:"))
        time_controls_layout.addWidget(self.start_time_input)
        time_controls_layout.addWidget(self.range_slider)
        time_controls_layout.addWidget(QtWidgets.QLabel("End:"))
        time_controls_layout.addWidget(self.end_time_input)

        self.download_button = QtWidgets.QPushButton("Download")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download_video)

        self.status_box = QtWidgets.QTextEdit()
        self.status_box.setReadOnly(True)
        self.status_box.setMaximumHeight(180)

        layout.addWidget(url_label)
        layout.addWidget(self.url_input)
        layout.addWidget(self.fetch_button)
        layout.addWidget(quality_label)
        layout.addWidget(self.quality_dropdown)
        layout.addWidget(self.progress_bar)
        layout.addLayout(time_controls_layout)
        layout.addWidget(self.download_button)
        layout.addWidget(self.status_box)

        self.setLayout(layout)

    def log(self, message):
        self.status_box.append(message)
        self.status_box.ensureCursorVisible()
        QtCore.QCoreApplication.processEvents()

    def fetch_qualities(self):
        url = self.url_input.text().strip()
        if not url:
            self.log("Please enter a YouTube URL.")
            return
        self.fetch_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress while fetching info
        self.progress_bar.setValue(0)
        self.log("Fetching video information...")
        self.worker_fetch = WorkerFetchInfo(url)
        self.worker_fetch.fetched.connect(self.on_info_fetched)
        self.worker_fetch.error.connect(self.on_fetch_error)
        self.worker_fetch.finished.connect(self.on_fetch_finished)
        self.worker_fetch.start()

    def on_info_fetched(self, info):
        self.video_info = info
        self.duration = int(info.get('duration', 0))
        formats = info.get('formats', [])

        # We'll include audio formats (vcodec == 'none' or acodec != 'none' and no height)
        audio_exts = set(['m4a', 'mp3', 'webm', 'opus', 'aac', 'mka'])
        video_exts = set(['mp4', 'webm', 'mkv', 'm4v'])

        fmt_map = {}  # key by label for uniqueness
        collected = []

        for f in formats:
            fid = f.get('format_id')
            ext = (f.get('ext') or '').lower()
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            height = f.get('height')
            # Determine type
            if vcodec == 'none' or (ext in audio_exts and height is None):
                # audio format
                abr = f.get('abr') or f.get('tbr') or ''
                label = f"{ext} {abr}kbps - audio" if abr else f"{ext} - audio"
                meta = {
                    'format_id': fid,
                    'type': 'audio',
                    'ext': ext,
                    'label': label,
                    'audio': True
                }
                # Add only unique format_id
                collected.append(meta)
            else:
                # video format
                res = f.get('format_note') or f.get('resolution') or (str(f.get('height')) + 'p' if f.get('height') else '')
                audio_present = (acodec != 'none')
                label = f"{res} - video" if res else f"{ext} - video"
                meta = {
                    'format_id': fid,
                    'type': 'video',
                    'ext': ext,
                    'label': label,
                    'audio': audio_present
                }
                collected.append(meta)

        # Remove duplicates (by format_id) keeping first occurrence
        unique = {}
        deduped = []
        for m in collected:
            if m['format_id'] not in unique:
                unique[m['format_id']] = True
                deduped.append(m)

        # Sort: prefer higher resolution videos first, then audio (no strict ordering)
        def sort_key(m):
            if m['type'] == 'video':
                # extract digits from label for resolution
                import re
                digits = re.findall(r'(\d{2,4})p', m['label'])
                if digits:
                    return (-int(digits[0]), 0)
                else:
                    return (0, 0)
            else:
                return (9999, 1)
        deduped_sorted = sorted(deduped, key=sort_key)

        self.formats = deduped_sorted
        self.quality_dropdown.clear()
        for fmt in self.formats:
            self.quality_dropdown.addItem(fmt['label'])

        if not self.formats:
            self.log("No formats found.")
            self.quality_dropdown.setEnabled(False)
            self.download_button.setEnabled(False)
            return

        self.quality_dropdown.setEnabled(True)
        self.download_button.setEnabled(True)

        # Configure range slider and inputs
        if self.duration > 0:
            self.range_slider.setRange(0, self.duration)
            self.range_slider.setValues(0, self.duration)
            self.start_time_input.setText(seconds_to_hms(0))
            self.end_time_input.setText(seconds_to_hms(self.duration))
        else:
            self.range_slider.setRange(0, 100)
            self.range_slider.setValues(0, 100)
            self.start_time_input.setText("0:00")
            self.end_time_input.setText("1:40")  # default

        self.log(f"Found {len(self.formats)} formats (audio + video combined).")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def on_fetch_error(self, err):
        self.log(f"Error fetching info: {err}")

    def on_fetch_finished(self):
        self.fetch_button.setEnabled(True)
        self.progress_bar.setVisible(False)

    def on_slider_changed(self, start_val, end_val):
        self.start_time_input.setText(seconds_to_hms(start_val))
        self.end_time_input.setText(seconds_to_hms(end_val))

    def on_start_time_input_changed(self):
        val = hms_to_seconds(self.start_time_input.text())
        if val is None:
            self.log("Invalid start time format. Use HH:MM:SS or MM:SS or seconds.")
            return
        start_val, end_val = self.range_slider.values()
        if val > end_val:
            val = end_val
        self.range_slider.setValues(val, end_val)
        self.start_time_input.setText(seconds_to_hms(val))

    def on_end_time_input_changed(self):
        val = hms_to_seconds(self.end_time_input.text())
        if val is None:
            self.log("Invalid end time format. Use HH:MM:SS or MM:SS or seconds.")
            return
        start_val, end_val = self.range_slider.values()
        if val < start_val:
            val = start_val
        self.range_slider.setValues(start_val, val)
        self.end_time_input.setText(seconds_to_hms(val))

    def download_video(self):
        selected_index = self.quality_dropdown.currentIndex()
        if selected_index < 0 or selected_index >= len(self.formats):
            self.log("Please select a valid format.")
            return
        url = self.url_input.text().strip()
        if not url:
            self.log("Please enter a YouTube URL.")
            return
        start_time = hms_to_seconds(self.start_time_input.text())
        end_time = hms_to_seconds(self.end_time_input.text())
        if start_time is None or end_time is None:
            self.log("Invalid start or end time format.")
            return
        if start_time < 0 or end_time < 0:
            self.log("Start or end time cannot be negative.")
            return
        if end_time <= start_time:
            self.log("End time must be greater than start time.")
            return
        self.download_button.setEnabled(False)
        self.fetch_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.log("Starting download...")

        selected_meta = self.formats[selected_index]
        format_id = selected_meta['format_id']

        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~")
        outtmpl = os.path.join(downloads_path, '%(title)s.%(ext)s')

        # Build format selector:
        # If video selected and it has no audio, ask yt-dlp to merge with bestaudio
        if selected_meta['type'] == 'video':
            if not selected_meta.get('audio', False):
                format_selector = f"{format_id}+bestaudio/best"
            else:
                format_selector = format_id
        else:
            # audio selected
            format_selector = format_id

        self.worker_download = WorkerDownload(
            url, format_selector, selected_meta, self.ffmpeg_path, start_time, end_time, outtmpl
        )
        self.worker_download.progress_percent.connect(self.progress_bar.setValue)
        self.worker_download.progress_text.connect(self.log)
        self.worker_download.finished.connect(self.on_download_finished)
        self.worker_download.start()

    def on_download_finished(self, result):
        self.log(f"Finished: {result}")
        self.download_button.setEnabled(True)
        self.fetch_button.setEnabled(True)
        self.progress_bar.setVisible(False)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = YouTubeDownloaderApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
