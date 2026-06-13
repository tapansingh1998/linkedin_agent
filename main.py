"""
LinkedIn Studio PRO v4.3 — RESEND EMAIL (No SMTP)
- Uses Resend API instead of SMTP (works on Render free tier)
- Port blocking issue completely solved
- Approval email sends immediately on scheduling
- One-click approve → posts to LinkedIn instantly
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

# ── Resend (replaces smtplib completely) ──────────────────────────────────────
try:
    import resend
    HAS_RESEND = True
except ImportError:
    HAS_RESEND = False
    logger.warning("resend not installed — run: pip install resend")

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-generativeai not installed")

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
    "APPROVAL_LEAD_HOURS":    int(os.environ.get("APPROVAL_LEAD_HOURS", 720)),

    # ── Resend (HTTP API — no port blocking) ──────────────────────────────────
    # 1. Sign up free at resend.com
    # 2. Add & verify your domain (or use onboarding@resend.dev for testing)
    # 3. Create API key at resend.com/api-keys
    # 4. Set RESEND_API_KEY in Render environment variables
    # 5. Set SENDER_EMAIL to a verified email, e.g. noreply@yourdomain.com
    #    (For testing without domain: use onboarding@resend.dev)
    "RESEND_API_KEY": "re_8WkcNH3E_2JPvza3xkmvG5sP4eBvX7Mgp",
    "SENDER_EMAIL":    "onboarding@resend.dev",
    "APPROVAL_EMAIL":  os.environ.get("APPROVAL_EMAIL", ""),

    "OPENROUTER_API_KEY":  os.environ.get("OPENROUTER_API_KEY", ""),
    "OPENROUTER_MODEL":    os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
}

os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
os.makedirs(CONFIG["SCHEDULED_IMAGES_DIR"], exist_ok=True)

# ── Gemini rotating keys ───────────────────────────────────────────────────────
GEMINI_API_KEYS = [k for k in [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 11)] if k]
_single = os.getenv("GEMINI_API_KEY", "")
if _single and _single not in GEMINI_API_KEYS:
    GEMINI_API_KEYS.insert(0, _single)

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
#  PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════
_TOKEN_FILE    = "li_tokens.json"
_PROFILE_FILE  = "li_profile.json"
_JOBS_FILE     = "scheduler_jobs.json"
_APPROVALS_FILE = "li_approvals.json"

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
#  RESEND EMAIL  ←  replaces all smtplib code
#
#  Setup (5 minutes):
#  1. resend.com → Sign up free
#  2. resend.com/domains → Add & verify your domain
#     (Testing only: use "delivered@resend.dev" as to_email — no domain needed)
#  3. resend.com/api-keys → Create key → copy it
#  4. Render → Environment → Add:
#       RESEND_API_KEY = re_xxxxxxxxxxxx
#       SENDER_EMAIL   = noreply@yourdomain.com
#       APPROVAL_EMAIL = you@youremail.com
# ═══════════════════════════════════════════════════════════════════════════════

def _resend_send(subject: str, html: str, to_email: str) -> bool:
    """
    Send email using Resend HTTP API.
    No ports. No SMTP. Works on any cloud host including Render free tier.
    """
    api_key = CONFIG["RESEND_API_KEY"]
    sender  = CONFIG["SENDER_EMAIL"] or "onboarding@resend.dev"

    if not api_key:
        logger.warning("[Resend] RESEND_API_KEY not set — skipping email")
        logger.warning("[Resend] Get a free key at resend.com/api-keys")
        return False

    if not HAS_RESEND:
        # Fallback: use raw HTTP if resend package not installed
        try:
            resp = http_requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"LinkedIn Studio PRO <{sender}>",
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                },
                timeout=15,
            )
            if resp.status_code in (200, 201):
                logger.info(f"[Resend] ✅ Email sent to {to_email} | {subject}")
                return True
            else:
                logger.error(f"[Resend] ❌ HTTP {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"[Resend] ❌ {type(e).__name__}: {e}")
            return False

    # Use official resend SDK
    try:
        resend.api_key = api_key
        params = {
            "from": f"LinkedIn Studio PRO <{sender}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        result = resend.Emails.send(params)
        # SDK returns dict with 'id' on success
        if result and result.get("id"):
            logger.info(f"[Resend] ✅ Email sent to {to_email} | id={result['id']} | {subject}")
            return True
        else:
            logger.error(f"[Resend] ❌ Unexpected response: {result}")
            return False
    except Exception as e:
        logger.error(f"[Resend] ❌ {type(e).__name__}: {e}")
        return False


def _build_approval_html(approval_id: str, job_data: dict, variations: list, image_urls: list) -> str:
    """Beautiful approval email. Each variation button = approve + post immediately."""
    base_url = CONFIG["APP_BASE_URL"]
    topic    = escape(job_data.get("topic") or job_data.get("text", "LinkedIn Post")[:80])
    sched    = job_data.get("datetime", "")

    var_html = ""
    for i, v in enumerate(variations):
        label       = chr(65 + i)
        approve_url = f"{base_url}/campaign-approve/{approval_id}?choice={label.lower()}&variation={i}"
        text_preview = escape((v.get("text") or "")[:600])
        var_html += f"""
