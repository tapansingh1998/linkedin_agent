"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      LinkedIn Studio PRO v4.2 — FastAPI Backend (Render-Ready)              ║
║   Supabase · OAuth · AI Topics · AI Campaign · SMTP Approval Email          ║
╚══════════════════════════════════════════════════════════════════════════════╝

EMAIL FLOW (SMTP — works with Gmail, Outlook, any SMTP server):
  AI Campaign creates scheduled jobs
  → Scheduler fires 24h before each post
  → SMTP sends approval email with post variations + images
  → User clicks "Approve" in email → post published to LinkedIn instantly
"""

import os, json, time, threading, random, uuid, secrets
import urllib.parse, re, math
from pathlib import Path
from contextlib import asynccontextmanager
from html import escape
from typing import Optional, List, Dict, Any
import datetime, tempfile

from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("li_studio")

import requests as http_requests

# ── SMTP Email (standard library + email libraries) ─────────────────────────────
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
HAS_SMTP = True  # Built-in, always available
HAS_RESEND = False  # Resend SDK not used; all email goes through SMTP


# ── Gemini ─────────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-generativeai not installed")

# ── Pillow ─────────────────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
CONFIG = {
    "LINKEDIN_CLIENT_ID":     os.environ.get("LINKEDIN_CLIENT_ID", ""),
    "LINKEDIN_CLIENT_SECRET": os.environ.get("LINKEDIN_CLIENT_SECRET", ""),
    "LINKEDIN_REDIRECT_URI":  os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/callback"),
    "LINKEDIN_SCOPES":        os.environ.get("LINKEDIN_SCOPES", "openid profile w_member_social email"),
    "GEMINI_MODEL":           os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
    "PIXABAY_API_KEY":        os.environ.get("PIXABAY_API_KEY", ""),
    "PEXELS_API_KEY":         os.environ.get("PEXELS_API_KEY", ""),
    "CACHE_DIR":              os.environ.get("CACHE_DIR", "li_cache"),
    "SCHEDULED_IMAGES_DIR":   os.environ.get("SCHEDULED_IMAGES_DIR", "scheduled_images"),
    "PORT":                   int(os.environ.get("PORT", 8000)),
    "APP_BASE_URL":           os.environ.get("APP_BASE_URL", "http://localhost:8000"),
    # How many hours before scheduled post to send approval email
    # Set to 0 to send email immediately when a post is scheduled
    "APPROVAL_LEAD_HOURS":    int(os.environ.get("APPROVAL_LEAD_HOURS", 720)),  # 30 days default
    # ── SMTP Configuration (works with Gmail, Outlook, custom servers) ──────────
    "SMTP_HOST":              os.environ.get("SMTP_HOST", "smtp.gmail.com"),
    "SMTP_PORT":              int(os.environ.get("SMTP_PORT", 587)),
    "SMTP_USER":              os.environ.get("SMTP_USER", ""),
    "SMTP_PASSWORD":          os.environ.get("SMTP_PASSWORD", ""),
    "SENDER_EMAIL":           os.environ.get("SENDER_EMAIL", "brijeshrajara24@gmail.com"),
    "APPROVAL_EMAIL":         os.environ.get("APPROVAL_EMAIL", ""),
    # ── OpenRouter fallback ─────────────────────────────────────────────────────
    "OPENROUTER_API_KEY":     os.environ.get("OPENROUTER_API_KEY", ""),
    "OPENROUTER_MODEL":       os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
}

os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
os.makedirs(CONFIG["SCHEDULED_IMAGES_DIR"], exist_ok=True)

# ── Gemini rotating keys ───────────────────────────────────────────────────────
GEMINI_API_KEYS = [k for k in [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 11)] if k]
_current_key_index = 0
_key_lock = threading.Lock()
_key_cooldowns: Dict[int, float] = {}
_KEY_COOLDOWN_SECS = 65

# ── Supabase ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("[Supabase] Connected")
    except Exception as e:
        logger.warning(f"[Supabase] Failed: {e}")

# ── Design constants ───────────────────────────────────────────────────────────
TONES = [
    "Executive Authority", "Warm & Authentic", "Bold Marketing",
    "Data-Driven Analyst", "Storyteller", "Technical Expert", "Inspiring Coach",
]
MOODS = {
    "Professional":     "professional corporate clean business modern",
    "Bold & Energetic": "bold dynamic energetic vibrant exciting",
    "Innovative":       "innovative creative futuristic technology modern",
    "Celebratory":      "celebration success achievement festive joyful",
    "Calm & Inspire":   "inspirational calm motivational serene peaceful",
    "Social Impact":    "community diversity purpose social impact",
    "Fun & Relatable":  "fun relatable friendly warm approachable",
    "Research & Data":  "data research analytics science insights",
}
GRADIENTS = {
    "Navy Sapphire":    ("#0a192f", "#0ea5e9"),
    "Obsidian Emerald": ("#020617", "#10b981"),
    "Deep Violet":      ("#1a0533", "#a855f7"),
    "Midnight Amber":   ("#1c1408", "#f59e0b"),
    "Charcoal Crimson": ("#1a0000", "#ef4444"),
    "Dark Teal":        ("#042f2e", "#14b8a6"),
    "Slate Coral":      ("#1e1b2e", "#f97316"),
    "Graphite Sky":     ("#111827", "#38bdf8"),
}
REWRITE_STYLES = {
    "professional": "Rewrite in polished executive professional tone.",
    "viral":        "Rewrite to maximise virality with a strong hook and bold claim.",
    "ceo":          "Rewrite as a CEO personal brand post with strategic vision.",
    "technical":    "Rewrite with deep technical detail and precise terminology.",
    "motivational": "Rewrite as deeply inspiring motivational content.",
    "storytelling": "Rewrite as a compelling narrative story.",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE — Supabase primary, JSON fallback
# ═══════════════════════════════════════════════════════════════════════════════
_TOKEN_FILE           = "li_tokens.json"
_PROFILE_FILE         = "li_profile.json"
_JOBS_FILE            = "scheduler_jobs.json"
_APPROVALS_FILE       = "li_approvals.json"
_PENDING_APPROVALS_FILE = "pending_approvals.json"  # Resend one-click token store

def _save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"[JSON] save {path}: {e}")

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def upload_image_to_supabase(local_path: str) -> Optional[str]:
    try:
        filename = f"{uuid.uuid4()}.png"
        with open(local_path, "rb") as f:
            supabase.storage.from_("post-images").upload(
                path=filename, file=f.read(), file_options={"content-type": "image/png"}
            )
        return supabase.storage.from_("post-images").get_public_url(filename)
    except Exception as e:
        logger.error(f"[Storage] {e}")
        return None

# ── Token ──────────────────────────────────────────────────────────────────────
def save_token(token_data: dict):
    _save_json(_TOKEN_FILE, token_data)
    if supabase:
        try:
            supabase.table("li_tokens").upsert({
                "id": "main", "access_token": token_data.get("access_token"),
                "expires_in": token_data.get("expires_in"),
                "token_type": token_data.get("token_type", "Bearer"),
                "scope": token_data.get("scope", ""),
                "created_at": datetime.datetime.utcnow().isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_token: {e}")

def get_token() -> Optional[str]:
    if supabase:
        try:
            r = supabase.table("li_tokens").select("access_token").eq("id", "main").limit(1).execute()
            if r.data:
                return r.data[0].get("access_token")
        except Exception:
            pass
    data = _load_json(_TOKEN_FILE)
    return data.get("access_token") if data else None

def delete_token():
    _save_json(_TOKEN_FILE, {})
    if supabase:
        try:
            supabase.table("li_tokens").delete().eq("id", "main").execute()
        except Exception:
            pass

# ── Profile ────────────────────────────────────────────────────────────────────
def save_profile(data: dict):
    _save_json(_PROFILE_FILE, data)
    if supabase:
        try:
            supabase.table("li_profiles").upsert(
                {"id": "main", **data, "updated_at": datetime.datetime.utcnow().isoformat()}
            ).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_profile: {e}")

def get_profile() -> dict:
    if supabase:
        try:
            r = supabase.table("li_profiles").select("*").eq("id", "main").limit(1).execute()
            if r.data:
                return dict(r.data[0])
        except Exception:
            pass
    return _load_json(_PROFILE_FILE) or {}

# ── Jobs ───────────────────────────────────────────────────────────────────────
def save_job(job: dict):
    jobs = _load_json(_JOBS_FILE) or []
    jobs.append(job)
    _save_json(_JOBS_FILE, jobs)
    if supabase:
        try:
            supabase.table("scheduled_posts").insert(job).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_job: {e}")

def update_job_status(job_id: str, status: str, extra: dict = None):
    jobs = _load_json(_JOBS_FILE) or []
    for j in jobs:
        if str(j.get("id")) == str(job_id):
            j["status"] = status
            if extra:
                j.update(extra)
            break
    _save_json(_JOBS_FILE, jobs)
    if supabase:
        try:
            payload = {"status": status}
            if extra:
                payload.update(extra)
            supabase.table("scheduled_posts").update(payload).eq("id", str(job_id)).execute()
        except Exception as e:
            logger.warning(f"[Supabase] update_job_status: {e}")

def get_all_jobs(status_filter: str = None) -> list:
    if supabase:
        try:
            q = supabase.table("scheduled_posts").select("*").order("created_at", desc=True)
            if status_filter:
                q = q.eq("status", status_filter)
            r = q.execute()
            if r.data is not None:
                return r.data
        except Exception as e:
            logger.warning(f"[Supabase] get_all_jobs: {e}")
    jobs = _load_json(_JOBS_FILE) or []
    if status_filter:
        jobs = [j for j in jobs if j.get("status", "").lower() == status_filter.lower()]
    return list(reversed(jobs))

def delete_job_by_id(job_id: str) -> bool:
    jobs = _load_json(_JOBS_FILE) or []
    before = len(jobs)
    jobs = [j for j in jobs if str(j.get("id")) != str(job_id)]
    _save_json(_JOBS_FILE, jobs)
    if supabase:
        try:
            supabase.table("scheduled_posts").delete().eq("id", str(job_id)).execute()
        except Exception:
            pass
    return len(jobs) < before

# ── Approvals ──────────────────────────────────────────────────────────────────
def save_approval(approval: dict):
    approvals = _load_json(_APPROVALS_FILE) or []
    approvals = [a for a in approvals if a.get("id") != approval.get("id")]
    approvals.append(approval)
    _save_json(_APPROVALS_FILE, approvals)
    if supabase:
        try:
            supabase.table("approvals").upsert(approval).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_approval: {e}")

def get_approvals(status_filter: str = None) -> list:
    if supabase:
        try:
            q = supabase.table("approvals").select("*").order("created_at", desc=True)
            if status_filter:
                q = q.eq("status", status_filter)
            r = q.execute()
            if r.data is not None:
                return r.data
        except Exception as e:
            logger.warning(f"[Supabase] get_approvals: {e}")
    approvals = _load_json(_APPROVALS_FILE) or []
    if status_filter:
        approvals = [a for a in approvals if a.get("status", "pending") == status_filter]
    return list(reversed(approvals))

def get_approval_by_id(approval_id: str) -> Optional[dict]:
    if supabase:
        try:
            r = supabase.table("approvals").select("*").eq("id", approval_id).limit(1).execute()
            if r.data:
                return dict(r.data[0])
        except Exception:
            pass
    for a in (_load_json(_APPROVALS_FILE) or []):
        if str(a.get("id")) == str(approval_id):
            return a
    return None

def update_approval(approval_id: str, data: dict):
    approvals = _load_json(_APPROVALS_FILE) or []
    for a in approvals:
        if str(a.get("id")) == str(approval_id):
            a.update(data)
            break
    _save_json(_APPROVALS_FILE, approvals)
    if supabase:
        try:
            supabase.table("approvals").update(data).eq("id", approval_id).execute()
        except Exception as e:
            logger.warning(f"[Supabase] update_approval: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  SMTP EMAIL  — Campaign approval only (SMTP works with Gmail, Outlook, etc.)
#
#  Flow:
#    AI Campaign creates jobs → scheduler fires 24h before → SMTP sends
#    approval email with 3 post variations + images → user clicks one link
#    → post published to LinkedIn immediately.
# ═══════════════════════════════════════════════════════════════════════════════

def _smtp_send(subject: str, html: str, to_email: str) -> bool:
    """
    Send email via SMTP (works with Gmail, Outlook, any SMTP server).
    
    Configuration needed:
      SMTP_HOST = smtp server hostname (e.g., smtp.gmail.com)
      SMTP_PORT = 587 (TLS) or 465 (SSL)
      SMTP_USER = email address to send from
      SMTP_PASSWORD = password or app-specific password
      SENDER_EMAIL = display name's email
    """
    if not CONFIG["SMTP_USER"] or not CONFIG["SMTP_PASSWORD"]:
        logger.warning(f"[SMTP] SKIP (no credentials): would send to {to_email}")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = CONFIG["SENDER_EMAIL"]
        msg['To'] = to_email
        
        # Add HTML content
        part = MIMEText(html, 'html')
        msg.attach(part)
        
        # Connect and send
        logger.info(f"[SMTP] Connecting to {CONFIG['SMTP_HOST']}:{CONFIG['SMTP_PORT']}")
        with smtplib.SMTP(CONFIG["SMTP_HOST"], CONFIG["SMTP_PORT"], timeout=10) as server:
            server.starttls()  # Upgrade to TLS (works for port 587)
            server.login(CONFIG["SMTP_USER"], CONFIG["SMTP_PASSWORD"])
            server.send_message(msg)
        
        logger.info(f"[SMTP] ✅ Sent to {to_email} | Subject: {subject}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"[SMTP] ❌ AUTH FAILED: Check SMTP_USER and SMTP_PASSWORD")
        logger.error(f"[SMTP] Error: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"[SMTP] ❌ SMTP Error: {e}")
        return False
    except Exception as e:
        logger.error(f"[SMTP] ❌ Failed to send: {type(e).__name__}: {e}")
        return False


def _build_campaign_approval_html(approval_id: str, job_data: dict, variations: list, image_urls: list) -> str:
    """
    Approval email sent by AI Campaign scheduler.
    Shows 3 post variations + up to 3 images — user clicks one link to approve & publish.
    """
    base_url = CONFIG["APP_BASE_URL"]
    topic    = escape(job_data.get("topic", "LinkedIn Post"))
    sched    = job_data.get("datetime", "")

    var_html = ""
    for i, v in enumerate(variations):
        label = chr(65 + i)  # A, B, C
        approve_url = f"{base_url}/campaign-approve/{approval_id}?choice={label.lower()}&variation={i}"
        var_html += f"""
