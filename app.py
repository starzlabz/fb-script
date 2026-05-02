import os
import sys
import json
import time
import sqlite3
import warnings
from datetime import datetime
from typing import Optional

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "scheduler.db")


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
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            published_at TEXT,
            facebook_post_id TEXT,
            error_message TEXT
        )
    """)

    conn.commit()
    conn.close()


def validate_datetime(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def add_post(message: str, scheduled_at: str) -> None:
    if not validate_datetime(scheduled_at):
        raise ValueError("Date must be in format: YYYY-MM-DD HH:MM:SS")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO scheduled_posts (message, scheduled_at, created_at)
        VALUES (?, ?, ?)
    """, (
        message,
        scheduled_at,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))

    conn.commit()
    conn.close()


def list_posts() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, message, scheduled_at, status, published_at, facebook_post_id, error_message
        FROM scheduled_posts
        ORDER BY scheduled_at ASC
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No scheduled posts found.")
        return

    for row in rows:
        print("-" * 80)
        print(f"ID: {row['id']}")
        print(f"Message: {row['message']}")
        print(f"Scheduled At: {row['scheduled_at']}")
        print(f"Status: {row['status']}")
        print(f"Published At: {row['published_at']}")
        print(f"Facebook Post ID: {row['facebook_post_id']}")
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


def mark_post_success(post_id: int, facebook_post_id: Optional[str]) -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE scheduled_posts
        SET status = 'published',
            published_at = ?,
            facebook_post_id = ?,
            error_message = NULL
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        facebook_post_id,
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


def publish_to_facebook(message: str) -> tuple[bool, str]:
    page_id = get_env("PAGE_ID")
    page_access_token = get_env("PAGE_ACCESS_TOKEN")
    graph_api_version = get_env("GRAPH_API_VERSION", "v25.0")
    validate_facebook_config(page_access_token)

    url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/feed"

    payload = {
        "message": message,
        "access_token": page_access_token,
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "id" in data:
            return True, data["id"]

        return False, f"Unexpected response: {json.dumps(data, ensure_ascii=False)}"

    except requests.HTTPError:
        try:
            error_data = response.json()
            return False, f"Facebook API error: {json.dumps(error_data, ensure_ascii=False)}"
        except Exception:
            return False, f"HTTP error: {response.text}"

    except requests.RequestException as e:
        return False, f"Request failed: {str(e)}"


def run_scheduler() -> None:
    interval = int(get_env("CHECK_INTERVAL_SECONDS", "30"))

    print("Scheduler running...")
    print(f"Checking every {interval} seconds")

    while True:
        due_posts = get_due_posts()

        if due_posts:
            print(f"Found {len(due_posts)} due post(s)")

        for post in due_posts:
            print(f"Publishing post ID {post['id']}...")

            success, result = publish_to_facebook(post["message"])

            if success:
                mark_post_success(post["id"], result)
                print(f"Published successfully: {result}")
            else:
                mark_post_failed(post["id"], result)
                print(f"Failed: {result}")

        time.sleep(interval)


def print_help() -> None:
    print("""
Commands:
  python app.py init
  python app.py add "Your message here" "2026-04-14 18:30:00"
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
                sys.exit(1)

            message = sys.argv[2]
            scheduled_at = sys.argv[3]
            add_post(message, scheduled_at)
            print("Post added.")

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