<div style="background:#0e1828;border:1px solid #1e3a5f;border-radius:10px;padding:18px;margin:12px 0">
  <div style="color:#0ea5e9;font-weight:700;font-size:12px;margin-bottom:10px;text-transform:uppercase">
    {'Variation ' + label + ' — ' + escape(v.get('style', '')) if len(variations) > 1 else 'Post Preview'}
  </div>
  <div style="color:#c8d6e5;font-size:13px;white-space:pre-wrap;line-height:1.75;
       background:#060d1a;border-radius:6px;padding:12px;border:1px solid #162030">
{text_preview}{'…' if len(v.get('text',''))>600 else ''}
  </div>
  <a href="{approve_url}"
     style="display:inline-block;margin-top:14px;padding:12px 28px;background:#0ea5e9;
            color:#000;border-radius:6px;font-size:14px;font-weight:700;text-decoration:none">
    ✓ Approve &amp; Post {'Variation ' + label if len(variations) > 1 else 'to LinkedIn'}
  </a>
</div>"""

    img_html = ""
    if image_urls:
        img_html = "<h3 style='color:#f0f6fc;margin:24px 0 12px;font-size:14px'>📸 Post with an image</h3>"
        img_html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
        for i, img_url in enumerate(image_urls[:3]):
            approve_img_url = f"{base_url}/campaign-approve/{approval_id}?choice=a&variation=0&image={i}"
            img_html += f"""
<a href="{approve_img_url}" style="text-decoration:none">
  <div style="border:2px solid #1e3a5f;border-radius:8px;overflow:hidden;width:180px;cursor:pointer">
    <img src="{escape(img_url)}" style="width:180px;height:115px;object-fit:cover;display:block" alt="Image {i+1}">
    <div style="padding:8px;text-align:center;color:#0ea5e9;font-size:11px;font-weight:700;background:#0a1628">
      Use Image {i+1}
    </div>
  </div>
</a>"""
        img_html += "</div>"

    reject_url = f"{base_url}/campaign-approve/{approval_id}?action=reject"
    skip_url   = f"{base_url}/campaign-approve/{approval_id}?action=skip"

    return f"""<!DOCTYPE html><html>
