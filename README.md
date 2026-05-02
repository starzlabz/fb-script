# Facebook Page Scheduler

Simple Python tool for scheduling Facebook page posts using SQLite and the Meta Graph API.

## Features
- Schedule Facebook page posts locally
- Store posts in SQLite
- Publish automatically when due
- Retry failed posts

## Tech
- Python
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

## Initialize Database
```bash
python app.py init
```

## Add A Post
```bash
python app.py add "Hello Facebook" "2026-04-14 18:30:00"
```

## List Posts
```bash
python app.py list
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