<div style="background:#0e1828;border:1px solid #1e3a5f;border-radius:10px;padding:18px;margin:12px 0">
  <div style="color:#0ea5e9;font-weight:700;font-size:12px;margin-bottom:8px;text-transform:uppercase;letter-spacing:.05em">
    Variation {label} — {escape(v.get('style',''))}
  </div>
  <div style="color:#c8d6e5;font-size:13px;white-space:pre-wrap;line-height:1.75;max-height:220px;overflow:hidden">
    {escape(v.get('text','')[:500])}{'…' if len(v.get('text',''))>500 else ''}
  </div>
  <a href="{approve_url}"
     style="display:inline-block;margin-top:14px;padding:10px 24px;background:#0ea5e9;
            color:#000;border-radius:6px;font-size:13px;font-weight:700;text-decoration:none">
    ✓ Approve &amp; Post Variation {label}
  </a>
</div>"""

    img_html = ""
    if image_urls:
        img_html = "<h3 style='color:#f0f6fc;margin:24px 0 12px;font-size:15px'>📸 Or choose a variation with this image</h3>"
        img_html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
        for i, img_url in enumerate(image_urls[:3]):
            label = chr(65 + i)
            approve_img_url = f"{base_url}/campaign-approve/{approval_id}?choice=a&variation=0&image={i}"
            img_html += f"""
<a href="{approve_img_url}" style="text-decoration:none">
  <div style="border:2px solid #1e3a5f;border-radius:8px;overflow:hidden;width:180px;cursor:pointer">
    <img src="{img_url}" style="width:180px;height:115px;object-fit:cover;display:block" alt="Image {label}">
    <div style="padding:8px;text-align:center;color:#0ea5e9;font-size:11px;font-weight:700;background:#0a1628">
      Use Image {label}
    </div>
  </div>
</a>"""
        img_html += "</div>"

    reject_url = f"{base_url}/campaign-approve/{approval_id}?action=reject"
    skip_url   = f"{base_url}/campaign-approve/{approval_id}?action=skip"

    return f"""<!DOCTYPE html><html>
<body style="background:#03050a;color:#f0f6fc;font-family:'Segoe UI',sans-serif;padding:0;margin:0">
<div style="max-width:680px;margin:32px auto;background:#0a1628;border:1px solid #1e3a5f;border-radius:16px;overflow:hidden">

  <div style="background:linear-gradient(135deg,#0ea5e9,#a855f7);padding:28px 32px">
    <h1 style="margin:0;font-size:20px;color:#fff">🚀 LinkedIn Post Ready for Approval</h1>
    <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:13px">
      Click any variation below to approve &amp; publish instantly to LinkedIn.
    </p>
  </div>

  <div style="padding:24px 32px">
    <div style="background:#0e1828;border-radius:8px;padding:14px 18px;margin-bottom:20px;display:flex;gap:16px;flex-wrap:wrap">
      <div><span style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Topic</span><br>
           <strong style="font-size:14px">{topic}</strong></div>
      <div><span style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Scheduled</span><br>
           <strong style="font-size:14px">{sched}</strong></div>
    </div>

    <h3 style="color:#f0f6fc;margin:0 0 4px;font-size:15px">📝 Choose a Post Variation</h3>
    <p style="color:#64748b;font-size:12px;margin:0 0 8px">Each variation is written in a different style. Click to approve &amp; post immediately.</p>
    {var_html}
    {img_html}

    <div style="margin-top:28px;display:flex;gap:10px;padding-top:20px;border-top:1px solid #1e3a5f">
      <a href="{reject_url}"
         style="padding:10px 22px;background:rgba(239,68,68,0.15);color:#ef4444;
                border:1px solid rgba(239,68,68,0.3);border-radius:6px;font-size:12px;
                font-weight:700;text-decoration:none">✗ Reject</a>
      <a href="{skip_url}"
         style="padding:10px 22px;background:rgba(100,116,139,0.15);color:#64748b;
                border:1px solid rgba(100,116,139,0.3);border-radius:6px;font-size:12px;
                font-weight:700;text-decoration:none">⏭ Skip this post</a>
    </div>

    <p style="color:#334155;font-size:10px;margin-top:16px">
      Generated by LinkedIn Studio PRO · Will not publish unless you click Approve.
    </p>
  </div>
</div>
</body></html>"""


def send_campaign_approval_email(to_email: str, approval_id: str, job_data: dict, variations: list, image_urls: list) -> bool:
    """Send the AI Campaign approval email via SMTP."""
    topic = job_data.get("topic", "LinkedIn Post")
    html  = _build_campaign_approval_html(approval_id, job_data, variations, image_urls)
    return _smtp_send(
        f"🚀 Approve LinkedIn Post — {topic[:50]}",
        html,
        to_email,
    )


def _build_manual_approval_html(approval_id: str, job_data: dict) -> str:
    """
    Approval email for manually scheduled posts (single text + optional image).
    User clicks Approve → post published immediately to LinkedIn.
    """
    base_url   = CONFIG["APP_BASE_URL"]
    text_preview = escape((job_data.get("text") or "")[:600])
    sched      = job_data.get("datetime", "")
    post_type  = escape(job_data.get("post_type") or "Scheduled Post")
    image_url  = job_data.get("image_url") or ""

    approve_url = f"{base_url}/campaign-approve/{approval_id}?choice=a&variation=0"
    reject_url  = f"{base_url}/campaign-approve/{approval_id}?action=reject"

    img_block = ""
    if image_url:
        img_block = f"""
<div style="margin:18px 0 0">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:6px">
    Attached Image
  </div>
  <div style="border:1px solid #1e3a5f;border-radius:8px;overflow:hidden">
    <img src="{escape(image_url)}" style="width:100%;max-height:260px;object-fit:cover;display:block">
  </div>
</div>"""

    return f"""<!DOCTYPE html><html>
<body style="background:#03050a;color:#f0f6fc;font-family:'Segoe UI',sans-serif;padding:0;margin:0">
<div style="max-width:660px;margin:32px auto;background:#0a1628;border:1px solid #1e3a5f;border-radius:16px;overflow:hidden">

  <div style="background:linear-gradient(135deg,#0ea5e9,#a855f7);padding:26px 32px">
    <h1 style="margin:0;font-size:20px;color:#fff">📋 Scheduled Post Ready for Approval</h1>
    <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:13px">
      Click Approve below to publish this post to LinkedIn instantly.
    </p>
  </div>

  <div style="padding:24px 32px">
    <div style="background:#0e1828;border-radius:8px;padding:12px 16px;margin-bottom:18px;display:flex;gap:20px;flex-wrap:wrap">
      <div><span style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Post Type</span><br>
           <strong style="font-size:13px">{post_type}</strong></div>
      <div><span style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Scheduled For</span><br>
           <strong style="font-size:13px">{sched}</strong></div>
    </div>

    <h3 style="color:#f0f6fc;margin:0 0 8px;font-size:14px">📝 Post Content</h3>
    <div style="background:#0e1828;border:1px solid #1e3a5f;border-radius:8px;padding:16px;
         font-size:14px;line-height:1.8;color:#e8f0fc;white-space:pre-wrap">
{text_preview}{'…' if len(job_data.get('text',''))>600 else ''}
    </div>

    {img_block}

    <div style="margin-top:24px;display:flex;gap:12px;flex-wrap:wrap">
      <a href="{approve_url}"
         style="display:inline-block;padding:12px 28px;background:#0ea5e9;
                color:#000;border-radius:8px;font-size:14px;font-weight:700;text-decoration:none">
        ✓ Approve &amp; Publish to LinkedIn
      </a>
      <a href="{reject_url}"
         style="display:inline-block;padding:12px 22px;background:rgba(239,68,68,0.15);
                color:#ef4444;border:1px solid rgba(239,68,68,0.3);border-radius:8px;
                font-size:14px;font-weight:700;text-decoration:none">
        ✗ Reject
      </a>
    </div>

    <p style="color:#334155;font-size:10px;margin-top:18px">
      Generated by LinkedIn Studio PRO · Will not publish unless you click Approve.
    </p>
  </div>
