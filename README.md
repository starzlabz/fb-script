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

## Initialize database
python app.py init

## Add a post
python app.py add "Hello Facebook" "2026-04-14 18:30:00"

## List post
python app.py list

## Delete a post
python app.py delete 1

## Retry a failed post
python app.py retry 1

## Run Scheduler
python app.py run
