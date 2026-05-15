import os
import sys
import json
import time
import sqlite3
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "scheduler.db")
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".wmv"}
MEDIA_TYPES = {"image", "video"}
MediaPathInput = Optional[Union[str, list[str], tuple[str, ...]]]


@dataclass(frozen=True)
class FacebookPageConfig:
    key: str
    name: str
    page_id: str
    page_access_token: str
    graph_api_version: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.page_id})"


def is_placeholder_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("your_") and normalized.endswith("_here")


def strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise ValueError(f"Missing environment variable: {name}")
    value = value.strip()
    if is_placeholder_value(value):
        raise ValueError(f"{name} is still set to a placeholder value in .env")
    return value


def get_optional_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None

    value = value.strip()
    if is_placeholder_value(value):
        raise ValueError(f"{name} is still set to a placeholder value in .env")

    return value


def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = strip_env_quotes(value)

            if key:
                os.environ[key] = value


def validate_facebook_config(page_access_token: str, token_name: str = "PAGE_ACCESS_TOKEN") -> None:
    if page_access_token.lower().startswith("bearer "):
        raise ValueError(f"{token_name} should contain only the token, without 'Bearer '")

    if any(ch.isspace() for ch in page_access_token):
        raise ValueError(f"{token_name} contains whitespace; keep the token on one line in .env")


def build_page_config(
    key: str,
    name: str,
    page_id: str,
    page_access_token: str,
    graph_api_version: str,
    token_name: str,
) -> FacebookPageConfig:
    page_id = page_id.strip()
    if any(ch.isspace() for ch in page_id):
        raise ValueError(f"{key} page ID contains whitespace; keep it on one line in .env")

    validate_facebook_config(page_access_token, token_name)
    return FacebookPageConfig(
        key=key.strip(),
        name=name.strip(),
        page_id=page_id,
        page_access_token=page_access_token.strip(),
        graph_api_version=graph_api_version.strip(),
    )


def get_indexed_page_numbers() -> list[int]:
    page_numbers = []
    for key in os.environ:
        if not key.startswith("PAGE_") or not key.endswith("_ID"):
            continue

        number = key[len("PAGE_"):-len("_ID")]
        if number.isdigit():
            page_numbers.append(int(number))

    return sorted(set(page_numbers))


def get_facebook_pages() -> list[FacebookPageConfig]:
    graph_api_version = get_env("GRAPH_API_VERSION", "v25.0")
    pages = []

    legacy_page_id = get_optional_env("PAGE_ID")
    legacy_page_access_token = get_optional_env("PAGE_ACCESS_TOKEN")
    if legacy_page_id or legacy_page_access_token:
        if not legacy_page_id or not legacy_page_access_token:
            raise ValueError("Set both PAGE_ID and PAGE_ACCESS_TOKEN, or remove both.")

        pages.append(build_page_config(
            "default",
            get_optional_env("PAGE_NAME") or "Default Page",
            legacy_page_id,
            legacy_page_access_token,
            graph_api_version,
            "PAGE_ACCESS_TOKEN",
        ))

    for number in get_indexed_page_numbers():
        prefix = f"PAGE_{number}"
        page_key = get_optional_env(f"{prefix}_KEY") or f"page_{number}"
        page_name = get_optional_env(f"{prefix}_NAME") or f"Page {number}"
        page_id = get_env(f"{prefix}_ID")
        page_access_token = get_env(f"{prefix}_ACCESS_TOKEN")
        page_graph_api_version = get_optional_env(f"{prefix}_GRAPH_API_VERSION") or graph_api_version

        pages.append(build_page_config(
            page_key,
            page_name,
            page_id,
            page_access_token,
            page_graph_api_version,
            f"{prefix}_ACCESS_TOKEN",
        ))

    if not pages:
        raise ValueError(
            "No Facebook pages configured. Set PAGE_ID/PAGE_ACCESS_TOKEN "
            "or PAGE_1_ID/PAGE_1_ACCESS_TOKEN in .env."
        )

    seen_keys = set()
    for page in pages:
        normalized_key = page.key.casefold()
        if normalized_key in seen_keys:
            raise ValueError(f"Duplicate Facebook page key in .env: {page.key}")
        seen_keys.add(normalized_key)

    return pages