</div>
</body></html>"""


def send_manual_approval_email(to_email: str, approval_id: str, job_data: dict) -> bool:
    """Send approval email for a manually scheduled post via SMTP."""
    text_snippet = (job_data.get("text") or "Scheduled Post")[:50]
    html = _build_manual_approval_html(approval_id, job_data)
    return _smtp_send(
        f"📋 Approve Scheduled LinkedIn Post — {text_snippet}",
        html,
        to_email,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  LINKEDIN API
# ═══════════════════════════════════════════════════════════════════════════════
def linkedin_get_auth_url(state: str = "") -> str:
    if not CONFIG["LINKEDIN_CLIENT_ID"]:
        raise ValueError("LINKEDIN_CLIENT_ID not configured")
    params = {
        "response_type": "code",
        "client_id":     CONFIG["LINKEDIN_CLIENT_ID"],
        "redirect_uri":  CONFIG["LINKEDIN_REDIRECT_URI"],
        "scope":         CONFIG["LINKEDIN_SCOPES"],
        "state":         state or str(random.randint(100000, 999999)),
    }
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)

def linkedin_exchange_code(code: str) -> str:
    resp = http_requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": CONFIG["LINKEDIN_REDIRECT_URI"],
            "client_id": CONFIG["LINKEDIN_CLIENT_ID"],
            "client_secret": CONFIG["LINKEDIN_CLIENT_SECRET"],
        }, timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"LinkedIn token exchange failed: {resp.text}")
    token_data = resp.json()
    if "error" in token_data:
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))
    save_token(token_data)
    return token_data.get("access_token")

def linkedin_get_userinfo(access_token: str) -> tuple:
    r = http_requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to fetch user info: {r.text}")
    info = r.json()
    return info.get("sub"), info.get("name", "User"), info.get("email", "")

def linkedin_post_text(access_token: str, urn: str, text: str) -> tuple:

    payload = {
        "author": f"urn:li:person:{urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    r = http_requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202405",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30
    )

    try:
        return r.status_code, r.json()
    except:
        return r.status_code, r.text
def download_temp_image(url: str) -> Optional[str]:
    try:
        r = http_requests.get(url, timeout=30)
        if r.status_code != 200:
            return None
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.error(f"[Image Download] {e}")
        return None

def linkedin_post_with_image(access_token: str, urn: str, text: str, image_path: str) -> tuple:
    reg_payload = {
        "registerUploadRequest": {
            "owner": f"urn:li:person:{urn}",
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "serviceRelationships": [
                {"identifier": "urn:li:userGeneratedContent", "relationshipType": "OWNER"}
            ],
        }
    }
    reg_r = http_requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=reg_payload, timeout=15,
    )
    if reg_r.status_code not in (200, 201):
      return reg_r.status_code, reg_r.text

    reg_data   = reg_r.json()
    upload_url = reg_data["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn  = reg_data["value"]["asset"]

    with open(image_path, "rb") as f:
        img_bytes = f.read()
    upload_resp = http_requests.put(
        upload_url, data=img_bytes,
        headers={"Authorization": f"Bearer {access_token}"}, timeout=30,
    )
    if upload_resp.status_code not in (200, 201):
      return upload_resp.status_code, upload_resp.text

    payload = {
    "author": f"urn:li:person:{urn}",
    "commentary": text,
    "visibility": "PUBLIC",
    "distribution": {
        "feedDistribution": "MAIN_FEED",
        "targetEntities": [],
        "thirdPartyDistributionChannels": []
    },
    "content": {
        "media": {
            "id": asset_urn
        }
    },
    "lifecycleState": "PUBLISHED",
    "isReshareDisabledByAuthor": False
    }    
    r = http_requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202405",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20,
    )
    return r.status_code, r.json()

# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI AI + OPENROUTER FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════
GEMINI_MODELS_FALLBACK = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
OPENROUTER_MODELS_FALLBACK = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat:free",
    "qwen/qwen2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

def get_next_gemini_model(model_name: str = None, key_idx: int = None):
    global _current_key_index
    now = time.time()
    with _key_lock:
        if key_idx is not None:
            idx = key_idx % len(GEMINI_API_KEYS)
        else:
            start = _current_key_index
            idx = start
            for _ in range(len(GEMINI_API_KEYS)):
                candidate = _current_key_index
                _current_key_index = (_current_key_index + 1) % len(GEMINI_API_KEYS)
                if now >= _key_cooldowns.get(candidate, 0):
                    idx = candidate
                    break
            else:
                idx = start
        api_key = GEMINI_API_KEYS[idx]
    genai.configure(api_key=api_key)
    name = model_name or CONFIG.get("GEMINI_MODEL", "gemini-2.0-flash")
    return genai.GenerativeModel(name), api_key, idx

def openrouter_generate(prompt: str) -> str:
    api_key = CONFIG.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return ""
    for model in OPENROUTER_MODELS_FALLBACK:
        try:
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": CONFIG.get("APP_BASE_URL", ""),
                    "X-Title": "LinkedIn Studio PRO",
                },
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return ""

def gemini_generate(prompt: str) -> str:
    if not GEMINI_API_KEYS:
        return openrouter_generate(prompt) or "[AI error: No API keys]"
    primary = CONFIG.get("GEMINI_MODEL", "gemini-2.0-flash")
    models  = [primary] + [m for m in GEMINI_MODELS_FALLBACK if m != primary]
    for model_name in models:
        exhausted = 0
        for attempt in range(len(GEMINI_API_KEYS)):
            try:
                model, _, _ = get_next_gemini_model(model_name, key_idx=attempt)
                return model.generate_content(prompt).text.strip()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("429", "quota", "rate limit", "resource_exhausted")):
                    _key_cooldowns[attempt] = time.time() + _KEY_COOLDOWN_SECS
                    exhausted += 1
                    continue
                if "404" in err or "not found" in err:
                    exhausted = len(GEMINI_API_KEYS)
                    break
                break
        if exhausted >= len(GEMINI_API_KEYS):
            continue
    result = openrouter_generate(prompt)
    if result:
        return result
    return "[AI temporarily unavailable. Please try again.]"

# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE SEARCH — Pixabay + Pexels
# ═══════════════════════════════════════════════════════════════════════════════
def _search_stock(query: str, count: int) -> list:
    results = []
    if CONFIG["PIXABAY_API_KEY"] and len(results) < count:
        try:
            r = http_requests.get("https://pixabay.com/api/", params={
                "key": CONFIG["PIXABAY_API_KEY"], "q": query,
                "image_type": "photo", "per_page": min(count + 3, 20),
                "safesearch": "true", "order": "popular",
                "min_width": 800, "orientation": "horizontal",
            }, timeout=10)
            for hit in r.json().get("hits", [])[:count]:
                results.append({
                    "url": hit["largeImageURL"], "thumb": hit["webformatURL"],
                    "source": "Pixabay", "query": query,
                    "id": str(hit.get("id", "")), "photographer": hit.get("user", ""),
                })
        except Exception as e:
            logger.debug(f"[Pixabay] {e}")
    if CONFIG["PEXELS_API_KEY"] and len(results) < count:
        try:
            r = http_requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": CONFIG["PEXELS_API_KEY"]},
                params={"query": query, "per_page": count, "orientation": "landscape"},
                timeout=10,
            )
            for p in r.json().get("photos", []):
                if len(results) >= count:
                    break
                results.append({
                    "url": p["src"]["large2x"], "thumb": p["src"]["medium"],
                    "source": "Pexels", "query": query,
                    "id": str(p.get("id", "")), "photographer": p.get("photographer", ""),
                })
        except Exception as e:
            logger.debug(f"[Pexels] {e}")
    return results[:count]

def search_images(query: str, count: int = 9) -> list:
    return _search_stock(query, count)

def fetch_images_for_post(profile: dict, post_type: str, mood: str, topic: str, count: int = 3) -> list:
    domain  = profile.get("domain", "").strip()
    product = profile.get("product", "").strip()
    company = profile.get("company", "")
    queries = []
    if HAS_GEMINI and domain:
        prompt = f"""Stock photo search queries for LinkedIn post.
