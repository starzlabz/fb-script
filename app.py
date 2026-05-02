import os
import sys
import json
import time
import sqlite3
import warnings
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "scheduler.db")
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".wmv"}
MEDIA_TYPES = {"image", "video"}


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

            if key and key not in os.environ:
                os.environ[key] = value


def validate_facebook_config(page_access_token: str) -> None:
    if page_access_token.lower().startswith("bearer "):
        raise ValueError("PAGE_ACCESS_TOKEN should contain only the token, without 'Bearer '")

    if any(ch.isspace() for ch in page_access_token):
        raise ValueError("PAGE_ACCESS_TOKEN contains whitespace; keep the token on one line in .env")


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


def validate_media(media_path: Optional[str], media_type: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if media_path is None:
        if media_type:
            raise ValueError("Media type was provided without a media path")
        return None, None

    media_path = media_path.strip()
    normalized_media_type = media_type.strip().lower() if media_type else detect_media_type(media_path)

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
    media_path: Optional[str] = None,
    media_type: Optional[str] = None,
    first_comment: Optional[str] = None,
) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    message = message.strip()
    if not message and not media_path:
        raise ValueError("Add a message or media file for the post")

    media_path, media_type = validate_media(media_path, media_type)
    first_comment = first_comment.strip() if first_comment and first_comment.strip() else None

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO scheduled_posts (message, scheduled_at, media_path, media_type, first_comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
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
        SELECT id, message, scheduled_at, media_path, media_type, first_comment, status,
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
        print(f"Message: {row['message']}")
        if row["media_path"]:
            print(f"Media: {row['media_type']} - {row['media_path']}")
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


def get_facebook_config() -> tuple[str, str, str]:
    page_id = get_env("PAGE_ID")
    page_access_token = get_env("PAGE_ACCESS_TOKEN")
    graph_api_version = get_env("GRAPH_API_VERSION", "v25.0")
    validate_facebook_config(page_access_token)
    return page_id, page_access_token, graph_api_version


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


def publish_text_to_facebook(message: str) -> tuple[bool, str]:
    page_id, page_access_token, graph_api_version = get_facebook_config()

    url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/feed"

    payload = {
        "message": message,
        "access_token": page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_image_to_facebook(message: str, media_path: str) -> tuple[bool, str]:
    page_id, page_access_token, graph_api_version = get_facebook_config()
    url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/photos"
    normalized_media_path = normalize_media_path(media_path)
    payload = {
        "caption": message,
        "access_token": page_access_token,
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


def publish_video_to_facebook(message: str, media_path: str) -> tuple[bool, str]:
    page_id, page_access_token, graph_api_version = get_facebook_config()
    url = f"https://graph-video.facebook.com/{graph_api_version}/{page_id}/videos"
    normalized_media_path = normalize_media_path(media_path)
    payload = {
        "description": message,
        "access_token": page_access_token,
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


def publish_first_comment_to_facebook(facebook_post_id: str, first_comment: str) -> tuple[bool, str]:
    _, page_access_token, graph_api_version = get_facebook_config()
    url = f"https://graph.facebook.com/{graph_api_version}/{facebook_post_id}/comments"
    payload = {
        "message": first_comment,
        "access_token": page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        return parse_facebook_response(response)

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def publish_to_facebook(
    message: str,
    media_path: Optional[str] = None,
    media_type: Optional[str] = None,
) -> tuple[bool, str]:
    if not media_path:
        return publish_text_to_facebook(message)

    media_path, media_type = validate_media(media_path, media_type)
    if media_type == "image":
        return publish_image_to_facebook(message, media_path)

    if media_type == "video":
        return publish_video_to_facebook(message, media_path)

    return False, f"Unsupported media type: {media_type}"


def publish_post_with_first_comment(post: sqlite3.Row) -> tuple[bool, str, Optional[str], Optional[str]]:
    first_comment = post["first_comment"]
    facebook_post_id = post["facebook_post_id"]

    if facebook_post_id:
        post_success = True
        post_result = facebook_post_id
    else:
        post_success, post_result = publish_to_facebook(
            post["message"],
            post["media_path"],
            post["media_type"],
        )

    if not post_success:
        return False, post_result, None, None

    facebook_post_id = post_result
    if not first_comment or post["facebook_comment_id"]:
        return True, facebook_post_id, post["facebook_comment_id"], None

    comment_success, comment_result = publish_first_comment_to_facebook(facebook_post_id, first_comment)
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
        log(f"Publishing post ID {post['id']}...")

        success, result, facebook_post_id, facebook_comment_id = publish_post_with_first_comment(post)

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


def print_help() -> None:
    print("""
Commands:
  python app.py init
  python app.py add "Your message here" "2026-04-14 18:30:00"
  python app.py add "Your message here" "2026-04-14 18:30:00" --comment "First comment here"
  python app.py add "Caption here" "2026-04-14 18:30:00" media/photo.jpg
  python app.py add-image "Caption here" "2026-04-14 18:30:00" media/photo.jpg
  python app.py add-video "Caption here" "2026-04-14 18:30:00" media/video.mp4
  python app.py list
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
                print('Example with first comment: python app.py add "My post text" "2026-04-14 18:30:00" --comment "First comment"')
                sys.exit(1)

            message = sys.argv[2]
            scheduled_at = sys.argv[3]
            args = sys.argv[4:]
            first_comment = None
            if "--comment" in args:
                comment_index = args.index("--comment")
                if comment_index == len(args) - 1:
                    raise ValueError("--comment must be followed by comment text")
                first_comment = args[comment_index + 1]
                del args[comment_index:comment_index + 2]
            media_path = args[0] if args else None
            add_post(message, scheduled_at, media_path, first_comment=first_comment)
            print("Post added.")

        elif command == "add-image":
            if len(sys.argv) < 5:
                print('Example: python app.py add-image "My caption" "2026-04-14 18:30:00" media/photo.jpg')
                sys.exit(1)

            add_post(sys.argv[2], sys.argv[3], sys.argv[4], "image")
            print("Image post added.")

        elif command == "add-video":
            if len(sys.argv) < 5:
                print('Example: python app.py add-video "My caption" "2026-04-14 18:30:00" media/video.mp4')
                sys.exit(1)

            add_post(sys.argv[2], sys.argv[3], sys.argv[4], "video")
            print("Video post added.")

        elif command == "list":
            list_posts()

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