def get_facebook_config(page_key: Optional[str] = None) -> FacebookPageConfig:
    pages = get_facebook_pages()
    if not page_key or not page_key.strip():
        return pages[0]

    requested = page_key.strip()
    requested_casefold = requested.casefold()
    for page in pages:
        if requested == page.page_id:
            return page
        if requested_casefold in {page.key.casefold(), page.name.casefold()}:
            return page

    available_pages = ", ".join(f"{page.key} ({page.name})" for page in pages)
    raise ValueError(f"Unknown Facebook page '{requested}'. Available pages: {available_pages}")


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_media_extension(media_path: str) -> str:
    path = urlparse(media_path).path if is_remote_url(media_path) else media_path
    return os.path.splitext(path)[1].lower()


def detect_media_type(media_path: str) -> str:
    extension = get_media_extension(media_path)

    if extension in IMAGE_EXTENSIONS:
        return "image"

    if extension in VIDEO_EXTENSIONS:
        return "video"

    raise ValueError(
        "Could not detect media type from file extension. "
        "Use add-image or add-video for this file."
    )


def normalize_media_path(media_path: str) -> str:
    media_path = media_path.strip()
    if not media_path:
        raise ValueError("Media path cannot be empty")

    if is_remote_url(media_path):
        return media_path

    normalized_path = os.path.expanduser(media_path)
    if not os.path.isabs(normalized_path):
        normalized_path = os.path.join(BASE_DIR, normalized_path)

    if not os.path.isfile(normalized_path):
        raise ValueError(f"Media file was not found: {media_path}")

    return normalized_path


def parse_media_paths(media_path: MediaPathInput) -> list[str]:
    if media_path is None:
        return []

    if isinstance(media_path, (list, tuple)):
        return [path.strip() for path in media_path if path and path.strip()]

    media_path = media_path.strip()
    if not media_path:
        return []

    if media_path.startswith("["):
        try:
            values = json.loads(media_path)
        except json.JSONDecodeError:
            values = None

        if isinstance(values, list) and all(isinstance(value, str) for value in values):
            return [value.strip() for value in values if value.strip()]

    if "\n" in media_path:
        return [path.strip() for path in media_path.splitlines() if path.strip()]

    return [media_path]


def serialize_media_paths(media_paths: list[str]) -> Optional[str]:
    if not media_paths:
        return None

    if len(media_paths) == 1:
        return media_paths[0]

    return json.dumps(media_paths)


def validate_media(media_path: MediaPathInput, media_type: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    media_paths = parse_media_paths(media_path)
    if not media_paths:
        if media_type:
            raise ValueError("Media type was provided without a media path")
        return None, None

    explicit_media_type = media_type.strip().lower() if media_type else None
    detected_media_types = [detect_media_type(path) for path in media_paths]

    if len(media_paths) > 1:
        if explicit_media_type and explicit_media_type != "image":
            raise ValueError("Multiple media files are only supported for image posts")

        if any(detected_media_type != "image" for detected_media_type in detected_media_types):
            raise ValueError("Multiple media files are only supported for images")

        for path in media_paths:
            normalize_media_path(path)

        return serialize_media_paths(media_paths), "image"

    media_path = media_paths[0]
    normalized_media_type = explicit_media_type or detected_media_types[0]

    if normalized_media_type not in MEDIA_TYPES:
        raise ValueError("Media type must be image or video")

    normalize_media_path(media_path)
    return media_path, normalized_media_type


def ensure_db_dir() -> None:
    os.makedirs(DB_DIR, exist_ok=True)


def get_db_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_key TEXT,
            page_name TEXT,
            message TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            media_path TEXT,
            media_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            published_at TEXT,
            facebook_post_id TEXT,
            first_comment TEXT,
            facebook_comment_id TEXT,
            error_message TEXT
        )
    """)

    cur.execute("PRAGMA table_info(scheduled_posts)")
    columns = {row["name"] for row in cur.fetchall()}
    if "page_key" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN page_key TEXT")
    if "page_name" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN page_name TEXT")
    if "media_path" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN media_path TEXT")
    if "media_type" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN media_type TEXT")
    if "first_comment" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN first_comment TEXT")
    if "facebook_comment_id" not in columns:
        cur.execute("ALTER TABLE scheduled_posts ADD COLUMN facebook_comment_id TEXT")

    conn.commit()
    conn.close()


def validate_datetime(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def add_post(
    message: str,
    scheduled_at: str,
    media_path: MediaPathInput = None,
    media_type: Optional[str] = None,
    first_comment: Optional[str] = None,
    page_key: Optional[str] = None,
) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    message = message.strip()
    if not message and not parse_media_paths(media_path):
        raise ValueError("Add a message or media file for the post")

    media_path, media_type = validate_media(media_path, media_type)
    first_comment = first_comment.strip() if first_comment and first_comment.strip() else None
    page_name = None
    if page_key and page_key.strip():
        page_config = get_facebook_config(page_key)
        page_key = page_config.key
        page_name = page_config.name
    else:
        page_key = None

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO scheduled_posts (
            page_key, page_name, message, scheduled_at, media_path, media_type, first_comment, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        page_key,
        page_name,
        message,
        scheduled_at,
        media_path,
        media_type,
        first_comment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))

    conn.commit()
    conn.close()


def get_posts() -> list[sqlite3.Row]:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, page_key, page_name, message, scheduled_at, media_path, media_type, first_comment, status,
               published_at, facebook_post_id, facebook_comment_id, error_message
        FROM scheduled_posts
        ORDER BY scheduled_at ASC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def list_posts() -> None:
    rows = get_posts()

    if not rows:
        print("No scheduled posts found.")
        return

    for row in rows:
        print("-" * 80)
        print(f"ID: {row['id']}")
        print(f"Page: {row['page_name'] or row['page_key'] or 'default from .env'}")
        print(f"Message: {row['message']}")
        if row["media_path"]:
            media_paths = parse_media_paths(row["media_path"])
            if len(media_paths) == 1:
                print(f"Media: {row['media_type']} - {media_paths[0]}")
            else:
                print(f"Media: {row['media_type']} - {len(media_paths)} images")
                for media_index, path in enumerate(media_paths, start=1):
                    print(f"  {media_index}. {path}")
        if row["first_comment"]:
            print(f"First Comment: {row['first_comment']}")
        print(f"Scheduled At: {row['scheduled_at']}")
        print(f"Status: {row['status']}")
        print(f"Published At: {row['published_at']}")
        print(f"Facebook Post ID: {row['facebook_post_id']}")
        print(f"Facebook Comment ID: {row['facebook_comment_id']}")
        print(f"Error: {row['error_message']}")


def delete_post(post_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()


def retry_post(post_id: int) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'pending',
            error_message = NULL
        WHERE id = ?
    """, (post_id,))

    conn.commit()
    conn.close()


