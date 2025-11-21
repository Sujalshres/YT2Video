import sys
import os
import re
import subprocess
from PyQt6 import QtWidgets, QtCore, QtGui
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

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

    def __init__(self, url, format_selector, ffmpeg_path, start_time, end_time, outtmpl):
        super().__init__()
        self.url = url
        self.format_selector = format_selector
        self.ffmpeg_path = ffmpeg_path
        self.start_time = start_time
        self.end_time = end_time
        self.outtmpl = outtmpl

    def ydl_hook(self, d):
        if d['status'] == 'downloading':
            percent_raw = d.get('_percent_str', '0.0%').strip()
            try:
                percent = float(percent_raw.strip('%'))
            except:
                percent = 0
            self.progress_percent.emit(int(percent))
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            self.progress_text.emit(f"Downloading... {percent_raw} at {speed}, ETA: {eta}")
        elif d['status'] == 'finished':
            self.progress_percent.emit(100)
            self.progress_text.emit("Download finished, processing...")

    def run(self):
        ydl_opts = {
            'format': self.format_selector,
            'outtmpl': self.outtmpl,
            'ffmpeg_location': os.path.dirname(self.ffmpeg_path),
            'progress_hooks': [self.ydl_hook],
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
                info_dict = ydl.extract_info(self.url, download=False)
                downloaded_filename = ydl.prepare_filename(info_dict)
                if not downloaded_filename.lower().endswith('.mp4'):
                    downloaded_filename = os.path.splitext(downloaded_filename)[0] + '.mp4'

            # If no trimming needed, finish
            if self.start_time is None and self.end_time is None:
                self.finished.emit(downloaded_filename)
                return

            # trimming needed
            trimmed_filename = os.path.splitext(downloaded_filename)[0] + "_trimmed.mp4"
            cmd = [
                self.ffmpeg_path,
                '-hide_banner', '-loglevel', 'error',
                '-ss', str(self.start_time or 0),
            ]
            if self.end_time is not None:
                duration = self.end_time - (self.start_time or 0)
                cmd.extend(['-t', str(duration)])
            cmd.extend([
                '-i', downloaded_filename,
                '-c', 'copy',
                trimmed_filename
            ])
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                self.finished.emit(f"FFmpeg error: {proc.stderr.decode(errors='ignore')}")
            else:
                # Delete full video after trimming
                try:
                    os.remove(downloaded_filename)
                except Exception:
                    pass
                self.finished.emit(trimmed_filename)

        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")


class YouTubeDownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Video Downloader")
        self.setGeometry(300, 300, 700, 450)
        self.ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg', 'ffmpeg.exe')
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

        quality_label = QtWidgets.QLabel("Select Video Quality:")
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
        self.status_box.setMaximumHeight(150)

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
        mp4_formats = [f for f in formats if f.get('ext') == 'mp4' and f.get('filesize')]

        res_map = {}
        for f in mp4_formats:
            res = f.get('format_note') or f.get('resolution') or str(f.get('height') or '')
            if not res:
                continue
            acodec = f.get('acodec', 'none')
            has_audio = (acodec != 'none')
            if res not in res_map or (has_audio and res_map[res]['audio'] is False):
                res_map[res] = {
                    'format_id': f['format_id'],
                    'resolution': res,
                    'audio': has_audio,
                    'fps': f.get('fps', ''),
                    'filesize': f.get('filesize', 0)
                }
        if not res_map:
            self.log("No suitable .mp4 video formats found.")
            self.quality_dropdown.clear()
            self.quality_dropdown.setEnabled(False)
            self.download_button.setEnabled(False)
            return
        sorted_res = sorted(res_map.items(), key=lambda item: int(''.join(filter(str.isdigit, item[0]))), reverse=True)
        self.formats = [v for k,v in sorted_res]
        self.quality_dropdown.clear()
        for fmt in self.formats:
            size_mb = fmt['filesize'] / (1024 * 1024)
            label = f"{fmt['resolution']} - {size_mb:.2f} MB"
            self.quality_dropdown.addItem(label)
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

        self.log(f"Found {len(self.formats)} .mp4 video quality options.")
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
            self.log("Please select a valid video quality.")
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

        selected_format = self.formats[selected_index]
        format_id = selected_format['format_id']

        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~")
        outtmpl = os.path.join(downloads_path, '%(title)s.%(ext)s')

        format_selector = format_id if selected_format['audio'] else f"{format_id}+bestaudio/best"

        self.worker_download = WorkerDownload(
            url, format_selector, self.ffmpeg_path, start_time, end_time, outtmpl
        )
        self.worker_download.progress_percent.connect(self.progress_bar.setValue)
        self.worker_download.progress_text.connect(self.log)
        self.worker_download.finished.connect(self.on_download_finished)
        self.worker_download.start()

    def on_download_finished(self, result):
        self.log(result)
        self.download_button.setEnabled(True)
        self.fetch_button.setEnabled(True)
        self.progress_bar.setVisible(False)


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


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = YouTubeDownloaderApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