<body style="background:#03050a;color:#f0f6fc;font-family:'Segoe UI',Arial,sans-serif;padding:0;margin:0">
<div style="max-width:680px;margin:32px auto;background:#0a1628;border:1px solid #1e3a5f;border-radius:16px;overflow:hidden">
  <div style="background:linear-gradient(135deg,#0ea5e9,#a855f7);padding:28px 32px">
    <h1 style="margin:0;font-size:20px;color:#fff">🚀 LinkedIn Post Ready for Approval</h1>
    <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px">
      Click any button below → post goes live on LinkedIn instantly.
    </p>
  </div>
  <div style="padding:24px 32px">
    <div style="background:#0e1828;border-radius:8px;padding:12px 16px;margin-bottom:20px">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em">Topic / Post</div>
      <strong style="font-size:14px">{topic}</strong>
      {f'<br><div style="font-size:11px;color:#64748b;margin-top:4px">Scheduled: {sched}</div>' if sched else ''}
    </div>
    {var_html}
    {img_html}
    <div style="margin-top:28px;display:flex;gap:10px;padding-top:20px;border-top:1px solid #1e3a5f">
      <a href="{reject_url}"
         style="padding:10px 22px;background:rgba(239,68,68,0.15);color:#ef4444;
                border:1px solid rgba(239,68,68,0.3);border-radius:6px;font-size:12px;
                font-weight:700;text-decoration:none">✗ Reject</a>
      <a href="{skip_url}"
         style="padding:10px 22px;background:rgba(100,116,139,0.15);color:#94a3b8;
                border:1px solid rgba(100,116,139,0.3);border-radius:6px;font-size:12px;
                font-weight:700;text-decoration:none">⏭ Skip</a>
    </div>
    <p style="color:#334155;font-size:10px;margin-top:16px">
      LinkedIn Studio PRO · Will not publish unless you click Approve.
    </p>
  </div>
</div>
</body></html>"""


def send_approval_email(to_email: str, approval_id: str, job_data: dict,
                        variations: list, image_urls: list) -> bool:
    topic = job_data.get("topic") or (job_data.get("text", "")[:50]) or "LinkedIn Post"
    html  = _build_approval_html(approval_id, job_data, variations, image_urls)
    return _resend_send(f"🚀 Approve LinkedIn Post — {topic[:50]}", html, to_email)


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
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  CONFIG["LINKEDIN_REDIRECT_URI"],
            "client_id":     CONFIG["LINKEDIN_CLIENT_ID"],
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
        "author":       f"urn:li:person:{urn}",
        "commentary":   text,
        "visibility":   "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities":   [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState":          "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = http_requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization":             f"Bearer {access_token}",
            "LinkedIn-Version":           "202405",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type":              "application/json",
        },
        json=payload, timeout=30,
    )
    try:
        return r.status_code, r.json()
    except Exception:
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
            "owner":   f"urn:li:person:{urn}",
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
        headers={"Authorization": f"Bearer {access_token}"}, timeout=60,
    )
    if upload_resp.status_code not in (200, 201):
        return upload_resp.status_code, upload_resp.text

    payload = {
        "author":     f"urn:li:person:{urn}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities":   [],
            "thirdPartyDistributionChannels": []
        },
        "content": {"media": {"id": asset_urn}},
        "lifecycleState":          "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = http_requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization":             f"Bearer {access_token}",
            "LinkedIn-Version":           "202405",
            "Content-Type":              "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text

def _publish_to_linkedin(token: str, urn: str, text: str, image_url: str = None) -> tuple:
    image_path = None
    if image_url:
        image_path = download_temp_image(image_url)
    try:
        if image_path and os.path.exists(image_path):
            st, resp = linkedin_post_with_image(token, urn, text, image_path)
        else:
            st, resp = linkedin_post_text(token, urn, text)
        return st, resp
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI AI
# ═══════════════════════════════════════════════════════════════════════════════
GEMINI_MODELS_FALLBACK = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
OPENROUTER_MODELS_FALLBACK = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat:free",
]

def get_next_gemini_model(model_name: str = None, key_idx: int = None):
    global _current_key_index
    with _key_lock:
        if key_idx is not None:
            idx = key_idx % len(GEMINI_API_KEYS)
        else:
            idx = _current_key_index
            _current_key_index = (_current_key_index + 1) % len(GEMINI_API_KEYS)
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
                    "Content-Type":  "application/json",
                    "X-Title":       "LinkedIn Studio PRO",
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
        return openrouter_generate(prompt) or "[AI error: No GEMINI_API_KEY set]"
    primary = CONFIG.get("GEMINI_MODEL", "gemini-2.0-flash")
    models  = [primary] + [m for m in GEMINI_MODELS_FALLBACK if m != primary]
    for model_name in models:
        for attempt in range(len(GEMINI_API_KEYS)):
            try:
                model, _, _ = get_next_gemini_model(model_name, key_idx=attempt)
                return model.generate_content(prompt).text.strip()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("429", "quota", "rate limit", "resource_exhausted")):
                    _key_cooldowns[attempt] = time.time() + _KEY_COOLDOWN_SECS
                    continue
                break
    result = openrouter_generate(prompt)
    return result if result else "[AI temporarily unavailable. Please try again.]"

# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE SEARCH
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
#  IMAGE GENERATION (PIL)
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
    acc = _hex_to_rgb(accent_hex); drk = _hex_to_rgb(dark_hex)
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
            bg_img   = Image.open(raw_path).convert("RGB")
            poster   = LAYOUT_BUILDERS[i % len(LAYOUT_BUILDERS)](bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex)
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

def generate_ai_topics(company: str, domain: str, product: str, name: str, count: int = 5) -> list:
    if not (company or domain or product):
        return []
    prompt = f"""LinkedIn content strategist for {domain} company selling {product}.