def get_due_posts() -> list[sqlite3.Row]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM scheduled_posts
        WHERE status = 'pending'
          AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
    """, (now_str,))

    rows = cur.fetchall()
    conn.close()
    return rows


def mark_post_success(
    post_id: int,
    facebook_post_id: Optional[str],
    facebook_comment_id: Optional[str] = None,
) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'published',
            published_at = ?,
            facebook_post_id = ?,
            facebook_comment_id = ?,
            error_message = NULL
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        facebook_post_id,
        facebook_comment_id,
        post_id,
    ))

    conn.commit()
    conn.close()


def mark_post_failed(post_id: int, error_message: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'failed',
            error_message = ?
        WHERE id = ?
    """, (error_message[:2000], post_id))

    conn.commit()
    conn.close()


def mark_first_comment_failed(post_id: int, facebook_post_id: str, error_message: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'comment_failed',
            published_at = ?,
            facebook_post_id = ?,
            error_message = ?
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        facebook_post_id,
        error_message[:2000],
        post_id,
    ))

    conn.commit()
    conn.close()


def parse_facebook_response(response: requests.Response) -> tuple[bool, str]:
    try:
        response.raise_for_status()
        data = response.json()

        facebook_post_id = data.get("post_id") or data.get("id")
        if facebook_post_id:
            return True, facebook_post_id

        return False, f"Unexpected response: {json.dumps(data, ensure_ascii=False)}"

    except ValueError:
        return False, f"Unexpected response: {response.text}"

    except requests.HTTPError:
        try:
            error_data = response.json()
            return False, f"Facebook API error: {json.dumps(error_data, ensure_ascii=False)}"
        except Exception:
            return False, f"HTTP error: {response.text}"


