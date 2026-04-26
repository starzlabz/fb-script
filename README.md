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
- Playwright
- Meta Graph API

## Setup
```bash
git clone https://github.com/endrithiseni1/fb-script.git
cd fb-script
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Create a `.env` file in the project root:

```env
PAGE_ID=123456789012345
PAGE_ACCESS_TOKEN=EAAB...
GRAPH_API_VERSION=v25.0
CHECK_INTERVAL_SECONDS=30
BOT_URL=https://www.facebook.com/
BOT_SEND_INVITE_URL=https://www.facebook.com/profile.php?id=POSTING_PAGE_ID
BOT_ACCEPT_INVITE_URL=https://www.facebook.com/profile.php?id=ACCEPTING_PAGE_ID
BOT_SEND_INVITE_PROFILE_NAME=BlicAlb
BOT_ACCEPT_INVITE_PROFILE_NAME=Strana 2
BOT_BUTTONS=["Accept all","css=button.submit"]
BOT_LOGIN_URL=https://www.facebook.com/
BOT_PROFILE_DIR=data/browser-profile
BOT_HEADLESS=false
BOT_STAY_OPEN=true
BOT_SLOW_MO_MS=250
BOT_TIMEOUT_MS=15000
BOT_AFTER_CLICK_MS=1500
BOT_SWITCH_PROMPT_TIMEOUT_MS=8000
```

Use a Facebook Page access token only. Paste just the token value, without `Bearer`, quotes, spaces, or inline comments.

## Initialize database
```bash
python app.py init
```

## Add a post
```bash
python app.py add "Hello Facebook" "2026-04-14 18:30:00"
```

## List post
```bash
python app.py list
```

## Delete a post
```bash
python app.py delete 1
```

## Retry a failed post
```bash
python app.py retry 1
```

## Run Scheduler
```bash
python app.py run
```

## Schedule Collaboration Invite Post
Browser-based collaboration posts are scheduled separately from Graph API posts because the invite is created through Facebook's UI.

Set `BOT_SEND_INVITE_URL` to the Page URL that creates the post, and set `BOT_ACCEPT_INVITE_URL` to the other Page URL that accepts the collaboration invite. New scheduled browser jobs save the flow-specific URL, so the bot starts on the correct Page instead of switching profiles mid-flow.

If Facebook shows a Page confirmation pop-up after opening one of those URLs, keep `"switch-profile-if-present=Page Name"` as the first flow step. It waits for the `Switch profiles` dialog, clicks the blue `Switch` button when it appears, and confirms the active Page before continuing. The scheduler also adds this step automatically for `send-invite` and `accept-invite` when a flow-specific URL and profile name are configured.

Schedule a collaboration post using `BOT_SEND_INVITE_BUTTONS`:

```bash
python app.py schedule-send-invite "Hello collaborator" "2026-04-14 18:30:00"
```

Then keep the scheduler running:

```bash
python app.py run
```

You can also schedule a saved bot flow directly:

```bash
python app.py schedule-bot-flow send-invite "2026-04-14 18:30:00"
python app.py schedule-accept-invite "2026-04-14 18:45:00"
```

Manage scheduled browser jobs:

```bash
python app.py list-bot-flows
python app.py delete-bot-flow 1
python app.py retry-bot-flow 1
python app.py clear-bot-flows
python app.py rebuild-send-invite 1 "2026-04-14 18:30:00"
```

If you already scheduled jobs before changing the URLs, the scheduler will use the new flow-specific URL at run time. Delete and schedule them again, or rebuild the send-invite job, only if you want the saved database row itself to be rewritten.

Scheduled browser jobs reuse `BOT_PROFILE_DIR`, so run `python app.py bot-login` first and keep the machine awake at the scheduled time.

## Run Browser Bot
If the site requires login, log in once first:

```bash
python app.py bot-login
```

A browser opens. Log in manually, finish any two-factor checks, then press Enter in the terminal. The session is saved in `BOT_PROFILE_DIR`, so future bot runs reuse it.

```bash
python app.py bot "https://example.com" "Accept all" "css=button.submit"
```

The first argument is the URL. Every following argument is clicked in order.

Click targets can be:
- Button text: `"Accept all"`
- Visible text: `"text=Continue"`
- Partial visible text: `"text-partial=What's on your mind"`
- Last visible text match: `"text-last=Strana 2"`
- Top-right Facebook profile menu: `"profile-menu"`
- Ensure Facebook is using a profile/page when a direct URL is not enough: `"ensure-profile=Strana 2"`
- Stop unless Facebook is using a profile/page: `"require-profile=Strana 2"`
- Switch into the Page from Facebook's Manage Page screen when needed: `"page-switch=BlicAlb"`
- Click Facebook's Page `Switch profiles` pop-up if it appears: `"switch-profile-if-present=BlicAlb"`
- Open Facebook's post composer using several possible Page UI labels: `"facebook-composer"`
- Navigate to a URL: `"go=https://www.facebook.com/"`
- Facebook add-collaborator icon: `"collaborator-icon"`
- Accept invite only when an Accept button is visible: `"accept-invite-if-present"`
- Optional click that skips failures: `"optional=text=Not now"`
- Viewport coordinate: `"xy=1240,28"`
- Wait for an element: `"wait=text=Invite collaborators"`
- Pause for milliseconds: `"wait-ms=3000"`
- Fill a field: `"fill=placeholder=Search|Collab Strana"`
- Type into a field: `"type=css=input[role='combobox']|Collab Strana"`
- Press a key: `"press=Enter"` or `"press=css=input[role='combobox']|Enter"`
- Upload a file: `"upload=css=input[type='file']|media/video.mp4"`
- CSS selector: `"css=button.submit"`
- Last matching CSS selector: `"css-last=[aria-label='Account Controls and Settings']"`
- XPath selector: `"xpath=//button[contains(., 'Save')]"`
- ARIA role and name: `"role=button:Save"`
- Test id: `"testid=submit-button"`

Example shape for sending a collaboration invite through the browser UI:

```env
BOT_SEND_INVITE_URL=https://www.facebook.com/profile.php?id=POSTING_PAGE_ID
BOT_SEND_INVITE_PROFILE_NAME=BlicAlb
BOT_SEND_INVITE_BUTTONS=["switch-profile-if-present=BlicAlb","text=Professional dashboard","text=Create post","upload=css=input[type='file']|media/reel.mp4","text=Invite collaborators","fill=placeholder=Search|Collab Strana","text=Collab Strana","text=Done","text=Publish"]
```

Example shape for the Facebook text-post collaboration flow:

```env
BOT_SEND_INVITE_URL=https://www.facebook.com/profile.php?id=POSTING_PAGE_ID
BOT_SEND_INVITE_PROFILE_NAME=BlicAlb
BOT_SEND_INVITE_BUTTONS=["switch-profile-if-present=BlicAlb","facebook-composer","type=facebook-composer|Hello collaborator","collaborator-icon","fill=placeholder=Add collaborator|strana 2","text=Strana 2","text=Done","text=Next","text=Post","optional=text=Not now"]
```

Example shape for accepting the invite from the other Page:

```env
BOT_ACCEPT_INVITE_URL=https://www.facebook.com/profile.php?id=ACCEPTING_PAGE_ID
BOT_ACCEPT_INVITE_PROFILE_NAME=Strana 2
BOT_ACCEPT_INVITE_BUTTONS=["switch-profile-if-present=Strana 2","text=Professional dashboard","text=All tools","text=Collaborations","accept-invite-if-present"]
```

The exact labels/selectors depend on the Meta screen you see, so use Inspect or screenshots to adjust the field target after each failed step.

You can also configure the bot from `.env` with `BOT_URL` and `BOT_BUTTONS`, then run:

```bash
python app.py bot
```

You can also run the saved collaboration flows:

```bash
python app.py bot-send-invite
python app.py bot-accept-invite
```

`bot-send-invite` opens `BOT_SEND_INVITE_URL`. `bot-accept-invite` opens `BOT_ACCEPT_INVITE_URL`. If either one is missing, the bot falls back to `BOT_URL`.

If a click fails, the bot saves `data/bot-error.png` so you can see what was visible when it got stuck.