Company: {company} | Person: {name}
Generate {count} highly specific LinkedIn post ideas tied to {domain} and {product}.
Return ONLY a JSON array of {count} strings. No markdown, no explanation."""
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
# ═══════════════════════════════════════════════════════════════════════════════
def _post_approved_jobs():
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
            st, resp = _publish_to_linkedin(token, urn, text, job.get("image_url"))
            if st in (200, 201):
                update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                logger.info(f"[Scheduler] Job {job_id} posted ✓")
            else:
                update_job_status(job_id, f"failed_http_{st}")
                logger.error(f"[Scheduler] Job {job_id} LinkedIn error {st}: {resp}")
        except Exception as e:
            logger.exception(f"[Scheduler] Job {job_id}: {e}")
            update_job_status(job_id, "failed")

def run_scheduler_daemon():
    logger.info("[Scheduler] Started")
    while True:
        try:
            _post_approved_jobs()
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

app = FastAPI(title="LinkedIn Studio PRO", version="4.3.0", lifespan=lifespan)
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
    approval_email: Optional[str] = None

class ImageEditIn(BaseModel):
    image_path: str; operations: Dict[str, Any]

class ImageSearchIn(BaseModel):
    query: str; count: int = 9

class ApprovalActionIn(BaseModel):
    approval_id: str; action: str
    variation_index: int = 0; image_index: int = 0
    custom_text: Optional[str] = None

# ── Helpers ────────────────────────────────────────────────────────────────────
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
border-radius:16px;max-width:520px;width:90%}}</style></head>
<body><div class="card">
<div style="font-size:56px">{icon}</div>
<h2 style="color:{color};margin:16px 0 8px">{title}</h2>
<p style="color:#8aa0bc;line-height:1.6">{message}</p>
<p style="color:#4a6080;font-size:12px;margin-top:20px">You can close this tab.</p>
</div></body></html>"""

# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    resend_ok = bool(CONFIG["RESEND_API_KEY"])
    return {
        "status": "ok", "version": "4.3.0", "scheduler": "running",
        "gemini":         HAS_GEMINI and len(GEMINI_API_KEYS) > 0,
        "linkedin_token": bool(get_token()),
        "supabase":       bool(supabase),
        "pixabay":        bool(CONFIG["PIXABAY_API_KEY"]),
        "pexels":         bool(CONFIG["PEXELS_API_KEY"]),
        "resend_ready":   resend_ok,
        "resend_sdk":     HAS_RESEND,
        "sender_email":   CONFIG["SENDER_EMAIL"] or "NOT SET",
        "pillow":         HAS_PIL,
    }