def publish_text_to_facebook(
    message: str,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()

    url = f"https://graph.facebook.com/{page_config.graph_api_version}/{page_config.page_id}/feed"

    payload = {
        "message": message,
        "access_token": page_config.page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_image_to_facebook(
    message: str,
    media_path: str,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()
    url = f"https://graph.facebook.com/{page_config.graph_api_version}/{page_config.page_id}/photos"
    normalized_media_path = normalize_media_path(media_path)
    payload = {
        "caption": message,
        "access_token": page_config.page_access_token,
    }

    try:
        if is_remote_url(normalized_media_path):
            response = requests.post(url, data={**payload, "url": normalized_media_path}, timeout=60)
            return parse_facebook_response(response)

        with open(normalized_media_path, "rb") as media_file:
            response = requests.post(url, data=payload, files={"source": media_file}, timeout=120)
            return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def upload_unpublished_image_to_facebook(
    media_path: str,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()
    url = f"https://graph.facebook.com/{page_config.graph_api_version}/{page_config.page_id}/photos"
    normalized_media_path = normalize_media_path(media_path)
    payload = {
        "published": "false",
        "access_token": page_config.page_access_token,
    }

    try:
        if is_remote_url(normalized_media_path):
            response = requests.post(url, data={**payload, "url": normalized_media_path}, timeout=60)
            return parse_facebook_response(response)

        with open(normalized_media_path, "rb") as media_file:
            response = requests.post(url, data=payload, files={"source": media_file}, timeout=120)
            return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_images_to_facebook(
    message: str,
    media_paths: list[str],
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()

    if len(media_paths) == 1:
        return publish_image_to_facebook(message, media_paths[0], page_config)

    url = f"https://graph.facebook.com/{page_config.graph_api_version}/{page_config.page_id}/feed"
    uploaded_photo_ids = []

    for index, media_path in enumerate(media_paths, start=1):
        success, result = upload_unpublished_image_to_facebook(media_path, page_config)
        if not success:
            return False, f"Image {index} upload failed: {result}"
        uploaded_photo_ids.append(result)

    payload = {
        "message": message,
        "access_token": page_config.page_access_token,
    }
    for index, photo_id in enumerate(uploaded_photo_ids):
        payload[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})

    try:
        response = requests.post(url, data=payload, timeout=60)
        return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_video_to_facebook(
    message: str,
    media_path: str,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()
    url = f"https://graph-video.facebook.com/{page_config.graph_api_version}/{page_config.page_id}/videos"
    normalized_media_path = normalize_media_path(media_path)
    payload = {
        "description": message,
        "access_token": page_config.page_access_token,
    }

    try:
        if is_remote_url(normalized_media_path):
            response = requests.post(url, data={**payload, "file_url": normalized_media_path}, timeout=120)
            return parse_facebook_response(response)

        with open(normalized_media_path, "rb") as media_file:
            response = requests.post(url, data=payload, files={"source": media_file}, timeout=600)
            return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_first_comment_to_facebook(
    facebook_post_id: str,
    first_comment: str,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config()
    url = f"https://graph.facebook.com/{page_config.graph_api_version}/{facebook_post_id}/comments"
    payload = {
        "message": first_comment,
        "access_token": page_config.page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_to_facebook(
    message: str,
    media_path: MediaPathInput = None,
    media_type: Optional[str] = None,
    page_key: Optional[str] = None,
    page_config: Optional[FacebookPageConfig] = None,
) -> tuple[bool, str]:
    page_config = page_config or get_facebook_config(page_key)

    if not parse_media_paths(media_path):
        return publish_text_to_facebook(message, page_config)

    media_path, media_type = validate_media(media_path, media_type)
    media_paths = parse_media_paths(media_path)

    if media_type == "image":
        return publish_images_to_facebook(message, media_paths, page_config)

    if media_type == "video":
        return publish_video_to_facebook(message, media_paths[0], page_config)

    return False, f"Unsupported media type: {media_type}"


def publish_post_with_first_comment(post: sqlite3.Row) -> tuple[bool, str, Optional[str], Optional[str]]:
    first_comment = post["first_comment"]
    facebook_post_id = post["facebook_post_id"]
    page_config = get_facebook_config(post["page_key"])

    if facebook_post_id:
        post_success = True
        post_result = facebook_post_id
    else:
        post_success, post_result = publish_to_facebook(
            post["message"],
            post["media_path"],
            post["media_type"],
            page_config=page_config,
        )

    if not post_success:
        return False, post_result, None, None

    facebook_post_id = post_result
    if not first_comment or post["facebook_comment_id"]:
        return True, facebook_post_id, post["facebook_comment_id"], None

    comment_success, comment_result = publish_first_comment_to_facebook(
        facebook_post_id,
        first_comment,
        page_config,
    )
    if not comment_success:
        return False, comment_result, facebook_post_id, None

    return True, facebook_post_id, comment_result, None


def run_scheduler() -> None:
    interval = int(get_env("CHECK_INTERVAL_SECONDS", "30"))

    print("Scheduler running...")
    print(f"Checking every {interval} seconds")

    while True:
        publish_due_posts_once()

        time.sleep(interval)


def publish_due_posts_once(log=print) -> int:
    due_posts = get_due_posts()

    if due_posts:
        log(f"Found {len(due_posts)} due post(s)")

    for post in due_posts:
        page_label = post["page_name"] or post["page_key"] or "default page"
        log(f"Publishing post ID {post['id']} to {page_label}...")

        try:
            success, result, facebook_post_id, facebook_comment_id = publish_post_with_first_comment(post)
        except Exception as e:
            mark_post_failed(post["id"], str(e))
            log(f"Failed: {e}")
            continue

        if success:
            mark_post_success(post["id"], facebook_post_id, facebook_comment_id)
            log(f"Published successfully: {facebook_post_id}")
            if facebook_comment_id:
                log(f"First comment published successfully: {facebook_comment_id}")
        elif facebook_post_id:
            mark_first_comment_failed(post["id"], facebook_post_id, result)
            log(f"Post published, but first comment failed: {result}")
        else:
            mark_post_failed(post["id"], result)
            log(f"Failed: {result}")

    return len(due_posts)


def list_facebook_pages() -> None:
    for page in get_facebook_pages():
        print(f"{page.key}: {page.label}")


def pop_cli_option(args: list[str], option: str) -> Optional[str]:
    if option not in args:
        return None

    option_index = args.index(option)
    if option_index == len(args) - 1:
        raise ValueError(f"{option} must be followed by a value")

    value = args[option_index + 1]
    del args[option_index:option_index + 2]
    return value


def print_help() -> None:
    print("""
Commands:
  python app.py init
  python app.py add "Your message here" "2026-04-14 18:30:00"
  python app.py add "Your message here" "2026-04-14 18:30:00" --page page_2
  python app.py add "Your message here" "2026-04-14 18:30:00" --comment "First comment here"
  python app.py add "Caption here" "2026-04-14 18:30:00" media/photo.jpg
  python app.py add-image "Caption here" "2026-04-14 18:30:00" media/photo.jpg
  python app.py add-image "Caption here" "2026-04-14 18:30:00" media/photo-1.jpg media/photo-2.jpg
  python app.py add-video "Caption here" "2026-04-14 18:30:00" media/video.mp4
  python app.py list
  python app.py pages
  python app.py delete 1
  python app.py retry 1
  python app.py run
""")


def main() -> None:
    load_env_file()
    init_db()

    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    command = sys.argv[1].lower()

    try:
        if command == "init":
            print("Database initialized.")

        elif command == "add":
            if len(sys.argv) < 4:
                print('Example: python app.py add "My post text" "2026-04-14 18:30:00"')
                print('Example with media: python app.py add "My caption" "2026-04-14 18:30:00" media/photo.jpg')
                print('Example with multiple images: python app.py add "My caption" "2026-04-14 18:30:00" media/photo-1.jpg media/photo-2.jpg')
                print('Example with first comment: python app.py add "My post text" "2026-04-14 18:30:00" --comment "First comment"')
                sys.exit(1)

            message = sys.argv[2]
            scheduled_at = sys.argv[3]
            args = sys.argv[4:]
            page_key = pop_cli_option(args, "--page")
            first_comment = pop_cli_option(args, "--comment")
            media_path = args if len(args) > 1 else (args[0] if args else None)
            add_post(message, scheduled_at, media_path, first_comment=first_comment, page_key=page_key)
            print("Post added.")

        elif command == "add-image":
            if len(sys.argv) < 5:
                print('Example: python app.py add-image "My caption" "2026-04-14 18:30:00" media/photo.jpg')
                print('Example with multiple images: python app.py add-image "My caption" "2026-04-14 18:30:00" media/photo-1.jpg media/photo-2.jpg')
                sys.exit(1)

            args = sys.argv[4:]
            page_key = pop_cli_option(args, "--page")
            if not args:
                raise ValueError("add-image requires at least one media path")
            media_path = args if len(args) > 1 else args[0]
            add_post(sys.argv[2], sys.argv[3], media_path, "image", page_key=page_key)
            print("Image post added.")

        elif command == "add-video":
            if len(sys.argv) < 5:
                print('Example: python app.py add-video "My caption" "2026-04-14 18:30:00" media/video.mp4')
                sys.exit(1)

            args = sys.argv[4:]
            page_key = pop_cli_option(args, "--page")
            if len(args) != 1:
                raise ValueError("add-video requires one media path")
            add_post(sys.argv[2], sys.argv[3], args[0], "video", page_key=page_key)
            print("Video post added.")

        elif command == "list":
            list_posts()

        elif command == "pages":
            list_facebook_pages()

        elif command == "delete":
            if len(sys.argv) < 3:
                print("Example: python app.py delete 1")
                sys.exit(1)

            delete_post(int(sys.argv[2]))
            print("Post deleted.")

        elif command == "retry":
            if len(sys.argv) < 3:
                print("Example: python app.py retry 1")
                sys.exit(1)

            retry_post(int(sys.argv[2]))
            print("Post marked for retry.")

        elif command == "run":
            run_scheduler()

        else:
            print_help()
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
