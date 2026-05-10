# LinkedIn AI Agent 🤖

Fully automated LinkedIn post pipeline using **Gemini AI + FastAPI + APScheduler**, deployed on **Render** (free tier).

Every Wednesday and Thursday at 9:00 AM IST, the agent:
1. Scrapes latest AI news headlines (RSS feeds)
2. Gemini picks the best topic for your persona
3. Gemini writes an engaging LinkedIn post
4. Sends you an approval email with a one-click **Approve & Post** button
5. On approval → posts directly to LinkedIn via official API

---

## Project Structure

```
linkedin_agent/
├── main.py                    # FastAPI app + scheduler + all routes
├── config.py                  # All config & dummy credentials
├── requirements.txt
├── render.yaml                # Render deployment config
├── .env.example               # Environment variable template
├── linkedin_token.json        # Created after OAuth (gitignore this!)
├── pending_approvals.json     # Active approval tokens
└── agents/
    ├── topic_agent.py         # Agent 1: RSS scrape + Gemini topic pick
    ├── post_agent.py          # Agent 2: Gemini post generation
    ├── email_agent.py         # Agent 3: Approval email sender
    └── linkedin_agent.py      # Agent 4: LinkedIn OAuth + posting
```

---

## Setup Guide

### 1. Clone & install locally

```bash
git clone <your-repo>
cd linkedin_agent
pip install -r requirements.txt
```

### 2. Set up credentials

Copy `.env.example` to `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → API Keys (free) |
| `LINKEDIN_CLIENT_ID` | [developer.linkedin.com/apps](https://developer.linkedin.com/apps) |
| `LINKEDIN_CLIENT_SECRET` | Same LinkedIn app → Auth tab |
| `LINKEDIN_REDIRECT_URI` | `https://your-app.onrender.com/auth/callback` |
| `SENDER_EMAIL` | Your Gmail address |
| `SENDER_PASS` | Gmail → Settings → App Passwords (16-char code) |
| `APPROVAL_EMAIL` | Email where you receive approval requests |
| `APP_BASE_URL` | Your Render app URL |
| `SECRET_KEY` | Any random 32-char string |

### 3. LinkedIn Developer App setup

1. Go to [developer.linkedin.com/apps](https://developer.linkedin.com/apps)
2. Create app → fill name, attach your LinkedIn page
3. Products tab → request **"Share on LinkedIn"** (instant approval)
4. Auth tab → add redirect URI: `https://your-app.onrender.com/auth/callback`
5. Copy Client ID + Client Secret → paste in `.env`

### 4. Run locally (dummy mode)

```bash
uvicorn main:app --reload
# Open http://localhost:8000
```

In dummy mode (no real credentials), everything runs but:
- RSS fallback to hardcoded headlines
- Gemini returns a sample post
- Email prints to console instead of sending
- LinkedIn prints instead of posting

### 5. Connect LinkedIn (one-time OAuth)

After deploying to Render with real credentials:
```
https://your-app.onrender.com/auth/linkedin
```
Click Allow in browser → token saved → you're connected forever.

### 6. Deploy to Render

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New Web Service → connect repo
3. Add all environment variables from `.env.example`
4. Deploy → get your URL
5. Update `LINKEDIN_REDIRECT_URI` and `APP_BASE_URL` to your Render URL

---

## How approval works

```
Pipeline runs → Email sent with "Approve & Post" button
                                        ↓
                        You click the button in your email
                                        ↓
                GET /approve/{token} → LinkedIn API → Post live!
```

The token is single-use and stored in `pending_approvals.json`.
If you ignore the email, nothing is posted.

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/` | Dashboard UI |
| GET | `/health` | Render health check |
| POST | `/run` | Manually trigger pipeline |
| GET | `/approve/{token}` | Approve & post (from email link) |
| GET | `/auth/linkedin` | Start LinkedIn OAuth |
| GET | `/auth/callback` | LinkedIn OAuth callback |
| GET | `/status` | JSON status + run log |

---

## Schedule

Runs every **Wednesday and Thursday at 9:00 AM IST** (03:30 UTC).
To change, edit in `config.py`:
```python
SCHEDULE_DAYS = ["wed", "thu"]
SCHEDULE_HOUR_UTC = 3
SCHEDULE_MINUTE_UTC = 30
```

---

## Replace dummy values

Search for `DUMMY` in `config.py` — every one of those needs a real value
before going to production. Or set them as environment variables on Render.