Company: {company} | Domain: {domain} | Product: {product} | Topic: {topic}
Return ONLY a JSON array of 3 search query strings (5-8 words each). No markdown."""
        raw = gemini_generate(prompt)
        try:
            queries = json.loads(re.sub(r"```json|```", "", raw).strip())
            if not isinstance(queries, list):
                queries = []
        except Exception:
            queries = []
    if not queries:
        d  = " ".join(domain.lower().split()[:2]) or "business"
        pr = " ".join(product.lower().split()[:2]) or "technology"
        queries = [f"{pr} professional", f"person {d} modern", f"{d} industry"]
    results = []
    per_q = max(1, math.ceil(count / len(queries)))
    for q in queries:
        if len(results) >= count:
            break
        results.extend(_search_stock(q, per_q))
    seen, unique = set(), []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique[:count]

def download_image(url: str, save_path: str) -> bool:
    try:
        r = http_requests.get(url, timeout=45, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return os.path.getsize(save_path) > 5000
    except Exception:
        pass
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE GENERATION — Poster layouts
# ═══════════════════════════════════════════════════════════════════════════════
def _load_font(size: int, bold: bool = True):
    if not HAS_PIL:
        return None
    candidates = (["arialbd.ttf", "DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"] if bold
                  else ["arial.ttf", "DejaVuSans.ttf",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] * (1-t) + c2[i] * t) for i in range(3))

def build_poster_layout_1(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))
    bg = ImageEnhance.Brightness(bg_img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")).enhance(0.75)
    canvas.paste(bg.convert("RGBA"), (0, 0))
    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x in range(W):
        t = 1.0 - min(1.0, x / 650)
        alpha = int(220 * (t ** 0.7))
        col = _lerp_color(drk, (drk[0], drk[1]+5, drk[2]+8), 1-t)
        for y in range(H):
            overlay.putpixel((x, y), (*col, alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rectangle([(0, 0), (6, H)], fill=(*acc, 255))
    canvas = Image.alpha_composite(canvas, bar)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(28); f_title = _load_font(78 if len(headline) < 25 else 58)
    f_tag = _load_font(20, False); f_sub = _load_font(30, False)
    draw.text((50, 50), org_name.upper(), font=f_brand, fill=(*acc, 255))
    draw.line([(50, 88), (300, 88)], fill=(*acc, 180), width=3)
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.text((62, 100), pt_clean.upper(), font=f_tag, fill=(*acc, 220))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0,0), " ".join(curr), font=f_title)[2] > 700:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    y = 200
    for line in lines[:3]:
        draw.text((52, y+3), line, font=f_title, fill=(0,0,0,130))
        draw.text((50, y), line, font=f_title, fill=(255,255,255,255))
        y += int(f_title.size * 1.15)
    if domain:
        tag = f"  {domain}  "
        tw = draw.textbbox((0,0), tag, font=f_sub)[2]
        draw.rounded_rectangle((50, H-80, 50+tw+24, H-44), radius=10, fill=(*acc,25), outline=(*acc,80))
        draw.text((62, H-76), tag, font=f_sub, fill=(*acc,220))
    return canvas.convert("RGB")

def build_poster_layout_2(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))
    bg = ImageEnhance.Brightness(bg_img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")).enhance(0.70)
    canvas.paste(bg.convert("RGBA"), (0, 0))
    acc = _hex_to_rgb(accent_hex); drk = _hex_to_rgb(dark_hex)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(H):
        t = max(0, (y - H*0.3) / (H*0.7))
        alpha = int(230 * min(1.0, t**0.65))
        col = _lerp_color((10,12,20), drk, t)
        draw_ov.line([(0,y),(W,y)], fill=(*col, alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(26); f_title = _load_font(86 if len(headline)<20 else 64); f_tag = _load_font(20, False)
    org_w = draw.textbbox((0,0), org_name.upper(), font=f_brand)[2]
    draw.text(((W-org_w)//2, 36), org_name.upper(), font=f_brand, fill=(*acc,240))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0,0)," ".join(curr),font=f_title)[2] > W-120:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr=[w]
    lines.append(" ".join(curr))
    total_h = len(lines)*int(f_title.size*1.12); y = H-total_h-100
    for line in lines[:3]:
        lw = draw.textbbox((0,0),line,font=f_title)[2]; x=(W-lw)//2
        draw.text((x+3,y+3),line,font=f_title,fill=(0,0,0,100))
        draw.text((x,y),line,font=f_title,fill=(255,255,255,255))
        y += int(f_title.size*1.12)
    pt_clean = re.sub(r'[^\w\s/]','',post_type).strip()
    draw.line([(W//2-100,H-78),(W//2+100,H-78)],fill=(*acc,200),width=3)
    tw = draw.textbbox((0,0),pt_clean.upper(),font=f_tag)[2]
    draw.text(((W-tw)//2,H-62),pt_clean.upper(),font=f_tag,fill=(*acc,200))
    return canvas.convert("RGB")

LAYOUT_BUILDERS = [build_poster_layout_1, build_poster_layout_2]

def build_posters_for_images(images_data, headline, profile, post_type, gradient_name, topic):
    if not HAS_PIL:
        return []
    org_name = profile.get("company", profile.get("name", ""))
    domain   = profile.get("domain", "")
    g_keys   = list(GRADIENTS.keys())
    g_idx    = g_keys.index(gradient_name) if gradient_name in g_keys else 0
    dark_hex, accent_hex = list(GRADIENTS.values())[g_idx]
    posters = []
    for i, item in enumerate(images_data):
        raw_path = os.path.join(CONFIG["CACHE_DIR"], f"raw_bg_{i}_{int(time.time())}.jpg")
        if not download_image(item["url"], raw_path):
            continue
        try:
            bg_img  = Image.open(raw_path).convert("RGB")
            poster  = LAYOUT_BUILDERS[i % len(LAYOUT_BUILDERS)](bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex)
            out_path = os.path.join(CONFIG["CACHE_DIR"], f"poster_{i}_{int(time.time())}.png")
            poster.save(out_path, "PNG")
            public_url = upload_image_to_supabase(out_path) if supabase else None
            posters.append((out_path, item.get("source", "Stock Photo"), public_url))
        except Exception as e:
            logger.warning(f"[Poster] {e}")
    return posters

def edit_image(image_path: str, operations: dict) -> str:
    if not HAS_PIL:
        return image_path
    try:
        img = Image.open(image_path).convert("RGB")
        if "brightness" in operations:
            img = ImageEnhance.Brightness(img).enhance(float(operations["brightness"]))
        if "contrast" in operations:
            img = ImageEnhance.Contrast(img).enhance(float(operations["contrast"]))
        if "blur" in operations:
            img = img.filter(ImageFilter.GaussianBlur(radius=float(operations["blur"])))
        if "watermark" in operations:
            draw = ImageDraw.Draw(img)
            w, h = img.size
            draw.text((w-20, h-20), str(operations["watermark"]),
                      font=_load_font(int(w*0.04)), fill=(255,255,255,100), anchor="rb")
        if "text_overlay" in operations:
            to = operations["text_overlay"]
            draw = ImageDraw.Draw(img)
            draw.text((to.get("x",50), to.get("y",50)), to.get("text",""),
                      font=_load_font(int(to.get("size",48))),
                      fill=tuple(_hex_to_rgb(to.get("color","#ffffff"))) + (255,))
        out_path = os.path.join(CONFIG["CACHE_DIR"], f"edited_{int(time.time())}.png")
        img.save(out_path, "PNG")
        return out_path
    except Exception as e:
        logger.warning(f"[ImageEdit] {e}")
        return image_path

# ═══════════════════════════════════════════════════════════════════════════════
#  TEXT GENERATION
# ═══════════════════════════════════════════════════════════════════════════════
def _unicode_bold(text: str) -> str:
    bold_map = {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        bold_map[c] = chr(0x1D400 + i)
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        bold_map[c] = chr(0x1D41A + i)
    return "".join(bold_map.get(c, c) for c in text)

def clean_for_linkedin(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    lines = text.split('\n')
    processed = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r'^#{1,4}\s+(.+)$', stripped)
        if m:
            processed.append(_unicode_bold(m.group(1).strip().upper()))
            continue
        line = re.sub(r'\*\*(.+?)\*\*', lambda m: _unicode_bold(m.group(1).strip()), stripped)
        line = re.sub(r'\*(.+?)\*', r'\1', line)
        processed.append(line)
    text = '\n'.join(processed)
    text_lines = text.strip().split('\n')
    body, tags = [], []
    for line in text_lines:
        s = line.strip()
        if s and all(w.startswith('#') for w in s.split()):
            tags.append(s)
        else:
            body.append(line)
    body_text = re.sub(r'\n{3,}', '\n\n', '\n'.join(body)).strip()
    return (body_text + '\n\n' + ' '.join(tags) if tags else body_text).strip()

def generate_post_text(profile: dict, post_type: str, tone: str, mood: str, topic: str) -> str:
    org_name   = profile.get("company", "")
    domain     = profile.get("domain", "")
    product    = profile.get("product", "")
    name       = profile.get("name", "Professional")
    is_company = profile.get("user_type", "individual") == "company"
    mood_desc  = MOODS.get(mood, "professional")
    prompt = f"""You are a senior LinkedIn content strategist.

BRAND: {org_name or name} | Domain: {domain} | Product: {product}
Type: {"Company (We/Our)" if is_company else "Individual (I/My)"}
Post Type: {post_type} | Tone: {tone} | Mood: {mood_desc} | Topic: {topic}

RULES:
1. Every sentence must tie back to {domain} and {product}
2. Structure: hook → 2-3 short paragraphs → 3 bullet points (✦) → CTA question → 5 hashtags
3. Max 200 words. Return ONLY the post text."""
    return gemini_generate(prompt)

def generate_ai_topics(company: str, domain: str, product: str, name: str, count: int = 3) -> list:
    prompt = f"""LinkedIn content strategist for {domain} company selling {product}.
Company: {company} | Person: {name}
Generate {count} highly specific LinkedIn post ideas tied to {domain} and {product}.
Return ONLY a JSON array of {count} strings. No markdown."""
    raw = gemini_generate(prompt)
    try:
        topics = json.loads(re.sub(r"```json|```", "", raw).strip())
        if isinstance(topics, list):
            return [str(t) for t in topics[:count]]
    except Exception:
        pass
    lines = [l.strip().strip('"\'- ') for l in raw.split("\n") if l.strip()]
    return [l for l in lines if 3 < len(l) < 120][:count]

def rewrite_post(text: str, style: str) -> str:
    instruction = REWRITE_STYLES.get(style, REWRITE_STYLES["professional"])
    prompt = f"""{instruction}

Original:
{text}

Keep all hashtags. Max 250 words. Return ONLY the rewritten post."""
    return clean_for_linkedin(gemini_generate(prompt))

def generate_post_variations(profile: dict, topic: str, post_type: str, tone: str, count: int = 3) -> list:
    styles = ["Thought Leadership", "Story / Experience", "Data-Driven Analyst"][:count]
    return [
        {"style": s, "text": clean_for_linkedin(generate_post_text(profile, post_type, s, "Professional", topic))}
        for s in styles
    ]

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND SCHEDULER
#  Every 30s: check for approved jobs due → post them
#  Every 2.5min: check for pending jobs within APPROVAL_LEAD_HOURS → send Resend email
# ═══════════════════════════════════════════════════════════════════════════════
def _process_approval_notifications():
    """
    For all pending jobs within APPROVAL_LEAD_HOURS of their schedule time:
    - Manual posts  → send approval email with the stored text/image directly.
    - AI Campaign posts → generate variations + images, then send approval email.
    """
    now     = datetime.datetime.now()
    profile = get_profile()
    lead_h  = CONFIG["APPROVAL_LEAD_HOURS"]

    for job in get_all_jobs():
        if job.get("status") != "pending":
            continue
        approval_email = job.get("approval_email") or profile.get("email", "") or CONFIG["APPROVAL_EMAIL"]
        if not approval_email:
            logger.warning(f"[Scheduler] Job {job.get('id')} has no approval_email — skipping")
            continue
        job_id = str(job.get("id", ""))
        # Skip if we already created an approval record for this job
        if any(str(a.get("job_id")) == job_id for a in get_approvals()):
            continue
        try:
            sched_dt = datetime.datetime.strptime(job.get("datetime", "9999-12-31 23:59"), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        hours_until = (sched_dt - now).total_seconds() / 3600
        if hours_until > lead_h:
            continue

        logger.info(f"[Scheduler] Building approval for job {job_id} (mode={job.get('mode','?')})")
        approval_id = str(uuid.uuid4())
        mode = job.get("mode", "manual")

        try:
            if mode == "manual":
                # ── Manual scheduled post ─────────────────────────────────────
                save_approval({
                    "id":            approval_id,
                    "job_id":        job_id,
                    "topic":         (job.get("text") or "")[:80],
                    "status":        "awaiting_approval",
                    "variations":    [{"style": "Manual", "text": job.get("text", "")}],
                    "image_urls":    [job["image_url"]] if job.get("image_url") else [],
                    "scheduled_for": job.get("datetime", ""),
                    "created_at":    datetime.datetime.utcnow().isoformat(),
                })
                update_job_status(job_id, "awaiting_approval")
                sent = send_manual_approval_email(approval_email, approval_id, job)
                logger.info(f"[Scheduler] Manual approval email {'✅ sent' if sent else '❌ failed (check SMTP config)'} → {approval_email}")

            else:
                # ── AI Campaign post ──────────────────────────────────────────
                topic  = job.get("topic", "LinkedIn Post")
                pdata  = {k: job.get(k, "") for k in ["company", "domain", "product", "name", "user_type"]}
                if not pdata["company"]:
                    pdata.update(profile)

                variations = generate_post_variations(
                    pdata, topic,
                    job.get("post_type", "Brand Announcement"),
                    job.get("tone", "Executive Authority"),
                )
                images     = fetch_images_for_post(pdata, job.get("post_type", "Brand Announcement"), job.get("mood", "Professional"), topic, count=3)
                image_urls = [img["thumb"] for img in images]

                save_approval({
                    "id":            approval_id,
                    "job_id":        job_id,
                    "topic":         topic,
                    "status":        "awaiting_approval",
                    "variations":    variations,
                    "image_urls":    image_urls,
                    "scheduled_for": job.get("datetime", ""),
                    "created_at":    datetime.datetime.utcnow().isoformat(),
                })
                update_job_status(job_id, "awaiting_approval")
                sent = send_campaign_approval_email(approval_email, approval_id, job, variations, image_urls)
                logger.info(f"[Scheduler] Campaign approval email {'✅ sent' if sent else '❌ failed (check SMTP config)'} → {approval_email}")

        except Exception as e:
            logger.error(f"[Scheduler] Approval error for {job_id}: {e}")


def _post_approved_jobs():
    """Post approved jobs whose scheduled time has arrived."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    token   = get_token()
    profile = get_profile()

    due = [
        j for j in get_all_jobs()
        if str(j.get("status", "")).lower() == "approved"
        and j.get("datetime", "") <= now_str
    ]
    for job in due:
        job_id = str(job.get("id", ""))
        try:
            urn  = job.get("urn") or profile.get("urn", "")
            text = clean_for_linkedin(job.get("approved_text") or job.get("text") or "")
            if not token or not urn or not text:
                update_job_status(job_id, "failed")
                continue

            image_path = None
            if job.get("image_url"):
                image_path = download_temp_image(job["image_url"])

            if image_path and os.path.exists(image_path):
                st, resp = linkedin_post_with_image(token, urn, text, image_path)
            else:
                st, resp = linkedin_post_text(token, urn, text)

            if st in (200, 201):
                update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                logger.info(f"[Scheduler] Job {job_id} posted ✓")
            else:
                update_job_status(job_id, f"failed_http_{st}")
                logger.error(f"[Scheduler] Job {job_id} LinkedIn error {st}")
        except Exception as e:
            logger.exception(f"[Scheduler] Job {job_id}: {e}")
            update_job_status(job_id, "failed")