@app.get("/analytics")
async def get_analytics():
    jobs = get_all_jobs()
    now  = datetime.datetime.now()
    weekly: Dict[str,int] = {}
    for j in jobs:
        try:
            dt = datetime.datetime.strptime(j.get("datetime",""), "%Y-%m-%d %H:%M")
            weekly[dt.strftime("%Y-W%W")] = weekly.get(dt.strftime("%Y-W%W"), 0) + 1
        except Exception:
            pass
    total    = len(jobs)
    posted   = sum(1 for j in jobs if j.get("status") == "posted")
    failed   = sum(1 for j in jobs if "failed" in str(j.get("status","")))
    approved = sum(1 for j in jobs if j.get("status") in ("approved","posted"))
    return {
        "total_posts": total, "posted": posted, "failed": failed, "approved": approved,
        "approval_rate": round(approved/total*100 if total else 0, 1),
        "success_rate":  round(posted/(posted+failed)*100 if (posted+failed) else 0, 1),
        "posts_per_week": weekly,
    }

@app.get("/auth/login")
async def auth_login():
    if not CONFIG["LINKEDIN_CLIENT_ID"]:
        raise HTTPException(status_code=500, detail="LINKEDIN_CLIENT_ID not configured")
    return RedirectResponse(url=linkedin_get_auth_url())

@app.get("/auth/url")
async def auth_get_url():
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

@app.post("/profile")
async def set_profile(data: ProfileIn):
    profile = get_profile()
    profile.update({k: v for k, v in data.dict().items() if v is not None})
    save_profile(profile)
    return {"status": "saved", "profile": profile}

@app.get("/profile")
async def read_profile():
    return get_profile()

@app.post("/generate-topics")
async def gen_topics():
    p = get_profile()
    if not p.get("company") and not p.get("domain"):
        raise HTTPException(status_code=400, detail="Set your Brand Profile first (Company + Domain required).")
    topics = generate_ai_topics(p.get("company",""), p.get("domain",""), p.get("product",""), p.get("name",""), count=10)
    if not topics:
        raise HTTPException(status_code=500, detail="Could not generate topics. Check GEMINI_API_KEY.")
    return {"topics": topics, "count": len(topics)}

@app.post("/rewrite")
async def rewrite(data: RewriteIn):
    return {"original": data.text, "rewritten": rewrite_post(data.text, data.style), "style": data.style}

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
    if image and image.filename:
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

    final_email = (approval_email or profile.get("email","") or CONFIG["APPROVAL_EMAIL"] or "").strip()

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
        "approval_email": final_email,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    save_job(job)

    email_sent = False
    approval_id = str(uuid.uuid4())
    if final_email:
        variations = [{"style": "Manual", "text": text}]
        image_urls = [image_url] if image_url else []
        save_approval({
            "id":            approval_id,
            "job_id":        job_id,
            "topic":         text[:80],
            "status":        "awaiting_approval",
            "variations":    variations,
            "image_urls":    image_urls,
            "scheduled_for": scheduled_datetime,
            "created_at":    datetime.datetime.utcnow().isoformat(),
        })
        update_job_status(job_id, "awaiting_approval")
        email_sent = send_approval_email(final_email, approval_id, job, variations, image_urls)
        logger.info(f"[Schedule] Resend email {'✅ sent' if email_sent else '❌ failed'} → {final_email}")

    return {
        "status": "scheduled", "job_id": job_id,
        "scheduled_for": scheduled_datetime,
        "approval_email": final_email,
        "email_sent": email_sent,
    }

