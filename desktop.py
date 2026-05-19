from __future__ import annotations

import os
import queue
import threading
import time
import webbrowser
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
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
import licensing


class ScrollableComboBox(QComboBox):
    def __init__(self, max_visible_items: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaxVisibleItems(max_visible_items)
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")

        popup_view = QListView(self)
        popup_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setView(popup_view)


class FacebookAppSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Facebook App Settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.app_id_input = QLineEdit(self.safe_env_value("FACEBOOK_APP_ID"))
        self.app_id_input.setPlaceholderText("Meta app ID")
        form_layout.addRow("App ID", self.app_id_input)

        self.client_token_input = QLineEdit(self.safe_env_value("FACEBOOK_CLIENT_TOKEN"))
        self.client_token_input.setPlaceholderText("Meta client token")
        self.client_token_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("Client Token", self.client_token_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setText("Save")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def safe_env_value(self, name: str) -> str:
        try:
            return scheduler.get_optional_env(name) or ""
        except Exception:
            return ""

    def values(self) -> tuple[str, str]:
        return (
            self.app_id_input.text().strip(),
            self.client_token_input.text().strip(),
        )


class SelectFacebookPageDialog(QDialog):
    def __init__(self, pages: list[scheduler.FacebookConnectedPage], parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.pages = pages
        self.setWindowTitle("Select Facebook Page")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        self.page_input = ScrollableComboBox()
        for page in pages:
            self.page_input.addItem(page.label)
        layout.addWidget(self.page_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setText("Connect Page")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def selected_page(self) -> scheduler.FacebookConnectedPage:
        return self.pages[self.page_input.currentIndex()]


class SelectSchedulePagesDialog(QDialog):
    def __init__(
        self,
        pages: list[scheduler.FacebookPageConfig],
        selected_page_keys: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.pages = pages
        self.setWindowTitle("Choose Facebook Pages")
        self.resize(620, 520)

        layout = QVBoxLayout(self)

        self.page_list = QListWidget()
        self.page_list.setUniformItemSizes(True)
        self.page_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.page_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        for page in pages:
            item = QListWidgetItem(page.label)
            item.setData(Qt.UserRole, page.key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if page.key in selected_page_keys else Qt.Unchecked)
            self.page_list.addItem(item)
        layout.addWidget(self.page_list, 1)

        selection_row = QHBoxLayout()
        select_all_button = QPushButton("Select All")
        select_all_button.clicked.connect(lambda: self.set_all_pages_checked(True))
        selection_row.addWidget(select_all_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: self.set_all_pages_checked(False))
        selection_row.addWidget(clear_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setText("Use Selected Pages")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def set_all_pages_checked(self, checked: bool) -> None:
        check_state = Qt.Checked if checked else Qt.Unchecked
        for index in range(self.page_list.count()):
            self.page_list.item(index).setCheckState(check_state)

    def selected_page_keys(self) -> set[str]:
        page_keys = set()
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.checkState() == Qt.Checked:
                page_keys.add(str(item.data(Qt.UserRole)))

        return page_keys


class ActivationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Activate Facebook Page Scheduler")
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)

        title = QLabel("This app is not activated.")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Send this Device ID to the app owner to get a license."))

        device_row = QHBoxLayout()
        self.device_id_input = QLineEdit(licensing.get_device_id())
        self.device_id_input.setReadOnly(True)
        device_row.addWidget(self.device_id_input, 1)

        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self.copy_device_id)
        device_row.addWidget(copy_button)
        layout.addLayout(device_row)

        layout.addWidget(QLabel("License Key"))
        self.license_input = QPlainTextEdit()
        self.license_input.setPlaceholderText("Paste the license key here")
        self.license_input.setFixedHeight(150)
        layout.addWidget(self.license_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #b91c1c;")
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(self.reject)
        button_row.addWidget(quit_button)

        activate_button = QPushButton("Activate")
        activate_button.clicked.connect(self.activate)
        button_row.addWidget(activate_button)
        layout.addLayout(button_row)

    def copy_device_id(self) -> None:
        QApplication.clipboard().setText(self.device_id_input.text())
        self.status_label.setStyleSheet("color: #4b5563;")
        self.status_label.setText("Device ID copied.")

    def activate(self) -> None:
        license_token = self.license_input.toPlainText().strip()
        if not license_token:
            self.status_label.setStyleSheet("color: #b91c1c;")
            self.status_label.setText("Paste a license key first.")
            return

        try:
            license_info = licensing.save_license(license_token)
        except Exception as exc:
            self.status_label.setStyleSheet("color: #b91c1c;")
            self.status_label.setText(str(exc))
            return

        self.status_label.setStyleSheet("color: #4b5563;")
        self.status_label.setText(f"Activated for {license_info.name}.")
        self.accept()


class SchedulerDesktopApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        scheduler.load_env_file()
        scheduler.init_db()

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_scheduler_event = threading.Event()
        self.scheduler_thread: threading.Thread | None = None
        self.worker_running = False
        self.page_configs: list[scheduler.FacebookPageConfig] = []
        self.selected_page_key_set: set[str] = set()

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

        page_selection_row = QHBoxLayout()
        page_selection_row.setSpacing(8)
        form_layout.addWidget(QLabel("Facebook Pages"))
        self.page_selection_label = QLabel("No pages selected")
        self.page_selection_label.setStyleSheet("color: #4b5563;")
        page_selection_row.addWidget(self.page_selection_label, 1)

        self.choose_pages_button = QPushButton("Choose Pages")
        self.choose_pages_button.clicked.connect(self.choose_schedule_pages)
        page_selection_row.addWidget(self.choose_pages_button)
        form_layout.addLayout(page_selection_row)

        page_row = QHBoxLayout()
        page_row.setSpacing(8)

        self.facebook_app_settings_button = QPushButton("App Settings")
        self.facebook_app_settings_button.setToolTip("Set or change the Meta app ID and client token")
        self.facebook_app_settings_button.clicked.connect(self.edit_facebook_app_settings)
        page_row.addWidget(self.facebook_app_settings_button, 1)

        self.connect_facebook_button = QPushButton("Connect Page")
        self.connect_facebook_button.setToolTip("Connect a Facebook profile and save one of its Pages")
        self.connect_facebook_button.clicked.connect(self.connect_facebook)
        page_row.addWidget(self.connect_facebook_button, 1)
        form_layout.addLayout(page_row)

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
        self.table.setWordWrap(False)
        self.configure_posts_table_columns()
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

    def configure_posts_table_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        header.setDefaultSectionSize(140)

        column_widths = {
            0: 92,
            1: 130,
            2: 82,
            3: 180,
            4: 260,
            5: 180,
            6: 220,
            7: 180,
            8: 190,
            9: 170,
            10: 280,
        }

        for column_index, width in column_widths.items():
            header.setSectionResizeMode(column_index, QHeaderView.Interactive)
            self.table.setColumnWidth(column_index, width)

    def selected_page_keys(self) -> list[str]:
        return [
            page.key
            for page in self.page_configs
            if page.key in self.selected_page_key_set
        ]

    def selected_page_labels(self) -> list[str]:
        return [
            page.label
            for page in self.page_configs
            if page.key in self.selected_page_key_set
        ]

    def set_page_controls_enabled(self, enabled: bool) -> None:
        self.choose_pages_button.setEnabled(enabled)

    def set_all_pages_checked(self, checked: bool) -> None:
        self.selected_page_key_set = {page.key for page in self.page_configs} if checked else set()
        self.update_page_selection_state()

    def select_all_pages(self) -> None:
        self.set_all_pages_checked(True)

    def clear_page_selection(self) -> None:
        self.set_all_pages_checked(False)

    def update_page_selection_state(self) -> None:
        selected_count = len(self.selected_page_keys())
        total_count = len(self.page_configs)
        if total_count == 0:
            self.page_selection_label.setText("No pages configured")
            self.page_selection_label.setToolTip("")
            return

        if selected_count == 0:
            self.page_selection_label.setText(f"0 of {total_count} selected")
            self.page_selection_label.setToolTip("")
            return

        labels = self.selected_page_labels()
        self.page_selection_label.setText(f"{selected_count} of {total_count} selected")
        self.page_selection_label.setToolTip("\n".join(labels))

    def choose_schedule_pages(self) -> None:
        if not self.page_configs:
            QMessageBox.information(self, "No pages", "Use Connect Page to add a page first.")
            return

        dialog = SelectSchedulePagesDialog(self.page_configs, self.selected_page_key_set, self)
        if dialog.exec() != QDialog.Accepted:
            return

        self.selected_page_key_set = dialog.selected_page_keys()
        self.update_page_selection_state()

    def load_page_options(self, selected_page_key: str | None = None) -> None:
        try:
            self.page_configs = scheduler.get_facebook_pages()
        except Exception as exc:
            self.page_configs = []
            self.selected_page_key_set = set()
            self.set_page_controls_enabled(False)
            self.schedule_button.setEnabled(False)
            self.update_page_selection_state()
            self.set_status(f"Could not load Facebook pages: {exc}", error=True)
            return

        available_page_keys = {page.key for page in self.page_configs}
        self.selected_page_key_set &= available_page_keys
        if selected_page_key and selected_page_key in available_page_keys:
            self.selected_page_key_set.add(selected_page_key)
        if not self.selected_page_key_set and self.page_configs:
            self.selected_page_key_set.add(self.page_configs[0].key)

        self.set_page_controls_enabled(True)
        self.schedule_button.setEnabled(True)
        self.update_page_selection_state()
        self.set_status(f"Loaded {len(self.page_configs)} Facebook page(s).")

    def prompt_facebook_app_settings(self) -> scheduler.FacebookAppConfig | None:
        dialog = FacebookAppSettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return None

        app_id, client_token = dialog.values()
        try:
            return scheduler.save_facebook_app_config(app_id, client_token)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save Facebook app settings", str(exc))
            self.set_status(f"Could not save Facebook app settings: {exc}", error=True)
            return None

    def ensure_facebook_app_config(self) -> scheduler.FacebookAppConfig | None:
        try:
            return scheduler.get_facebook_app_config()
        except Exception:
            return self.prompt_facebook_app_settings()

    def edit_facebook_app_settings(self) -> None:
        app_config = self.prompt_facebook_app_settings()
        if app_config is None:
            return

        self.log("Facebook app settings saved.")

    def connect_facebook(self) -> None:
        app_config = self.ensure_facebook_app_config()
        if app_config is None:
            return

        self.connect_facebook_button.setEnabled(False)
        self.facebook_app_settings_button.setEnabled(False)
        self.log(
            "Opening Facebook connection. If the wrong profile appears, use a private window "
            "or switch Facebook accounts before entering the code."
        )
        threading.Thread(
            target=self.connect_facebook_worker,
            args=(app_config,),
            daemon=True,
        ).start()

    def connect_facebook_worker(self, app_config: scheduler.FacebookAppConfig) -> None:
        try:
            pages = self.fetch_connected_facebook_pages(app_config)
            self.events.put(("facebook_pages", pages))
        except Exception as exc:
            self.events.put(("error", f"Facebook connection failed: {exc}"))
        finally:
            self.events.put(("connect_finished", None))

    def fetch_connected_facebook_pages(
        self,
        app_config: scheduler.FacebookAppConfig,
    ) -> list[scheduler.FacebookConnectedPage]:
        device_login = scheduler.start_facebook_device_login(app_config)
        user_code = str(device_login["user_code"])
        verification_uri = str(device_login["verification_uri"])
        device_code = str(device_login["code"])
        expires_in = int(device_login["expires_in"])
        interval = max(5, int(device_login["interval"]))

        self.events.put(("device_code", {
            "user_code": user_code,
            "verification_uri": verification_uri,
            "expires_in": expires_in,
        }))

        webbrowser.open(verification_uri)
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            user_access_token = scheduler.poll_facebook_device_login(device_code, app_config)
            if user_access_token:
                return scheduler.get_connected_facebook_pages(user_access_token, app_config)

            time.sleep(interval)

        raise ValueError("Facebook device login timed out")

    def save_connected_facebook_page(self, page: scheduler.FacebookConnectedPage) -> None:
        try:
            page_config = scheduler.save_connected_facebook_page_to_env(page)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save connected page", str(exc))
            self.set_status(f"Could not save connected page: {exc}", error=True)
            return

        self.load_page_options(selected_page_key=page_config.key)
        self.log(f"Connected Facebook page {page_config.name}.")

    def choose_connected_facebook_page(self, pages: list[scheduler.FacebookConnectedPage]) -> None:
        if len(pages) == 1:
            self.save_connected_facebook_page(pages[0])
            return

        dialog = SelectFacebookPageDialog(pages, self)
        if dialog.exec() != QDialog.Accepted:
            return

        self.save_connected_facebook_page(dialog.selected_page())

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
        page_keys = self.selected_page_keys()
        page_labels = self.selected_page_labels()
        media_paths = self.media_paths_from_input()
        media_path = media_paths if len(media_paths) > 1 else (media_paths[0] if media_paths else None)

        if not page_keys:
            QMessageBox.warning(self, "Missing pages", "Select at least one Facebook Page.")
            return

        if not message and not media_paths:
            QMessageBox.warning(self, "Missing content", "Add a message or choose media.")
            return

        media_type = self.media_type_input.currentText().strip().lower()
        if media_type == "auto" or not media_paths:
            media_type = None

        try:
            for page_key in page_keys:
                scheduler.add_post(message, scheduled_at, media_path, media_type, first_comment, page_key)
        except Exception as exc:
            QMessageBox.critical(self, "Could not schedule post", str(exc))
            self.set_status(f"Could not schedule post: {exc}", error=True)
            return

        if len(page_labels) == 1:
            self.log(f"Post scheduled for {page_labels[0]}.")
        else:
            self.log(f"Post scheduled for {len(page_labels)} pages.")
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
                item.setToolTip(value)
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

            if event_type == "log" and isinstance(payload, str):
                self.log(payload)
            elif event_type == "error" and isinstance(payload, str):
                self.log(f"Error: {payload}")
                self.set_status(payload, error=True)
                self.refresh_posts()
            elif event_type == "refresh":
                self.refresh_posts()
            elif event_type == "facebook_pages" and isinstance(payload, list):
                self.choose_connected_facebook_page(payload)
            elif event_type == "connect_finished":
                self.connect_facebook_button.setEnabled(True)
                self.facebook_app_settings_button.setEnabled(True)
            elif event_type == "device_code" and isinstance(payload, dict):
                user_code = str(payload.get("user_code", ""))
                verification_uri = str(payload.get("verification_uri", "https://www.facebook.com/device"))
                QMessageBox.information(
                    self,
                    "Connect Page",
                    (
                        f"Enter code {user_code} at {verification_uri}.\n\n"
                        "To connect a different Facebook profile, open that link in a private "
                        "browser window or switch Facebook accounts before entering the code."
                    ),
                )

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
    try:
        licensing.get_saved_license_info()
    except Exception:
        activation_dialog = ActivationDialog()
        if activation_dialog.exec() != QDialog.Accepted:
            return

    window = SchedulerDesktopApp()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