def run_scheduler_daemon():
    logger.info("[Scheduler] Started")
    while True:
        try:
            _post_approved_jobs()
            _process_approval_notifications()  # Check every loop (every 30s)
        except Exception as e:
            logger.exception(f"[Scheduler] Loop error: {e}")
        time.sleep(30)

# ═══════════════════════════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=run_scheduler_daemon, daemon=True).start()
    logger.info("[App] Scheduler started")
    yield

app = FastAPI(title="LinkedIn Studio PRO", version="4.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── Pydantic Models ────────────────────────────────────────────────────────────
class ProfileIn(BaseModel):
    name: str; company: str; domain: str; product: str
    user_type: str = "company"
    urn: Optional[str] = None; email: Optional[str] = None

class GeneratePostIn(BaseModel):
    topic: str; headline: Optional[str] = None
    post_type: str = "Brand Announcement"; tone: str = "Executive Authority"
    mood: str = "Professional"; gradient: str = "Navy Sapphire"; image_count: int = 2

class RewriteIn(BaseModel):
    text: str; style: str = "professional"

class AutoCampaignIn(BaseModel):
    days: int; posts_per_day: int = 1
    time_slots: Optional[List[str]] = None
    start_date: str
    industry: Optional[str] = None; domain: Optional[str] = None; product: Optional[str] = None
    tone: str = "Executive Authority"; mood: str = "Professional"; gradient: str = "Navy Sapphire"
    approval_email: Optional[str] = None   # ← email for Resend approval notifications

class PostNowIn(BaseModel):
    text: str; image_path: Optional[str] = None

class ImageEditIn(BaseModel):
    image_path: str; operations: Dict[str, Any]

class ImageSearchIn(BaseModel):
    query: str; count: int = 9

class ApprovalActionIn(BaseModel):
    approval_id: str; action: str
    variation_index: int = 0; image_index: int = 0
    custom_text: Optional[str] = None

# ── Helpers ────────────────────────────────────────────────────────────────────
def _require_auth() -> str:
    t = get_token()
    if not t:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect LinkedIn first.")
    return t

def _require_profile() -> dict:
    p = get_profile()
    if not p.get("company"):
        raise HTTPException(status_code=400, detail="Set your brand profile first.")
    return p

def _inline_page(icon: str, title: str, message: str, color: str = "#0ea5e9") -> str:
    return f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"><title>{title}</title>
<style>body{{background:#03050a;color:#e8f0fc;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:40px;background:#0e1828;border:1px solid #1b2d45;
border-radius:16px;max-width:480px}}</style></head>
<body><div class="card">
<div style="font-size:56px">{icon}</div>
<h2 style="color:{color};margin:16px 0 8px">{title}</h2>
<p style="color:#8aa0bc">{message}</p>
<p style="color:#4a6080;font-size:12px;margin-top:20px">You can close this tab.</p>
</div></body></html>"""

# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok", "version": "4.2.0", "scheduler": "running",
        "gemini":         HAS_GEMINI and len(GEMINI_API_KEYS) > 0,
        "linkedin_token": bool(get_token()),
        "supabase":       bool(supabase),
        "pixabay":        bool(CONFIG["PIXABAY_API_KEY"]),
        "pexels":         bool(CONFIG["PEXELS_API_KEY"]),
        "smtp_ready":     bool(CONFIG["SMTP_USER"] and CONFIG["SMTP_PASSWORD"]),
        "pillow":         HAS_PIL,
    }

@app.get("/stats")
async def get_stats():
    jobs    = get_all_jobs()
    profile = get_profile()
    return {
        "total_jobs":         len(jobs),
        "pending":            sum(1 for j in jobs if j.get("status") == "pending"),
        "posted":             sum(1 for j in jobs if j.get("status") == "posted"),
        "failed":             sum(1 for j in jobs if "failed" in str(j.get("status",""))),
        "approved":           sum(1 for j in jobs if j.get("status") == "approved"),
        "scheduled":          sum(1 for j in jobs if j.get("status") in ("pending","approved","awaiting_approval")),
        "linkedin_connected": bool(get_token()),
        "gemini_ready":       HAS_GEMINI and len(GEMINI_API_KEYS) > 0,
        "smtp_ready":         bool(CONFIG["SMTP_USER"] and CONFIG["SMTP_PASSWORD"]),
        "supabase_connected": bool(supabase),
        "profile_set":        bool(profile.get("company")),
    }

@app.get("/analytics")
async def get_analytics():
    jobs = get_all_jobs(); now = datetime.datetime.now()
    weekly: Dict[str,int] = {}
    daily:  Dict[str,int] = {}
    cutoff = now - datetime.timedelta(days=30)
    for j in jobs:
        try:
            dt = datetime.datetime.strptime(j.get("datetime",""), "%Y-%m-%d %H:%M")
            weekly[dt.strftime("%Y-W%W")] = weekly.get(dt.strftime("%Y-W%W"), 0) + 1
            if dt >= cutoff:
                daily[dt.strftime("%Y-%m-%d")] = daily.get(dt.strftime("%Y-%m-%d"), 0) + 1
        except Exception:
            pass
    total  = len(jobs)
    posted = sum(1 for j in jobs if j.get("status") == "posted")
    failed = sum(1 for j in jobs if "failed" in str(j.get("status","")))
    approved = sum(1 for j in jobs if j.get("status") in ("approved","posted"))
    return {
        "total_posts": total, "posted": posted, "failed": failed, "approved": approved,
        "approval_rate": round(approved/total*100 if total else 0, 1),
        "success_rate":  round(posted/(posted+failed)*100 if (posted+failed) else 0, 1),
        "posts_per_week": weekly, "posts_per_day": daily,
    }
@app.get("/debug/profile")
async def debug_profile():
    return get_profile()    

# ── Auth ───────────────────────────────────────────────────────────────────────
@app.get("/auth/login")
async def auth_login():
    if not CONFIG["LINKEDIN_CLIENT_ID"]:
        raise HTTPException(status_code=500, detail="LINKEDIN_CLIENT_ID not configured")
    return RedirectResponse(url=linkedin_get_auth_url())

@app.get("/auth/url")
async def auth_get_url():
    if not CONFIG["LINKEDIN_CLIENT_ID"]:
        raise HTTPException(status_code=500, detail="LINKEDIN_CLIENT_ID not configured")
    return {"url": linkedin_get_auth_url()}

@app.get("/auth/callback")
async def auth_callback(code: str, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(content=_inline_page("❌","Auth Failed",f"LinkedIn error: {error}","#ef4444"), status_code=400)
    try:
        token            = linkedin_exchange_code(code)
        urn, name, email = linkedin_get_userinfo(token)
        profile          = get_profile()
        profile.update({"urn": urn, "name": name, "email": email or profile.get("email","")})
        save_profile(profile)
        safe_name  = urllib.parse.quote(name, safe="")
        safe_email = urllib.parse.quote(email or "", safe="")
        frontend   = CONFIG["APP_BASE_URL"]
        return HTMLResponse(content=f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"><title>Connected</title>
<style>body{{background:#03050a;color:#e8f0fc;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:40px;max-width:400px;background:#0e1828;
border:1px solid #1b2d45;border-radius:16px}}</style></head>
<body><div class="card">
<div style="font-size:56px">✅</div>
<h2 style="color:#10b981;margin:16px 0 8px">LinkedIn Connected!</h2>
<p>Signed in as <strong>{name}</strong></p>
<p style="color:#4a6080;font-size:12px;margin-top:14px">You can close this tab.</p>
</div>
<script>
if(window.opener&&!window.opener.closed){{
  window.opener.postMessage({{type:'linkedin_connected',name:'{safe_name}',email:'{safe_email}'}},'*');
  setTimeout(()=>window.close(),800);
}}else{{window.location.href='{frontend}?linkedin_connected=1&name={safe_name}';}}
</script></body></html>""")
    except HTTPException as he:
        return HTMLResponse(content=_inline_page("❌","Auth Failed",he.detail,"#ef4444"), status_code=he.status_code)
    except Exception as e:
        return HTMLResponse(content=_inline_page("❌","Auth Failed",str(e),"#ef4444"), status_code=500)

@app.get("/auth/status")
async def auth_status():
    token = get_token(); profile = get_profile()
    return {"connected": bool(token), "urn": profile.get("urn"), "name": profile.get("name"), "email": profile.get("email")}

@app.delete("/auth/disconnect")
async def auth_disconnect():
    delete_token(); return {"status": "disconnected"}

# ── Profile ────────────────────────────────────────────────────────────────────
@app.post("/profile")
async def set_profile(data: ProfileIn):
    profile = get_profile()
    profile.update({k: v for k, v in data.dict().items() if v is not None})
    save_profile(profile)
    return {"status": "saved", "profile": profile}

@app.get("/profile")
async def read_profile():
    return get_profile()

# ── AI Topics ──────────────────────────────────────────────────────────────────
@app.post("/generate-topics")
async def gen_topics():
    p = get_profile()
    topics = generate_ai_topics(p.get("company",""), p.get("domain",""), p.get("product",""), p.get("name",""), count=3)
    if not topics:
        raise HTTPException(status_code=500, detail="Could not generate topics. Check GEMINI_API_KEY.")
    return {"topics": topics, "count": len(topics)}

# ── Rewrite ────────────────────────────────────────────────────────────────────
@app.post("/rewrite")
async def rewrite(data: RewriteIn):
    if data.style not in REWRITE_STYLES:
        raise HTTPException(status_code=400, detail=f"Style must be one of: {list(REWRITE_STYLES.keys())}")
    return {"original": data.text, "rewritten": rewrite_post(data.text, data.style), "style": data.style}

# ── Generate Post ──────────────────────────────────────────────────────────────
@app.post("/generate")
async def generate(data: GeneratePostIn):
    profile  = _require_profile()
    headline = data.headline or data.topic[:50]
    raw_text = generate_post_text(profile, data.post_type, data.tone, data.mood, data.topic)
    cleaned  = clean_for_linkedin(raw_text)
    images, posters = [], []
    if data.image_count > 0:
        images  = fetch_images_for_post(profile, data.post_type, data.mood, data.topic, count=data.image_count)
        posters = build_posters_for_images(images, headline, profile, data.post_type, data.gradient, data.topic)
    return {
        "text":          cleaned,
        "posters":       [p[2] if p[2] else f"{CONFIG['APP_BASE_URL']}/li_cache/{os.path.basename(p[0])}" for p in posters],
        "image_sources": [p[1] for p in posters],
        "image_thumbs":  [img.get("thumb","") for img in images],
        "topic":         data.topic, "headline": headline,
    }