@app.post("/campaign/auto")
async def auto_campaign(data: AutoCampaignIn, background_tasks: BackgroundTasks):
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")
    if not 1 <= data.days <= 90:
        raise HTTPException(status_code=400, detail="Days must be 1–90.")

    industry       = data.industry or profile.get("domain", "technology")
    domain         = data.domain   or profile.get("domain", "SaaS")
    product        = data.product  or profile.get("product", "software")
    total_posts    = data.days * data.posts_per_day
    time_slots     = (data.time_slots or ["09:00"])[:data.posts_per_day]
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
                "approval_email": approval_email,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            save_job(job)
            created.append({"id": job_id, "topic": topic, "datetime": sched.strftime("%Y-%m-%d %H:%M")})

    if approval_email:
        def send_campaign_emails():
            for job_info in created:
                try:
                    job_data = next(
                        (j for j in get_all_jobs() if str(j.get("id")) == job_info["id"]),
                        {"topic": job_info["topic"], "datetime": job_info["datetime"]}
                    )
                    pdata = {k: job_data.get(k, profile.get(k,""))
                             for k in ["company","domain","product","name","user_type"]}
                    variations = generate_post_variations(
                        pdata, job_info["topic"],
                        job_data.get("post_type","Brand Announcement"),
                        job_data.get("tone","Executive Authority"),
                    )
                    images    = fetch_images_for_post(pdata, "Brand Announcement", "Professional", job_info["topic"], count=2)
                    img_urls  = [img["thumb"] for img in images]
                    appr_id   = str(uuid.uuid4())
                    save_approval({
                        "id":            appr_id,
                        "job_id":        job_info["id"],
                        "topic":         job_info["topic"],
                        "status":        "awaiting_approval",
                        "variations":    variations,
                        "image_urls":    img_urls,
                        "scheduled_for": job_info["datetime"],
                        "created_at":    datetime.datetime.utcnow().isoformat(),
                    })
                    update_job_status(job_info["id"], "awaiting_approval")
                    sent = send_approval_email(approval_email, appr_id, job_data, variations, img_urls)
                    logger.info(f"[Campaign] Resend {'✅' if sent else '❌'} for job {job_info['id']}")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"[Campaign] Email error for {job_info['id']}: {e}")
        background_tasks.add_task(send_campaign_emails)

    return {
        "status":        "campaign_created",
        "days":          data.days,
        "posts_per_day": data.posts_per_day,
        "total_posts":   len(created),
        "approval_email": approval_email,
        "jobs":          created,
    }

