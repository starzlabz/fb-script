from __future__ import annotations

import os
import queue
import threading
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import app as scheduler


class SchedulerDesktopApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        scheduler.load_env_file()
        scheduler.init_db()

        self.events: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.stop_scheduler_event = threading.Event()
        self.scheduler_thread: threading.Thread | None = None
        self.worker_running = False
        self.page_configs: list[scheduler.FacebookPageConfig] = []

        self.setWindowTitle("Facebook Page Scheduler")
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

        self.build_layout()
        self.refresh_posts()
        self.load_page_options()

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.drain_events)
        self.event_timer.start(200)

    def build_layout(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(16, 14, 16, 12)
        main_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        title = QLabel("Facebook Page Scheduler")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.scheduler_state_label = QLabel("Scheduler stopped")
        self.scheduler_state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.scheduler_state_label.setStyleSheet("color: #4b5563;")
        header_layout.addWidget(title, 1)
        header_layout.addWidget(self.scheduler_state_label)
        main_layout.addLayout(header_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        main_layout.addLayout(content_layout, 1)

        form_box = QGroupBox("Schedule Post")
        form_box.setMinimumWidth(390)
        form_layout = QVBoxLayout(form_box)
        form_layout.setContentsMargins(14, 18, 14, 14)
        form_layout.setSpacing(8)

        form_layout.addWidget(QLabel("Facebook Page"))
        self.page_input = QComboBox()
        form_layout.addWidget(self.page_input)

        form_layout.addWidget(QLabel("Message"))
        self.message_input = QPlainTextEdit()
        self.message_input.setPlaceholderText("Write the post text or caption")
        self.message_input.setFixedHeight(150)
        form_layout.addWidget(self.message_input)

        form_layout.addWidget(QLabel("First Comment"))
        self.first_comment_input = QPlainTextEdit()
        self.first_comment_input.setPlaceholderText("Optional first comment")
        self.first_comment_input.setFixedHeight(100)
        form_layout.addWidget(self.first_comment_input)

        form_layout.addWidget(QLabel("Scheduled At"))
        schedule_row = QHBoxLayout()
        schedule_row.setSpacing(8)
        self.scheduled_at_input = QLineEdit(self.default_schedule_time())
        self.scheduled_at_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS")
        schedule_row.addWidget(self.scheduled_at_input, 1)

        one_hour_button = QPushButton("+1 Hour")
        one_hour_button.clicked.connect(self.set_one_hour_later)
        schedule_row.addWidget(one_hour_button)

        now_button = QPushButton("Now")
        now_button.clicked.connect(self.set_now)
        schedule_row.addWidget(now_button)
        form_layout.addLayout(schedule_row)

        form_layout.addWidget(QLabel("Media Paths or URLs"))
        media_row = QHBoxLayout()
        media_row.setSpacing(8)
        self.media_path_input = QPlainTextEdit()
        self.media_path_input.setPlaceholderText("Optional image/video file or public URL, one per line")
        self.media_path_input.setFixedHeight(76)
        media_row.addWidget(self.media_path_input, 1)

        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_media)
        media_row.addWidget(browse_button)
        form_layout.addLayout(media_row)

        form_layout.addWidget(QLabel("Media Type"))
        self.media_type_input = QComboBox()
        self.media_type_input.addItems(["Auto", "Image", "Video"])
        form_layout.addWidget(self.media_type_input)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self.schedule_button = QPushButton("Schedule")
        self.schedule_button.clicked.connect(self.schedule_post)
        self.schedule_button.setMinimumHeight(36)
        actions_row.addWidget(self.schedule_button, 1)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_form)
        actions_row.addWidget(clear_button)
        form_layout.addLayout(actions_row)

        scheduler_box = QGroupBox("Scheduler")
        scheduler_layout = QGridLayout(scheduler_box)

        publish_now_button = QPushButton("Publish Due Now")
        publish_now_button.clicked.connect(self.publish_due_now)
        scheduler_layout.addWidget(publish_now_button, 0, 0, 1, 2)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_scheduler)
        scheduler_layout.addWidget(self.start_button, 1, 0)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_scheduler)
        self.stop_button.setEnabled(False)
        scheduler_layout.addWidget(self.stop_button, 1, 1)

        form_layout.addWidget(scheduler_box)
        form_layout.addStretch(1)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setMinimumWidth(420)
        form_scroll.setWidget(form_box)
        content_layout.addWidget(form_scroll)

        right_layout = QVBoxLayout()
        content_layout.addLayout(right_layout, 1)

        table_toolbar = QHBoxLayout()
        posts_label = QLabel("Posts")
        posts_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        table_toolbar.addWidget(posts_label, 1)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_posts)
        table_toolbar.addWidget(refresh_button)

        retry_button = QPushButton("Retry")
        retry_button.clicked.connect(self.retry_selected)
        table_toolbar.addWidget(retry_button)

        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected)
        table_toolbar.addWidget(delete_button)
        right_layout.addLayout(table_toolbar)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Status",
            "Page",
            "Type",
            "Scheduled",
            "Message",
            "First Comment",
            "Media",
            "Published",
            "Facebook ID",
            "Comment ID",
            "Error",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        right_layout.addWidget(self.table, 1)

        activity_label = QLabel("Activity")
        activity_label.setStyleSheet("font-weight: 700;")
        main_layout.addWidget(activity_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(400)
        self.log_output.setMinimumHeight(120)
        main_layout.addWidget(self.log_output)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #4b5563;")
        main_layout.addWidget(self.status_label)

    def default_schedule_time(self) -> str:
        return (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    def set_one_hour_later(self) -> None:
        scheduled_at = self.scheduled_at_input.text().strip()
        try:
            base_time = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            base_time = datetime.now()

        self.scheduled_at_input.setText(
            (base_time + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        )

    def set_now(self) -> None:
        self.scheduled_at_input.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def load_page_options(self) -> None:
        self.page_input.clear()

        try:
            self.page_configs = scheduler.get_facebook_pages()
        except Exception as exc:
            self.page_configs = []
            self.page_input.addItem("No pages configured", "")
            self.page_input.setEnabled(False)
            self.schedule_button.setEnabled(False)
            self.set_status(f"Could not load Facebook pages: {exc}", error=True)
            return

        for page in self.page_configs:
            self.page_input.addItem(page.label, page.key)

        self.page_input.setEnabled(True)
        self.schedule_button.setEnabled(True)
        self.set_status(f"Loaded {len(self.page_configs)} Facebook page(s).")

    def browse_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select media",
            "",
            "Media files (*.jpg *.jpeg *.png *.gif *.tif *.tiff *.bmp *.mp4 *.mov *.m4v *.avi *.webm *.mkv *.mpeg *.mpg *.wmv *.flv);;Images (*.jpg *.jpeg *.png *.gif *.tif *.tiff *.bmp);;Videos (*.mp4 *.mov *.m4v *.avi *.webm *.mkv *.mpeg *.mpg *.wmv *.flv);;All files (*.*)",
        )
        if not paths:
            return

        media_paths = self.media_paths_from_input()
        for path in paths:
            if path not in media_paths:
                media_paths.append(path)

        self.media_path_input.setPlainText("\n".join(media_paths))
        try:
            detected_types = {scheduler.detect_media_type(path) for path in media_paths}
            if len(media_paths) > 1:
                self.media_type_input.setCurrentText("Image" if detected_types == {"image"} else "Auto")
            else:
                self.media_type_input.setCurrentText(next(iter(detected_types)).capitalize())
        except ValueError:
            self.media_type_input.setCurrentText("Auto")

    def media_paths_from_input(self) -> list[str]:
        return [
            path.strip()
            for path in self.media_path_input.toPlainText().splitlines()
            if path.strip()
        ]

    def schedule_post(self) -> None:
        message = self.message_input.toPlainText().strip()
        first_comment = self.first_comment_input.toPlainText().strip() or None
        scheduled_at = self.scheduled_at_input.text().strip()
        page_key = self.page_input.currentData()
        media_paths = self.media_paths_from_input()
        media_path = media_paths if len(media_paths) > 1 else (media_paths[0] if media_paths else None)

        if not page_key:
            QMessageBox.warning(self, "Missing page", "Add a Facebook page in .env first.")
            return

        if not message and not media_paths:
            QMessageBox.warning(self, "Missing content", "Add a message or choose media.")
            return

        media_type = self.media_type_input.currentText().strip().lower()
        if media_type == "auto" or not media_paths:
            media_type = None

        try:
            scheduler.add_post(message, scheduled_at, media_path, media_type, first_comment, page_key)
        except Exception as exc:
            QMessageBox.critical(self, "Could not schedule post", str(exc))
            self.set_status(f"Could not schedule post: {exc}", error=True)
            return

        self.log(f"Post scheduled for {self.page_input.currentText()}.")
        self.clear_form(keep_time=False)
        self.refresh_posts()

    def clear_form(self, keep_time: bool = True) -> None:
        self.message_input.clear()
        self.first_comment_input.clear()
        self.media_path_input.clear()
        self.media_type_input.setCurrentText("Auto")
        if not keep_time:
            self.set_one_hour_later()

    def selected_post_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a post", "Select a post first.")
            return None

        item = self.table.item(row, 0)
        if item is None:
            return None

        return int(item.data(Qt.UserRole))

    def delete_selected(self) -> None:
        post_id = self.selected_post_id()
        if post_id is None:
            return

        answer = QMessageBox.question(self, "Delete post", f"Delete post {post_id}?")
        if answer != QMessageBox.Yes:
            return

        try:
            scheduler.delete_post(post_id)
        except Exception as exc:
            QMessageBox.critical(self, "Could not delete post", str(exc))
            self.set_status(f"Could not delete post: {exc}", error=True)
            return

        self.log(f"Deleted post {post_id}.")
        self.refresh_posts()

    def retry_selected(self) -> None:
        post_id = self.selected_post_id()
        if post_id is None:
            return

        try:
            scheduler.retry_post(post_id)
        except Exception as exc:
            QMessageBox.critical(self, "Could not retry post", str(exc))
            self.set_status(f"Could not retry post: {exc}", error=True)
            return

        self.log(f"Post {post_id} marked for retry.")
        self.refresh_posts()

    def refresh_posts(self) -> None:
        try:
            rows = scheduler.get_posts()
        except Exception as exc:
            QMessageBox.critical(self, "Could not load posts", str(exc))
            self.set_status(f"Could not load posts: {exc}", error=True)
            return

        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            status = row["status"] or ""
            page_name = row["page_name"] or row["page_key"] or "Default"
            media_type = row["media_type"] or "text"
            media_path = row["media_path"] or ""
            values = [
                status,
                page_name,
                media_type,
                row["scheduled_at"] or "",
                row["message"] or "",
                row["first_comment"] or "",
                self.compact_media_path(media_path),
                row["published_at"] or "",
                row["facebook_post_id"] or "",
                row["facebook_comment_id"] or "",
                row["error_message"] or "",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row["id"])
                if status == "published":
                    item.setForeground(Qt.darkGreen)
                elif status in {"failed", "comment_failed"}:
                    item.setForeground(Qt.red)
                self.table.setItem(row_index, column_index, item)

        self.set_status(f"Loaded {len(rows)} post(s).")

    def publish_due_now(self) -> None:
        if self.worker_running:
            self.set_status("Publisher is already running.")
            return

        self.worker_running = True
        threading.Thread(target=self.publish_due_worker, daemon=True).start()

    def publish_due_worker(self) -> None:
        try:
            count = scheduler.publish_due_posts_once(log=self.thread_log)
            if count == 0:
                self.thread_log("No due posts.")
            self.events.put(("refresh", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.worker_running = False

    def start_scheduler(self) -> None:
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return

        self.stop_scheduler_event.clear()
        self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.scheduler_state_label.setText("Scheduler running")
        self.log("Scheduler started.")

    def stop_scheduler(self) -> None:
        self.stop_scheduler_event.set()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.scheduler_state_label.setText("Scheduler stopped")
        self.log("Scheduler stopped.")

    def scheduler_loop(self) -> None:
        while not self.stop_scheduler_event.is_set():
            try:
                count = scheduler.publish_due_posts_once(log=self.thread_log)
                if count:
                    self.events.put(("refresh", None))
            except Exception as exc:
                self.events.put(("error", str(exc)))

            self.stop_scheduler_event.wait(self.scheduler_interval_seconds())

    def scheduler_interval_seconds(self) -> int:
        try:
            return max(5, int(os.getenv("CHECK_INTERVAL_SECONDS", "30")))
        except ValueError:
            return 30

    def thread_log(self, message: str) -> None:
        self.events.put(("log", message))

    def drain_events(self) -> None:
        while True:
            try:
                event_type, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event_type == "log" and payload is not None:
                self.log(payload)
            elif event_type == "error" and payload is not None:
                self.log(f"Error: {payload}")
                self.set_status(payload, error=True)
                self.refresh_posts()
            elif event_type == "refresh":
                self.refresh_posts()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        self.set_status(message)

    def set_status(self, message: str, error: bool = False) -> None:
        self.status_label.setText(message)
        color = "#b91c1c" if error else "#4b5563"
        self.status_label.setStyleSheet(f"color: {color};")

    def compact_path(self, path: str) -> str:
        if not path:
            return ""
        if scheduler.is_remote_url(path):
            return path
        try:
            return os.path.relpath(path, scheduler.BASE_DIR)
        except ValueError:
            return path

    def compact_media_path(self, media_path: str) -> str:
        media_paths = scheduler.parse_media_paths(media_path)
        if not media_paths:
            return ""

        compacted_paths = [self.compact_path(path) for path in media_paths]
        if len(compacted_paths) == 1:
            return compacted_paths[0]

        return f"{len(compacted_paths)} images: " + ", ".join(compacted_paths)

    def closeEvent(self, event) -> None:
        self.stop_scheduler_event.set()
        event.accept()


def main() -> None:
    app = QApplication([])
    window = SchedulerDesktopApp()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
