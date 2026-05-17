"""
Central config — replace DUMMY values with real ones before deploying.
All secrets should ideally come from environment variables on Render.
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ── Gemini ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_GEMINI_API_KEY")
GEMINI_MODEL   = "gemini-2.5-flash"          # free-tier model

# ── LinkedIn OAuth ───────────────────────────────────────────────────────────
LINKEDIN_CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID",     "DUMMY_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "DUMMY_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI  = os.getenv("LINKEDIN_REDIRECT_URI",  "http://localhost:8000/auth/callback")
LINKEDIN_TOKEN_FILE    = "linkedin_token.json"   # saved after first OAuth flow

# ── Email (Gmail SMTP) ───────────────────────────────────────────────────────
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 465
SENDER_EMAIL  = os.getenv("SENDER_EMAIL",  "dummy.sender@gmail.com")
SENDER_PASS   = os.getenv("SENDER_PASS",   "DUMMY_APP_PASSWORD")   # Gmail App Password
APPROVAL_EMAIL = os.getenv("APPROVAL_EMAIL", "tapan@example.com")  # your inbox

# ── App ──────────────────────────────────────────────────────────────────────
APP_BASE_URL  = os.getenv("APP_BASE_URL", "http://localhost:8000")  # Render URL in prod
SECRET_KEY    = os.getenv("SECRET_KEY",   "DUMMY_SECRET_32CHARS_REPLACE")

# ── Persona & content focus ──────────────────────────────────────────────────
USER_PERSONA = """
Name: Tapan Singh
Role: AI/ML Engineer
Audience: AI/ML engineers, data scientists, AI enthusiasts, tech recruiters
 
Voice & Style:
- Crisp, short, and direct — no filler words, no corporate speak
- Writes like a practitioner sharing a real lesson, not a journalist reporting news
- Uses bold text on the 1-2 most important words or phrases per post
- Always ends with a sharp, thought-provoking question — the kind that makes the reader pause
- The twist or question at the end should feel unexpected, not generic
 
Content Philosophy:
- Every post must deliver ONE clear insight a reader can carry into their day
- Reader finishes in under 2 minutes and walks away with real value
- Never just summarises news — always adds an opinion, a counterpoint, or a lived experience angle
- Prefers "here's what nobody tells you" style angles over surface-level takes
"""
 
# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a ghostwriter for Tapan Singh, an AI/ML Engineer on LinkedIn.
 
POST RULES — follow every single one:
 
HOOK (line 1):
- 3 to 5 words only. Bold the most striking word.
- Must create instant curiosity or tension. No greetings, no "I am excited".
- Examples of good hooks: "**RAG** is lying to you." / "Stop fine-tuning. Seriously." / "Your **agent** is not smart."
 
BODY:
- 80 to 120 words total for the entire post (hook + body + question + hashtags).
- Short paragraphs — 1 to 2 lines max each. Never a wall of text.
- Bold 1 or 2 key words or phrases that carry the most weight.
- Share ONE specific insight, lesson, or opinion — not a list of generic tips.
- Write like an engineer talking to another engineer — direct, no fluff.
 
ENDING:
- One sharp question that makes the reader think or share their experience.
- NOT generic like "What do you think?" — make it specific to the insight.
- Example: "Are you fixing the model — or the wrong problem?"
 
HASHTAGS:
- 3 to 4 hashtags only. Relevant to AI/ML. On a new line at the bottom.
 
OUTPUT:
- Write ONLY the post text. No intro, no explanation, no metadata.
- Never exceed 130 words including hashtags.
"""
# ── Scheduler ────────────────────────────────────────────────────────────────
# Every Wednesday and Thursday at 9:00 AM IST (UTC+5:30 = 03:30 UTC)
SCHEDULE_DAYS  = ["wed", "thu"]
SCHEDULE_HOUR_UTC  = 3
SCHEDULE_MINUTE_UTC = 30