@app.get("/campaign-approve/{approval_id}", response_class=HTMLResponse)
async def campaign_approve_handler(
    approval_id: str,
    action:    Optional[str] = None,
    choice:    Optional[str] = None,
    variation: Optional[int] = 0,
    image:     Optional[int] = 0,
):
    approval = get_approval_by_id(approval_id)
    if not approval:
        return HTMLResponse(content=_inline_page("❌","Not Found","Approval not found or already used.","#ef4444"), status_code=404)

    if approval.get("status") in ("approved","rejected","posted"):
        return HTMLResponse(content=_inline_page("⚠️","Already Processed",
            f"This post was already {approval.get('status')}.", "#f59e0b"))

    if action == "reject":
        update_approval(approval_id, {"status": "rejected"})
        if approval.get("job_id"):
            update_job_status(approval["job_id"], "rejected")
        return HTMLResponse(content=_inline_page("🚫","Post Rejected","The post has been rejected.","#ef4444"))

    elif action == "skip":
        update_approval(approval_id, {"status": "skipped"})
        if approval.get("job_id"):
            update_job_status(approval["job_id"], "skipped")
        return HTMLResponse(content=_inline_page("⏭","Post Skipped","The post has been skipped.","#64748b"))

    elif choice:
        vi    = max(0, ord(choice.lower()) - ord('a'))
        vars_ = approval.get("variations", [])
        text  = vars_[vi].get("text","") if 0 <= vi < len(vars_) else ""
        if not text and vars_:
            text = vars_[0].get("text","")

        imgs               = approval.get("image_urls", [])
        selected_image_url = imgs[image] if imgs and 0 <= image < len(imgs) else ""

        update_approval(approval_id, {
            "status":             "approved",
            "selected_variation": vi,
            "selected_image":     image,
            "approved_text":      text,
            "approved_at":        datetime.datetime.utcnow().isoformat(),
        })
        job_id = approval.get("job_id")
        if job_id:
            update_job_status(job_id, "approved", {
                "approved_text": text,
                "image_url":     selected_image_url,
            })

        try:
            all_jobs  = get_all_jobs()
            job       = next((j for j in all_jobs if str(j.get("id")) == str(job_id)), {})
            li_token  = get_token()
            prof      = get_profile()
            urn       = job.get("urn") or prof.get("urn","")
            post_text = clean_for_linkedin(text or job.get("text",""))

            if not li_token:
                return HTMLResponse(content=_inline_page("⚠️","Not Connected",
                    "Approved! But LinkedIn token is missing. Please reconnect LinkedIn.","#f59e0b"))
            if not urn:
                return HTMLResponse(content=_inline_page("⚠️","No URN",
                    "Approved! But LinkedIn URN is missing. Please reconnect LinkedIn.","#f59e0b"))
            if not post_text:
                return HTMLResponse(content=_inline_page("⚠️","No Content",
                    "Approved! But post text is empty.","#f59e0b"))

            st, resp = _publish_to_linkedin(li_token, urn, post_text, selected_image_url or None)

            if st in (200, 201):
                update_approval(approval_id, {"status": "posted"})
                if job_id:
                    update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                logger.info(f"[Approve] ✅ Posted to LinkedIn — job {job_id}")
                return HTMLResponse(content=_inline_page("✅","Published to LinkedIn!",
                    "Your post is now live on LinkedIn. Check your profile!","#22c55e"))
            else:
                err_detail = str(resp)[:200]
                if job_id:
                    update_job_status(job_id, f"failed_http_{st}", {"linkedin_error": err_detail})
                return HTMLResponse(content=_inline_page("⚠️",f"LinkedIn Error {st}",
                    f"Approved but LinkedIn returned: {err_detail}","#f59e0b"))

        except Exception as ex:
            logger.exception(f"[Approve] {ex}")
            if approval.get("job_id"):
                update_job_status(approval["job_id"], "failed", {"linkedin_error": str(ex)})
            return HTMLResponse(content=_inline_page("❌","Error",
                f"Approved but posting failed: {str(ex)[:150]}","#ef4444"))

    return HTMLResponse(content=_inline_page("⚠️","No Action","No action specified.","#64748b"))

@app.get("/approvals")
async def list_approvals(status: Optional[str] = None):
    approvals = get_approvals(status)
    return {"approvals": approvals, "count": len(approvals)}

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
                text = vars_[data.variation_index].get("text","")
        update_approval(data.approval_id, {
            "status":             "approved",
            "selected_variation": data.variation_index,
            "approved_text":      text,
            "approved_at":        datetime.datetime.utcnow().isoformat(),
        })
        if job_id:
            update_job_status(job_id, "approved", {"approved_text": text or ""})
        post_result = "approved"
        try:
            all_jobs = get_all_jobs()
            job = next((j for j in all_jobs if str(j.get("id")) == str(job_id)), None)
            if job and text:
                token   = get_token()
                profile = get_profile()
                urn     = job.get("urn") or profile.get("urn","")
                if token and urn:
                    imgs    = approval.get("image_urls", [])
                    img_url = imgs[data.image_index] if imgs and data.image_index < len(imgs) else None
                    st, resp = _publish_to_linkedin(token, urn, clean_for_linkedin(text), img_url)
                    if st in (200, 201):
                        update_job_status(job_id, "posted", {"posted_at": datetime.datetime.utcnow().isoformat()})
                        update_approval(data.approval_id, {"status": "posted"})
                        post_result = "approved_and_posted"
                    else:
                        update_job_status(job_id, f"failed_http_{st}", {"linkedin_error": str(resp)})
                        post_result = f"approved_linkedin_error_{st}"
                else:
                    update_job_status(job_id, "failed_no_linkedin")
                    post_result = "approved_no_linkedin"
        except Exception as err:
            logger.error(f"[ApprovalAction] {err}")
            if job_id:
                update_job_status(job_id, "failed")
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