# ── Images ─────────────────────────────────────────────────────────────────────
@app.post("/images/search")
async def image_search_post(data: ImageSearchIn):
    results = search_images(data.query, data.count)
    if not results:
        raise HTTPException(status_code=404, detail="No images found.")
    return {"images": results, "count": len(results)}

@app.get("/images/search")
async def image_search_get(q: str, count: int = 9):
    return {"images": search_images(q, count), "count": len(search_images(q, count))}

@app.post("/images/edit")
async def image_edit_endpoint(data: ImageEditIn):
    if not os.path.exists(data.image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return {"edited_path": edit_image(data.image_path, data.operations)}

# ── Post Now (instant, multipart) ──────────────────────────────────────────────
@app.post("/api/posts/instant")
async def publish_instant_post(
    text:  str                  = Form(...),
    urn:   str                  = Form(...),
    image: Optional[UploadFile] = File(None),
):
    token = get_token()
    if not token:
        raise HTTPException(status_code=401, detail="LinkedIn not authenticated.")
    image_path = None
    if image:
        suffix = Path(image.filename).suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await image.read())
            image_path = tmp.name
    try:
        if image_path and os.path.exists(image_path):
            st, resp = linkedin_post_with_image(token, urn, text, image_path)
            try: os.unlink(image_path)
            except: pass
        else:
            st, resp = linkedin_post_text(token, urn, text)
        if st in (200, 201):
            return {"status": "success", "response": resp}
        raise HTTPException(status_code=st, detail=str(resp))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/post/now")
async def post_now(data: PostNowIn):
    token   = _require_auth()
    profile = get_profile()
    urn     = profile.get("urn")
    cleaned = clean_for_linkedin(data.text)
    image_path = data.image_path.replace("/", os.sep) if data.image_path else None
    if image_path and os.path.exists(image_path):
        st, resp = linkedin_post_with_image(token, urn, cleaned, image_path)
    else:
        st, resp = linkedin_post_text(token, urn, cleaned)
    if st in (200, 201):
        return {"status": "posted"}
    raise HTTPException(status_code=st, detail=str(resp))

