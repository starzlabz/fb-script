# Facebook Page Scheduler

Simple Python tool for scheduling Facebook page posts using SQLite and the Meta Graph API.

## Features
- Schedule Facebook page posts locally
- Attach one or more images, or one video, to a scheduled post
- Store posts in SQLite
- Publish automatically when due
- Retry failed posts

## Tech
- Python
- PySide6 desktop UI
- SQLite
- Requests
- Meta Graph API

## Setup
```bash
git clone https://github.com/endrithiseni1/fb-script.git
cd fb-script
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
PAGE_ID=123456789012345
PAGE_ACCESS_TOKEN=EAAB...
GRAPH_API_VERSION=v25.0
CHECK_INTERVAL_SECONDS=30
```

Use a Facebook Page access token only. Paste just the token value, without `Bearer`, quotes, spaces, or inline comments.

For multiple pages, keep the single-page variables above for the default page or use numbered page entries:

```env
PAGE_1_KEY=main
PAGE_1_NAME=Main Page
PAGE_1_ID=123456789012345
PAGE_1_ACCESS_TOKEN=EAAB...

PAGE_2_KEY=shop
PAGE_2_NAME=Shop Page
PAGE_2_ID=987654321098765
PAGE_2_ACCESS_TOKEN=EAAB...
```

The desktop app shows these pages in a page picker. In the CLI, pass `--page main`, `--page shop`, or another configured key/name/page ID.

## Initialize Database
```bash
python app.py init
```

## Open Desktop App
```bash
python desktop.py
```

On macOS, you can also double-click `run_desktop.command`.
On Windows, you can double-click `run_desktop.bat`.

## Add A Post
```bash
python app.py add "Hello Facebook" "2026-04-14 18:30:00"
```

To target a specific configured page:

```bash
python app.py add "Hello Facebook" "2026-04-14 18:30:00" --page shop
```

To publish a first comment right after the post:

```bash
python app.py add "Hello Facebook" "2026-04-14 18:30:00" --comment "First comment"
```

## Add An Image Post
Use one or more local file paths or public `https://` image URLs.

```bash
python app.py add-image "Photo caption" "2026-04-14 18:30:00" media/photo.jpg
```

Multiple images are published as one multi-photo Facebook post:

```bash
python app.py add-image "Photo caption" "2026-04-14 18:30:00" media/photo-1.jpg media/photo-2.jpg
```

You can also let the scheduler detect the media type from the file extension:

```bash
python app.py add "Photo caption" "2026-04-14 18:30:00" media/photo.jpg
```

For multiple images with the desktop app, select more than one image in the file picker or enter one path or URL per line. Videos remain single-file posts.

First comments require a Page token that can manage Page engagement.

## Add A Video Post
Use a local file path or a public `https://` video URL.

```bash
python app.py add-video "Video caption" "2026-04-14 18:30:00" media/video.mp4
```

## List Posts
```bash
python app.py list
```

## List Facebook Pages
```bash
python app.py pages
```

## Delete A Post
```bash
python app.py delete 1
```

## Retry A Failed Post
```bash
python app.py retry 1
```

## Run Scheduler
```bash
python app.py run
```