@app.get("/jobs")
async def list_jobs(status: Optional[str] = None):
    jobs = get_all_jobs(status)
    return {
        "stats": {
            "total":    len(jobs),
            "pending":  sum(1 for j in jobs if j.get("status") in ("pending","awaiting_approval")),
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
    return {"status": "deleted"}

@app.delete("/jobs")
async def clear_all_jobs():
    if supabase:
        try: supabase.table("scheduled_posts").delete().neq("id","").execute()
        except Exception as e: logger.warning(f"[Supabase] clear: {e}")
    _save_json(_JOBS_FILE, [])
    return {"status": "all_jobs_cleared"}

@app.get("/li_cache/{filename}")
async def serve_cache(filename: str):
    path = os.path.join(CONFIG["CACHE_DIR"], filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404)
    return FileResponse(path)

@app.get("/debug/profile")
async def debug_profile():
    return get_profile()

@app.get("/debug/linkedin")
async def debug_linkedin():
    token = get_token()
    profile = get_profile()
    return {
        "token_exists": bool(token),
        "urn":   profile.get("urn"),
        "name":  profile.get("name"),
        "email": profile.get("email"),
    }

@app.get("/debug/scheduler")
async def debug_scheduler():
    now = datetime.datetime.now()
    jobs = get_all_jobs()
    return {
        "current_time":    now.isoformat(),
        "total_jobs":      len(jobs),
        "pending_jobs":    sum(1 for j in jobs if j.get("status") in ("pending","awaiting_approval")),
        "approved_jobs":   sum(1 for j in jobs if j.get("status") == "approved"),
        "resend_configured": bool(CONFIG["RESEND_API_KEY"]),
        "resend_sdk":      HAS_RESEND,
        "sender_email":    CONFIG["SENDER_EMAIL"],
    }

@app.post("/debug/test-email")
async def test_email(to_email: str):
    if not CONFIG["RESEND_API_KEY"]:
        raise HTTPException(status_code=400,
            detail="RESEND_API_KEY not set. Get a free key at resend.com/api-keys and add it to Render environment variables.")
    html = f"""<!DOCTYPE html><html>
<body style="background:#03050a;color:#e8f0fc;font-family:system-ui;padding:20px">
<div style="max-width:600px;margin:auto;background:#0e1828;border:1px solid #1b2d45;
     border-radius:12px;padding:24px;text-align:center">
  <div style="font-size:48px">✅</div>
  <h2 style="color:#0ea5e9">Resend Email is Working!</h2>
  <p>LinkedIn Studio PRO can send emails via Resend successfully.</p>
  <p style="color:#8aa0bc;font-size:12px;margin-top:16px">
    Sent at {datetime.datetime.now().isoformat()}<br>
    Provider: Resend API (no SMTP ports needed)<br>
    From: {CONFIG['SENDER_EMAIL']}
  </p>
</div>
</body></html>"""
    sent = _resend_send("✅ Test Email — LinkedIn Studio PRO", html, to_email)
    if sent:
        return {"status": "sent", "to": to_email, "provider": "Resend"}
    raise HTTPException(status_code=500,
        detail="Resend send failed. Check logs. Make sure RESEND_API_KEY is valid and SENDER_EMAIL is verified.")

@app.get("/", response_class=HTMLResponse)
async def home():
    for f in ["index.html", "linkedin-studio-pro (4).html", "frontend.html"]:
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                return HTMLResponse(content=fh.read())
    return HTMLResponse(content="""<!DOCTYPE html><html>
<body style="background:#03050a;color:#e8f0fc;font-family:system-ui;padding:40px;text-align:center">
<h1 style="color:#0ea5e9">LinkedIn Studio PRO v4.3.0</h1>
<p>Place <code>index.html</code> next to <code>main.py</code>.</p>
<p><a href="/docs" style="color:#0ea5e9">→ API Docs</a></p>
</body></html>""")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["PORT"], reload=False, log_level="info")