# ── Schedule Single ────────────────────────────────────────────────────────────
@app.post("/schedule")
async def schedule_job(
    text:               str                  = Form(...),
    scheduled_datetime: str                  = Form(...),
    post_type:          Optional[str]        = Form(""),
    image:              Optional[UploadFile] = File(None),
    approval_email:     Optional[str]        = Form(None),
):
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")
    try:
        datetime.datetime.strptime(scheduled_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Use format: YYYY-MM-DD HH:MM")

    # Determine approval email: from form → profile → CONFIG
    final_approval_email = (approval_email or profile.get("email","") or CONFIG["APPROVAL_EMAIL"] or "").strip()
    if not final_approval_email:
        logger.warning(f"[Schedule] No approval email available. Resend notifications will be skipped.")
    
    image_url = None
    if image and image.filename:
        suffix = Path(image.filename).suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await image.read())
            tmp_path = tmp.name
        if supabase:
            image_url = upload_image_to_supabase(tmp_path)
        try: os.unlink(tmp_path)
        except: pass

    job_id = str(uuid.uuid4())
    job = {
        "id": job_id, "text": text, "image_url": image_url,
        "datetime": scheduled_datetime, "status": "pending", "mode": "manual",
        "post_type": post_type or "", "urn": urn,
        "company": profile.get("company",""), "domain": profile.get("domain",""),
        "product": profile.get("product",""),
        "approval_email": final_approval_email,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    if supabase:
        try: supabase.table("scheduled_posts").insert(job).execute()
        except: save_job(job)
    else:
        save_job(job)
    
    logger.info(f"[Schedule] Job {job_id} → {scheduled_datetime} | Email: {final_approval_email}")

    # ── Send approval email immediately on scheduling ─────────────────────────
    email_sent = False
    if final_approval_email and CONFIG["SMTP_USER"] and CONFIG["SMTP_PASSWORD"]:
        try:
            approval_id = str(uuid.uuid4())
            save_approval({
                "id":            approval_id,
                "job_id":        job_id,
                "topic":         (text or "")[:80],
                "status":        "awaiting_approval",
                "variations":    [{"style": "Manual", "text": text}],
                "image_urls":    [image_url] if image_url else [],
                "scheduled_for": scheduled_datetime,
                "created_at":    datetime.datetime.utcnow().isoformat(),
            })
            update_job_status(job_id, "awaiting_approval")
            email_sent = send_manual_approval_email(final_approval_email, approval_id, job)
            logger.info(f"[Schedule] Approval email {'✅ sent' if email_sent else '❌ failed'} → {final_approval_email}")
        except Exception as e:
            logger.error(f"[Schedule] Approval email error: {e}")
    elif not final_approval_email:
        logger.warning("[Schedule] No approval email — set APPROVAL_EMAIL or add email to Brand Profile")
    elif not CONFIG["SMTP_USER"]:
        logger.warning("[Schedule] SMTP not configured — set SMTP_USER and SMTP_PASSWORD env vars")

    return {
        "status": "scheduled", "job_id": job_id, "scheduled_for": scheduled_datetime,
        "image_url": image_url, "approval_email": final_approval_email,
        "email_sent": email_sent,
    }

# ── AI Campaign (with Resend approval emails) ──────────────────────────────────
@app.post("/campaign/auto")
async def auto_campaign(data: AutoCampaignIn, background_tasks: BackgroundTasks):
    """
    Creates scheduled AI campaign jobs.
    Each job will receive a Resend approval email APPROVAL_LEAD_HOURS before its scheduled time.
    User clicks a variation in the email → post published instantly to LinkedIn.
    """
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")
    if not 1 <= data.days <= 90:
        raise HTTPException(status_code=400, detail="Days must be 1–90.")

    industry    = data.industry or profile.get("domain", "technology")
    domain      = data.domain   or profile.get("domain", "SaaS")
    product     = data.product  or profile.get("product", "software")
    total_posts = data.days * data.posts_per_day
    time_slots  = (data.time_slots or ["09:00", "14:00", "18:00"])[:data.posts_per_day]
    approval_email = data.approval_email or profile.get("email","") or CONFIG["APPROVAL_EMAIL"]

    try:
        start_date = datetime.datetime.strptime(data.start_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Use format: YYYY-MM-DD")

    topics = generate_ai_topics(industry, domain, product, profile.get("company",""), total_posts)
    if not topics:
        raise HTTPException(status_code=500, detail="Failed to generate topics. Check GEMINI_API_KEY.")
    while len(topics) < total_posts:
        topics.extend(topics)
    topics = topics[:total_posts]

    created, topic_idx = [], 0
    for day in range(data.days):
        day_dt = start_date + datetime.timedelta(days=day)
        for slot in time_slots:
            if topic_idx >= len(topics):
                break
            topic = topics[topic_idx]; topic_idx += 1
            try:
                h, m  = map(int, slot.split(":"))
                sched = day_dt.replace(hour=h, minute=m)
            except Exception:
                sched = day_dt
            job_id = str(uuid.uuid4())
            job = {
                "id": job_id,
                "datetime": sched.strftime("%Y-%m-%d %H:%M"),
                "status": "pending", "mode": "ai_auto",
                "topic": topic, "tone": data.tone, "mood": data.mood,
                "gradient": data.gradient, "urn": urn,
                "company": profile.get("company",""), "domain": domain, "product": product,
                "approval_email": approval_email,  # ← Resend sends here
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            if supabase:
                try: supabase.table("scheduled_posts").insert(job).execute()
                except: save_job(job)
            else:
                save_job(job)
            created.append({"id": job_id, "topic": topic, "datetime": sched.strftime("%Y-%m-%d %H:%M")})

    return {
        "status":           "campaign_created",
        "days":             data.days,
        "posts_per_day":    data.posts_per_day,
        "total_posts":      len(created),
        "approval_email":   approval_email,
        "resend_note":      f"Approval emails will be sent to {approval_email} via SMTP {CONFIG['APPROVAL_LEAD_HOURS']}h before each post.",
        "jobs":             created,
    }

# ── Campaign Approve (one-click from email) ────────────────────────────────────
@app.get("/campaign-approve/{approval_id}", response_class=HTMLResponse)
async def campaign_approve_handler(
    approval_id: str,
    action:    Optional[str] = None,
    choice:    Optional[str] = None,
    variation: Optional[int] = 0,
    image:     Optional[int] = 0,
):
    """
    One-click approval handler linked from Resend campaign emails.
    Clicking a variation in the email hits this endpoint → publishes to LinkedIn immediately.
    """
    approval = get_approval_by_id(approval_id)
    if not approval:
        return HTMLResponse(content=_inline_page("❌","Not Found","Approval not found.","#ef4444"), status_code=404)

    msg, color = "", "#0ea5e9"

    if action == "reject":
        update_approval(approval_id, {"status": "rejected"})
        if approval.get("job_id"):
            update_job_status(approval["job_id"], "rejected")
        msg, color = "Post rejected.", "#ef4444"

    elif action == "skip":
        update_approval(approval_id, {"status": "skipped"})
        if approval.get("job_id"):
            update_job_status(approval["job_id"], "skipped")
        msg, color = "Post skipped.", "#64748b"

    elif choice:
        vi    = ord(choice.lower()) - ord('a')
        vars_ = approval.get("variations", [])
        text  = vars_[vi].get("text", "") if 0 <= vi < len(vars_) else ""
        imgs  = approval.get("image_urls", [])
        selected_image_url = imgs[image] if imgs and 0 <= image < len(imgs) else ""

        update_approval(approval_id, {
            "status": "approved", "selected_variation": vi,
            "selected_image": image, "approved_text": text,
            "approved_at": datetime.datetime.utcnow().isoformat(),
        })
        if approval.get("job_id"):
            update_job_status(approval["job_id"], "approved", {
                "approved_text": text, "image_url": selected_image_url,
            })

        # Publish immediately
        try:
            job_id  = approval.get("job_id")
            all_jobs = get_all_jobs()
            job     = next((j for j in all_jobs if str(j.get("id")) == str(job_id)), None)
            li_token = get_token()
            profile  = get_profile()
            urn      = (job.get("urn") if job else None) or profile.get("urn", "")
            post_text = text or (job.get("text","") if job else "")

            image_path = download_temp_image(selected_image_url) if selected_image_url else None

            if li_token and urn and post_text:
                if image_path and os.path.exists(image_path):
                    st, resp = linkedin_post_with_image(li_token, urn, clean_for_linkedin(post_text), image_path)
                else:
                    st, resp = linkedin_post_text(li_token, urn, clean_for_linkedin(post_text))

                if 200 <= st < 300:
                    if job_id:
                        update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                    msg, color = f"Variation {choice.upper()} approved and published to LinkedIn! ✓", "#22c55e"
                else:
                    if job_id:
                        update_job_status(job_id, f"failed_http_{st}", {"linkedin_error": str(resp)})
                    msg, color = f"Approved but LinkedIn returned error {st}. Try again manually.", "#f59e0b"
            else:
                if job_id:
                    update_job_status(job_id, "failed_no_linkedin", {"linkedin_error": "missing token/urn"})
                msg, color = "Approved but LinkedIn not connected (no token/urn).", "#f59e0b"
        except Exception as ex:
            logger.exception(f"[CampaignApprove] {ex}")
            if approval.get("job_id"):
                update_job_status(approval["job_id"], "failed", {"linkedin_error": str(ex)})
            msg, color = f"Approved but posting failed: {str(ex)[:100]}", "#f59e0b"
    else:
        msg, color = "No action taken.", "#64748b"

    icon = "✅" if "published" in msg.lower() or "approved" in msg.lower() else ("❌" if "rejected" in msg.lower() else "⏭")
    return HTMLResponse(content=_inline_page(icon, "Campaign Approval", msg, color))

# ── Approvals (dashboard view) ─────────────────────────────────────────────────
@app.get("/approvals")
async def list_approvals(status: Optional[str] = None):
    approvals = get_approvals(status)
    return {"approvals": approvals, "count": len(approvals)}
@app.get("/debug/linkedin")
async def debug_linkedin():
    token = get_token()
    profile = get_profile()
    return {
        "token_exists": bool(token),
        "urn": profile.get("urn"),
        "name": profile.get("name"),
        "email": profile.get("email")
    }

@app.get("/debug/scheduler")
async def debug_scheduler():
    """Show scheduler status and upcoming approvals due."""
    now = datetime.datetime.now()
    lead_h = CONFIG["APPROVAL_LEAD_HOURS"]
    jobs = get_all_jobs()
    pending_jobs = [j for j in jobs if j.get("status") == "pending"]
    
    due_for_approval = []
    for j in pending_jobs:
        try:
            sched_dt = datetime.datetime.strptime(j.get("datetime",""), "%Y-%m-%d %H:%M")
            hours_until = (sched_dt - now).total_seconds() / 3600
            approval_email = j.get("approval_email") or ""
            if hours_until <= lead_h and hours_until > 0:
                due_for_approval.append({
                    "job_id": j.get("id"),
                    "scheduled": j.get("datetime"),
                    "hours_until": round(hours_until, 1),
                    "approval_email": approval_email,
                    "has_email": bool(approval_email),
                })
        except:
            pass
    
    return {
        "current_time": now.isoformat(),
        "approval_lead_hours": lead_h,
        "total_jobs": len(jobs),
        "pending_jobs": len(pending_jobs),
        "due_for_approval": due_for_approval,
        "smtp_configured": bool(CONFIG["SMTP_USER"] and CONFIG["SMTP_PASSWORD"]),
        "smtp_host": CONFIG["SMTP_HOST"],
        "smtp_port": CONFIG["SMTP_PORT"],
        "sender_email": CONFIG["SENDER_EMAIL"],
    }

@app.post("/debug/test-email")
async def test_email(to_email: str):
    """Send a test email via SMTP to verify email setup."""
    if not CONFIG["SMTP_USER"] or not CONFIG["SMTP_PASSWORD"]:
        raise HTTPException(status_code=400, detail="SMTP not configured: Set SMTP_USER and SMTP_PASSWORD")
    
    html = """<!DOCTYPE html><html>
<body style="background:#03050a;color:#e8f0fc;font-family:system-ui;padding:20px">
<div style="max-width:600px;margin:auto;background:#0e1828;border:1px solid #1b2d45;border-radius:12px;padding:24px">
  <h2 style="color:#0ea5e9">✅ Test Email from LinkedIn Studio PRO</h2>
  <p>If you're reading this, SMTP email is working correctly!</p>
  <p style="color:#8aa0bc;font-size:12px;margin-top:16px">Sent at """ + datetime.datetime.now().isoformat() + """</p>
  <p style="color:#8aa0bc;font-size:11px">Using SMTP server: """ + CONFIG["SMTP_HOST"] + """</p>
</div>
</body></html>"""
    
    try:
        sent = _smtp_send("Test Email — LinkedIn Studio PRO", html, to_email)
        if sent:
            return {"status": "sent", "to": to_email, "message": "Check your inbox!"}
        else:
            raise HTTPException(status_code=500, detail="SMTP send failed - check logs for details")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Send failed: {str(e)}")


@app.get("/debug/jobs-detailed")
async def debug_jobs_detailed():
    """Detailed job list with approval email status."""
    jobs = get_all_jobs()
    return {
        "total": len(jobs),
        "jobs": [
            {
                "id": j.get("id"),
                "datetime": j.get("datetime"),
                "status": j.get("status"),
                "approval_email": j.get("approval_email"),
                "text": j.get("text", "")[:60],
                "mode": j.get("mode"),
            }
            for j in jobs[-20:]  # Last 20 jobs
        ]
    }
@app.post("/approvals/action")
async def approval_action(data: ApprovalActionIn):
    approval = get_approval_by_id(data.approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    job_id = approval.get("job_id")
    if data.action == "approve":
        text = data.custom_text
        if not text:
            vars_ = approval.get("variations", [])
            if vars_ and data.variation_index < len(vars_):
                text = vars_[data.variation_index].get("text", "")
        update_approval(data.approval_id, {
            "status": "approved", "selected_variation": data.variation_index,
            "selected_image": data.image_index, "approved_text": text,
            "approved_at": datetime.datetime.utcnow().isoformat(),
        })
        if job_id:
            update_job_status(job_id, "approved", {"approved_text": text or ""})
        # Try immediate publish
        post_result = "approved"
        try:
            all_jobs = get_all_jobs()
            job = next((j for j in all_jobs if str(j.get("id")) == str(job_id)), None)
            if job and text:
                token = get_token(); profile = get_profile()
                urn   = job.get("urn") or profile.get("urn","")
                if token and urn:
                    imgs = approval.get("image_urls", [])
                    img_url = imgs[data.image_index] if imgs and data.image_index < len(imgs) else None
                    image_path = download_temp_image(img_url) if img_url else None
                    if image_path and os.path.exists(image_path):
                        st, resp = linkedin_post_with_image(token, urn, text, image_path)
                    else:
                        st, resp = linkedin_post_text(token, urn, text)
                    if st in (200, 201):
                        update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                        post_result = "approved_and_posted"
                    else:
                        update_job_status(job_id, f"failed_http_{st}", {"linkedin_error": str(resp)})
                        post_result = f"approved_linkedin_error_{st}"
                else:
                    update_job_status(job_id, "failed_no_linkedin", {"linkedin_error": "missing token/urn"})
                    post_result = "approved_no_linkedin"
        except Exception as err:
            logger.error(f"[ApprovalAction] {err}")
            if job_id:
                update_job_status(job_id, "failed", {"linkedin_error": str(err)})
            post_result = "approved_failed"
        return {"status": post_result, "approval_id": data.approval_id}
    elif data.action == "reject":
        update_approval(data.approval_id, {"status": "rejected"})
        if job_id: update_job_status(job_id, "rejected")
        return {"status": "rejected"}
    elif data.action == "skip":
        update_approval(data.approval_id, {"status": "skipped"})
        if job_id: update_job_status(job_id, "skipped")
        return {"status": "skipped"}
    raise HTTPException(status_code=400, detail="action must be: approve, reject, or skip")

# ── Jobs ───────────────────────────────────────────────────────────────────────
@app.get("/jobs")
async def list_jobs(status: Optional[str] = None):
    jobs = get_all_jobs(status)
    return {
        "stats": {
            "total":    len(jobs),
            "pending":  sum(1 for j in jobs if j.get("status") == "pending"),
            "posted":   sum(1 for j in jobs if j.get("status") == "posted"),
            "failed":   sum(1 for j in jobs if "failed" in str(j.get("status",""))),
            "approved": sum(1 for j in jobs if j.get("status") == "approved"),
        },
        "jobs": jobs,
    }

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    if not delete_job_by_id(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted", "job_id": job_id}

@app.delete("/jobs")
async def clear_all_jobs():
    if supabase:
        try: supabase.table("scheduled_posts").delete().neq("id","").execute()
        except Exception as e: logger.warning(f"[Supabase] clear: {e}")
    _save_json(_JOBS_FILE, [])
    return {"status": "all_jobs_cleared"}

# ── Serve cache ────────────────────────────────────────────────────────────────
@app.get("/li_cache/{filename}")
async def serve_cache(filename: str):
    path = os.path.join(CONFIG["CACHE_DIR"], filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

# ═══════════════════════════════════════════════════════════════════════════════
#  EMAIL AGENT ROUTES  (Resend only — no SMTP)
#
#  Full flow:
#    POST /email/send-topics
#      → Resend sends topic-selection email to user
#      → User clicks a topic  →  GET /select-topic/{token}
#      → AI drafts post + fetches image
#      → Resend sends approval email  →  GET /email-approve/{token}
#      → Post published to LinkedIn (text or text+image)
#
#  Token store: pending_approvals.json  (file-based, single-user)
# ═══════════════════════════════════════════════════════════════════════════════

_EA_STORE_FILE = "pending_approvals.json"

def _ea_load() -> dict:
    if os.path.exists(_EA_STORE_FILE):
        try:
            with open(_EA_STORE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _ea_save(store: dict):
    with open(_EA_STORE_FILE, "w") as f:
        json.dump(store, f, indent=2)

def _ea_create_token(data: dict) -> str:
    token = secrets.token_urlsafe(32)
    store = _ea_load()
    store[token] = data
    _ea_save(store)
    return token

def _ea_consume_token(token: str, expected_type: str) -> Optional[dict]:
    store = _ea_load()
    data  = store.pop(token, None)
    if not data or data.get("type") != expected_type:
        if data:
            store[token] = data   # put back if wrong type
        _ea_save(store)
        return None
    data.pop("type", None)
    _ea_save(store)
    return data

def _ea_resend(subject: str, html: str, to_email: str) -> bool:
    """Send via SMTP (replaces old Resend SDK calls — all email is SMTP now)."""
    return _smtp_send(subject, html, to_email)

def _ea_topic_email_html(tokenized_topics: list) -> str:
    base_url = CONFIG["APP_BASE_URL"]
    cards = ""
    for i, item in enumerate(tokenized_topics, 1):
        topic     = item["topic"]
        label     = topic if isinstance(topic, str) else topic.get("topic", str(topic))
        angle     = "" if isinstance(topic, str) else topic.get("angle", "")
        sel_url   = f"{base_url}/select-topic/{item['token']}"
        cards += f"""
<div style="border:1px solid #1e3a5f;border-radius:10px;padding:16px;margin-bottom:14px;background:#0a1628">
  <div style="color:#0ea5e9;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em">Topic {i}</div>
  <div style="font-size:15px;font-weight:600;margin:8px 0 4px;color:#f0f6fc">{escape(label)}</div>
  {"<div style='font-size:13px;color:#94a3b8;margin-bottom:10px'>" + escape(angle) + "</div>" if angle else ""}
  <a href="{sel_url}" style="display:inline-block;background:#0ea5e9;color:#000;border-radius:6px;
     padding:9px 18px;font-size:13px;font-weight:700;text-decoration:none;margin-top:6px">
    Select this topic →
  </a>
</div>"""
    return f"""<!DOCTYPE html><html>
<body style="font-family:'Segoe UI',sans-serif;background:#03050a;padding:24px;margin:0">
<div style="background:#0a1628;border-radius:14px;max-width:600px;margin:0 auto;
     border:1px solid #1b2d45;overflow:hidden">
  <div style="background:linear-gradient(135deg,#0ea5e9,#a855f7);padding:22px 28px">
    <h1 style="color:#fff;margin:0;font-size:20px">🎯 Choose Today's LinkedIn Topic</h1>
    <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:13px">
      Pick one — AI will draft the full post + find an image. You approve before it goes live.
    </p>
  </div>
  <div style="padding:22px 28px">{cards}</div>
  <div style="padding:12px 28px;border-top:1px solid #1e3a5f;font-size:11px;color:#475569">
    Nothing publishes until you click Approve in the next email.
  </div>
</div>
</body></html>"""

def _ea_approval_email_html(post_text: str, topic: str, approve_url: str, reject_url: str,
                             image_url: str = None, photographer: str = None) -> str:
    escaped_post  = escape(post_text).replace("\n", "<br>")
    escaped_topic = escape(topic[:80])
    img_block = ""
    if image_url:
        img_block = f"""
<div style="margin:18px 0 0">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:6px">
    Auto-selected image
  </div>
  <div style="border:1px solid #1e3a5f;border-radius:8px;overflow:hidden">
    <img src="{escape(image_url)}" style="width:100%;max-height:280px;object-fit:cover;display:block">
    {"<div style='padding:8px 12px;background:#0e1828;font-size:11px;color:#64748b'>📷 " + escape(photographer or "Stock Photo") + "</div>" if photographer else ""}
  </div>
</div>"""
    return f"""<!DOCTYPE html><html>
<body style="font-family:'Segoe UI',sans-serif;background:#03050a;padding:24px;margin:0">
<div style="background:#0a1628;border-radius:14px;max-width:600px;margin:0 auto;
     border:1px solid #1b2d45;overflow:hidden">
  <div style="background:linear-gradient(135deg,#0ea5e9,#a855f7);padding:22px 28px">
    <h1 style="color:#fff;margin:0;font-size:20px">🚀 LinkedIn Post Ready for Approval</h1>
    <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:13px">
      Click Approve to publish instantly to LinkedIn.
    </p>
  </div>
  <div style="padding:22px 28px">
    <div style="display:inline-block;background:#0ea5e9;color:#000;border-radius:6px;
         padding:4px 12px;font-size:13px;font-weight:700;margin-bottom:16px">
      {escaped_topic}
    </div>
    <div style="background:#0e1828;border:1px solid #1e3a5f;border-radius:8px;padding:16px;
         font-size:14px;line-height:1.8;color:#e8f0fc">
      {escaped_post}
    </div>
    {img_block}
  </div>
  <div style="padding:0 28px 24px;display:flex;gap:12px">
    <a href="{approve_url}" style="display:inline-block;background:#0ea5e9;color:#000;
       border-radius:8px;padding:13px 30px;font-size:15px;font-weight:700;text-decoration:none">
      ✓ Approve &amp; Post to LinkedIn
    </a>
    <a href="{reject_url}" style="display:inline-block;background:rgba(239,68,68,.15);color:#ef4444;
       border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:13px 22px;
       font-size:15px;font-weight:700;text-decoration:none">
      ✗ Reject
    </a>
  </div>
  <div style="padding:12px 28px;border-top:1px solid #1e3a5f;font-size:11px;color:#475569">
    Auto-generated by LinkedIn Studio PRO. Will not publish unless you click Approve.
  </div>
</div>
</body></html>"""

# ── POST /email/send-topics ────────────────────────────────────────────────────
class SendTopicsEmailIn(BaseModel):
    topics: List[str] = []
    to_email: Optional[str] = None

@app.post("/email/send-topics")
async def api_send_topics_email(data: SendTopicsEmailIn):
    """
    Send a topic-selection email via Resend.
    If topics list is empty, AI auto-generates from brand profile.
    """
    profile  = get_profile()
    topics   = data.topics
    to_email = data.to_email or profile.get("email", "") or CONFIG["APPROVAL_EMAIL"]

    if not to_email:
        raise HTTPException(status_code=400,
            detail="No recipient email. Add email to Brand Profile or set APPROVAL_EMAIL env var.")

    # Auto-generate topics from brand profile if none provided
    if not topics:
        topics = generate_ai_topics(
            company=profile.get("company", ""),
            domain=profile.get("domain", ""),
            product=profile.get("product", ""),
            name=profile.get("name", ""),
            count=5,
        )
    if not topics:
        raise HTTPException(status_code=500, detail="Could not generate topics. Check GEMINI_API_KEY.")

    # Create one secure token per topic
    tokenized = []
    for t in topics:
        token = _ea_create_token({"type": "topic_selection", "topic": t, "to_email": to_email})
        tokenized.append({"token": token, "topic": t})

    html = _ea_topic_email_html(tokenized)
    sent = _ea_resend("[LinkedIn Studio] Choose today's topic", html, to_email)

    # Log clickable URLs for dummy/debug mode
    if not sent:
        for item in tokenized:
            logger.info(f"[EmailAgent] Select URL: {CONFIG['APP_BASE_URL']}/select-topic/{item['token']}")

    return {
        "status":    "sent" if sent else "dummy_mode",
        "recipient": to_email,
        "count":     len(tokenized),
        "topics":    topics,
        "note":      "Check SMTP_USER/SMTP_PASSWORD env vars if email was not received." if not sent else "",
    }

# ── GET /select-topic/{token} — user clicks topic in email ────────────────────
@app.get("/select-topic/{token}", response_class=HTMLResponse)
async def select_topic_handler(token: str):
    """
    User clicks a topic in the topic-selection email.
    AI generates full post + fetches an image → sends approval email.
    """
    data = _ea_consume_token(token, "topic_selection")
    if not data:
        return HTMLResponse(
            content=_inline_page("❌", "Invalid Link",
                "This topic link has already been used or is invalid.", "#ef4444"),
            status_code=404)

    topic_str = data["topic"] if isinstance(data["topic"], str) else data["topic"].get("topic", str(data["topic"]))
    to_email  = data.get("to_email") or CONFIG["APPROVAL_EMAIL"]
    profile   = get_profile()

    if not profile.get("company"):
        return HTMLResponse(content=_inline_page("⚠️", "Profile Missing",
            "Brand profile not set. Please configure your profile first.", "#f59e0b"))

    try:
        # 1. Generate post text
        post_text = clean_for_linkedin(
            generate_post_text(profile, "Brand Announcement", "Executive Authority", "Professional", topic_str)
        )

        # 2. Fetch one relevant image
        images     = fetch_images_for_post(profile, "Brand Announcement", "Professional", topic_str, count=1)
        image_url  = images[0]["url"]   if images else None
        thumb_url  = images[0]["thumb"] if images else None
        photographer = images[0].get("photographer", "") if images else ""

        # 3. Create approval token  (stores post + image info)
        approval_token = _ea_create_token({
            "type":         "post_approval",
            "post":         post_text,
            "topic":        topic_str,
            "image_url":    image_url,
            "thumb_url":    thumb_url,
            "photographer": photographer,
            "to_email":     to_email,
        })

        approve_url = f"{CONFIG['APP_BASE_URL']}/email-approve/{approval_token}"
        reject_url  = f"{CONFIG['APP_BASE_URL']}/email-reject/{approval_token}"

        # 4. Send approval email via Resend
        html = _ea_approval_email_html(
            post_text, topic_str, approve_url, reject_url,
            image_url=thumb_url, photographer=photographer,
        )
        sent = _ea_resend(f"[LinkedIn Studio] Post ready: {topic_str[:50]}", html, to_email)

        if not sent:
            logger.info(f"[EmailAgent] Approve URL: {approve_url}")

        return HTMLResponse(content=_inline_page(
            "🚀", "Topic Selected!",
            f"Draft for '{topic_str[:60]}' generated and {'sent to your inbox for approval.' if sent else 'ready (check SMTP_USER/SMTP_PASSWORD env vars if email not received).'}",
            "#0ea5e9"))

    except Exception as e:
        logger.error(f"[EmailAgent] select-topic error: {e}")
        return HTMLResponse(content=_inline_page("❌", "Error", str(e)[:120], "#ef4444"), status_code=500)

# ── GET /email-approve/{token} — user clicks Approve in email ─────────────────
@app.get("/email-approve/{token}", response_class=HTMLResponse)
async def email_approve_handler(token: str):
    """
    User clicks 'Approve & Post' in the approval email.
    Publishes the post (with image if available) to LinkedIn immediately.
    """
    data = _ea_consume_token(token, "post_approval")
    if not data:
        return HTMLResponse(
            content=_inline_page("❌", "Invalid Link",
                "This approval link has already been used or is invalid.", "#ef4444"),
            status_code=404)

    li_token = get_token()
    profile  = get_profile()
    urn      = profile.get("urn", "")

    if not li_token or not urn:
        return HTMLResponse(content=_inline_page("⚠️", "LinkedIn Not Connected",
            "LinkedIn account is not connected. Please authenticate first.", "#f59e0b"), status_code=401)

    post_text  = clean_for_linkedin(data.get("post", ""))
    image_url  = data.get("image_url")
    image_path = None

    # Download image to temp file
    if image_url:
        image_path = download_temp_image(image_url)

    try:
        if image_path and os.path.exists(image_path):
            st, resp = linkedin_post_with_image(li_token, urn, post_text, image_path)
        else:
            st, resp = linkedin_post_text(li_token, urn, post_text)

        # Cleanup temp file
        if image_path:
            try: os.unlink(image_path)
            except: pass

        if st in (200, 201):
            logger.info(f"[EmailAgent] Post published via email approval ✓")
            return HTMLResponse(content=_inline_page(
                "✅", "Published to LinkedIn!",
                "Your post has been published successfully. Check your LinkedIn profile.", "#22c55e"))
        else:
            logger.error(f"[EmailAgent] LinkedIn error {st}: {resp}")
            return HTMLResponse(content=_inline_page(
                "⚠️", "Publish Failed",
                f"LinkedIn returned error {st}. Please try posting manually.", "#f59e0b"))

    except Exception as e:
        logger.error(f"[EmailAgent] email-approve error: {e}")
        return HTMLResponse(content=_inline_page("❌", "Error", str(e)[:120], "#ef4444"), status_code=500)

# ── GET /email-reject/{token} — user clicks Reject in email ──────────────────
@app.get("/email-reject/{token}", response_class=HTMLResponse)
async def email_reject_handler(token: str):
    """User clicks Reject in the approval email — consumes token without posting."""
    data = _ea_consume_token(token, "post_approval")
    if not data:
        return HTMLResponse(content=_inline_page("❌", "Invalid Link",
            "This link has already been used or is invalid.", "#ef4444"), status_code=404)
    logger.info(f"[EmailAgent] Post rejected via email")
    return HTMLResponse(content=_inline_page(
        "🚫", "Post Rejected",
        "The post has been rejected and will not be published to LinkedIn.", "#ef4444"))

# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home():
    for f in ["index.html", "linkedin-studio-pro (4).html", "frontend.html"]:
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                return HTMLResponse(content=fh.read())
    return HTMLResponse(content="""<!DOCTYPE html><html>
<head><title>LinkedIn Studio PRO v4.2</title></head>
<body style="background:#03050a;color:#e8f0fc;font-family:system-ui;padding:40px;text-align:center">
<h1 style="color:#0ea5e9">LinkedIn Studio PRO v4.2</h1>
<p>Place <code>index.html</code> in the same folder as <code>main.py</code>.</p>
<p><a href="/docs" style="color:#0ea5e9">→ API Docs</a></p>
</body></html>""")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["PORT"], reload=False, log_level="info")
