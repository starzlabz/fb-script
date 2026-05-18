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

For source/development runs, the app creates a blank `.env` file in the project root if it is missing. You can also fill it manually:

```env
PAGE_ID=123456789012345
PAGE_ACCESS_TOKEN=EAAB...
GRAPH_API_VERSION=v25.0
CHECK_INTERVAL_SECONDS=30
```

Use a Facebook Page access token only. Paste just the token value, without `Bearer`, quotes, spaces, or inline comments.

Packaged desktop builds create and use a writable `.env` file outside the app bundle:

- Windows: `%LOCALAPPDATA%\FacebookPageScheduler\.env`
- macOS: `~/Library/Application Support/FacebookPageScheduler/.env`
- Linux: `~/.local/share/FacebookPageScheduler/.env`

The SQLite database is stored beside that config folder under `data/scheduler.db`. Do not ship your personal `.env` with real tokens; let the app create a blank one for each user.

To connect pages through Facebook Login from the desktop app, enable **Login from devices** in your Meta app and add your app credentials or enter them when the app asks:

```env
FACEBOOK_APP_ID=1234567890
FACEBOOK_CLIENT_TOKEN=your_client_token
```

No localhost redirect URI is needed for the device-login flow. The default login scopes are `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`. If you need video publishing or comment management, set `FACEBOOK_LOGIN_SCOPES` with the additional approved permissions.

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

If your first page still uses the original `PAGE_ID` and `PAGE_ACCESS_TOKEN` names, you can label it with `PAGE_1_KEY` and `PAGE_1_NAME`. Add additional pages with `PAGE_2_ID`, `PAGE_2_ACCESS_TOKEN`, and so on.

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

Use **Connect Facebook** beside the Facebook Page picker to log in, select a Page, and save its Page access token automatically.

## Build Desktop App
Build Windows packages on Windows and macOS packages on macOS:

```bash
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name FacebookPageScheduler desktop.py
```

Send the generated `dist/FacebookPageScheduler` folder on Windows or `dist/FacebookPageScheduler.app` on macOS. On first launch, the app creates a blank writable `.env` for that user and saves tokens there through the UI.

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
