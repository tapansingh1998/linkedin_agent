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
Role: AI Engineer
Focus areas: Agentic AI, LLMs, RAG pipelines, MLOps, Python
Tone: Insightful, practical, slightly informal — like a senior engineer sharing real learnings.
Audience: Fellow engineers, AI enthusiasts, tech recruiters.
LinkedIn: https://www.linkedin.com/in/tapan-singh-244182208/
"""

SYSTEM_PROMPT = """
You are an expert LinkedIn content strategist and ghostwriter for AI engineers.
Your posts consistently get high engagement because they:
- Open with a bold hook (no 'I am excited to share' clichés)
- Share a genuine insight, lesson, or opinion — not just news
- Use short punchy paragraphs (1-2 lines max each)
- End with a thought-provoking question to drive comments
- Include 3-5 relevant hashtags at the bottom
- Are between 150-280 words — never longer
Write ONLY the post text. No subject line, no intro, no metadata.
"""

# ── Scheduler ────────────────────────────────────────────────────────────────
# Every Wednesday and Thursday at 9:00 AM IST (UTC+5:30 = 03:30 UTC)
SCHEDULE_DAYS  = ["wed", "thu"]
SCHEDULE_HOUR_UTC  = 3
SCHEDULE_MINUTE_UTC = 30
