"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      LinkedIn Studio PRO v4.0 — FastAPI Backend (Render-Ready)             ║
║   FULLY FIXED: Approval→Post flow, image persistence, URN resolution       ║
╚══════════════════════════════════════════════════════════════════════════════╝

BUGS FIXED IN THIS VERSION:
 1. /schedule  — broken job dict (NameError scheduled_time + duplicate keys)
 2. /generate  — returns Supabase public URL (p[2]) not local disk path (p[0])
 3. _post_approved_jobs — uses job['urn'] OR profile['urn'] correctly
 4. _post_approved_jobs — properly downloads image from image_url before posting
 5. approval_link_handler — sets BOTH approved_text AND image_url on the job
 6. /campaign + /campaign/auto — safe Supabase insert with save_job() fallback
 7. _process_approval_notifications — stores image_urls in approval so scheduler can use them
 8. Approved job: scheduler reads selected_image index → downloads correct image_url
"""

import sys, os, json, time, threading, random, uuid
import urllib.parse, base64, io, smtplib
import datetime, textwrap, re, math
from pathlib import Path
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query, Form, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("li_studio")

import requests as http_requests

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-generativeai not installed — AI features disabled")

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("Pillow not installed — image generation disabled")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import tempfile

# ── Gemini keys ────────────────────────────────────────────────────────────────
GEMINI_API_KEYS = [
    os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 11)
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

_current_key_index = 0
_key_lock = threading.Lock()
_key_cooldowns: Dict[int, float] = {}
_KEY_COOLDOWN_SECS = 65

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "LINKEDIN_CLIENT_ID":     os.environ.get("LINKEDIN_CLIENT_ID", ""),
    "LINKEDIN_CLIENT_SECRET": os.environ.get("LINKEDIN_CLIENT_SECRET", ""),
    "LINKEDIN_REDIRECT_URI":  os.environ.get("LINKEDIN_REDIRECT_URI"),
    "LINKEDIN_SCOPES":        os.environ.get("LINKEDIN_SCOPES", "openid profile w_member_social email"),
    "GEMINI_MODEL":           os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
    "PIXABAY_API_KEY":        os.environ.get("PIXABAY_API_KEY", ""),
    "PEXELS_API_KEY":         os.environ.get("PEXELS_API_KEY", ""),
    "CACHE_DIR":              os.environ.get("CACHE_DIR", "li_cache"),
    "SCHEDULED_IMAGES_DIR":   os.environ.get("SCHEDULED_IMAGES_DIR", "scheduled_images"),
    "PORT":                   int(os.environ.get("PORT", 8000)),
    "SMTP_HOST":              os.environ.get("SMTP_HOST", "smtp.gmail.com"),
    "SMTP_PORT":              int(os.environ.get("SMTP_PORT", 587)),
    "SMTP_USER":              os.environ.get("SMTP_USER", ""),
    "SMTP_PASS":              os.environ.get("SMTP_PASS", ""),
    "APP_BASE_URL":           os.environ.get("APP_BASE_URL", "http://localhost:8000"),
    "APPROVAL_LEAD_HOURS":    int(os.environ.get("APPROVAL_LEAD_HOURS", 24)),
    "OPENROUTER_API_KEY":     os.environ.get("OPENROUTER_API_KEY", ""),
    "OPENROUTER_MODEL":       os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
}

os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
os.makedirs(CONFIG["SCHEDULED_IMAGES_DIR"], exist_ok=True)

# ── Supabase ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("[Supabase] Connected successfully")
    except Exception as _e:
        logger.warning(f"[Supabase] Connection failed: {_e}")

# ── Design constants ───────────────────────────────────────────────────────────
POST_TYPES = {
    "individual": ["Thought Leadership","Text Post","Motivational","Story / Experience","Hot Take / Opinion","Career Milestone"],
    "company":    ["Brand Announcement","Hiring / Recruiting","Festival / Occasion","Product / Feature Launch","Company Milestone","Event / Workshop","Industry News","Culture & Values"],
}
TONES = ["Executive Authority","Warm & Authentic","Bold Marketing","Data-Driven Analyst","Storyteller","Technical Expert","Inspiring Coach"]
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
    "Navy Sapphire":    ("#0a192f","#0ea5e9"),
    "Obsidian Emerald": ("#020617","#10b981"),
    "Deep Violet":      ("#1a0533","#a855f7"),
    "Midnight Amber":   ("#1c1408","#f59e0b"),
    "Charcoal Crimson": ("#1a0000","#ef4444"),
    "Dark Teal":        ("#042f2e","#14b8a6"),
    "Slate Coral":      ("#1e1b2e","#f97316"),
    "Graphite Sky":     ("#111827","#38bdf8"),
}
REWRITE_STYLES = {
    "professional": "Rewrite this LinkedIn post in a polished, executive professional tone.",
    "viral":        "Rewrite to maximize virality. Use a hook, create curiosity, add bold claim, end with CTA.",
    "ceo":          "Rewrite as a CEO personal brand post. Strategic thinking, forward vision, leadership lessons.",
    "technical":    "Rewrite with deep technical detail. Include data, frameworks, methodologies.",
    "motivational": "Rewrite as deeply inspiring motivational content with storytelling.",
    "storytelling": "Rewrite as a compelling narrative story. Hook, tension, insight, lesson.",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

_TOKEN_FILE     = "li_tokens.json"
_PROFILE_FILE   = "li_profile.json"
_JOBS_FILE      = "scheduler_jobs.json"
_APPROVALS_FILE = "li_approvals.json"


def upload_image_to_supabase(local_path: str) -> Optional[str]:
    if not supabase:
        return None
    try:
        filename = f"{uuid.uuid4()}.png"
        with open(local_path, "rb") as f:
            supabase.storage.from_("post-images").upload(
                path=filename, file=f.read(),
                file_options={"content-type": "image/png"}
            )
        return supabase.storage.from_("post-images").get_public_url(filename)
    except Exception as e:
        logger.error(f"[Storage] Upload failed: {e}")
        return None


def _save_json(path: str, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"[JSON] save error {path}: {e}")


def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ── Token ──────────────────────────────────────────────────────────────────────
def save_token(token_data: dict):
    _save_json(_TOKEN_FILE, token_data)
    if supabase:
        try:
            row = {
                "id": "main",
                "access_token": token_data.get("access_token"),
                "expires_in":   token_data.get("expires_in"),
                "token_type":   token_data.get("token_type", "Bearer"),
                "scope":        token_data.get("scope", ""),
                "created_at":   datetime.datetime.utcnow().isoformat(),
            }
            supabase.table("li_tokens").upsert(row).execute()
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
            row = {"id": "main", **data, "updated_at": datetime.datetime.utcnow().isoformat()}
            supabase.table("li_profiles").upsert(row).execute()
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


def _supabase_insert_job(job: dict):
    """Insert job to Supabase with JSON fallback."""
    if supabase:
        try:
            supabase.table("scheduled_posts").insert(job).execute()
            # Also write to JSON as local backup
            jobs = _load_json(_JOBS_FILE) or []
            jobs.append(job)
            _save_json(_JOBS_FILE, jobs)
            return
        except Exception as e:
            logger.warning(f"[Supabase] insert failed, using fallback: {e}")
    save_job(job)


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
    approvals = _load_json(_APPROVALS_FILE) or []
    for a in approvals:
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
        },
        timeout=15,
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
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to fetch user info: {r.text}")
    info = r.json()
    return info.get("sub"), info.get("name", "User"), info.get("email", "")


def linkedin_post_text(access_token: str, urn: str, text: str) -> tuple:
    payload = {
        "author": f"urn:li:person:{urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary":    {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    r = http_requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20,
    )
    return r.status_code, r.json()


def download_temp_image(url: str) -> Optional[str]:
    """Download image from URL to a temp file; return path or None."""
    if not url:
        return None
    try:
        r = http_requests.get(url, timeout=30)
        if r.status_code != 200:
            logger.warning(f"[Image Download] HTTP {r.status_code} for {url}")
            return None
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(r.content)
        tmp.close()
        logger.info(f"[Image Download] Saved to {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.error(f"[Image Download] {e}")
        return None


def linkedin_post_with_image(access_token: str, urn: str, text: str, image_path: str) -> tuple:
    # Step 1: register upload
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
        logger.warning(f"[LinkedIn] Image register failed: {reg_r.status_code} {reg_r.text}")
        return linkedin_post_text(access_token, urn, text)

    reg_data   = reg_r.json()
    upload_url = reg_data["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn  = reg_data["value"]["asset"]

    # Step 2: upload binary
    with open(image_path, "rb") as img_f:
        img_bytes = img_f.read()

    upload_r = http_requests.put(
        upload_url,
        data=img_bytes,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    logger.info(f"[LinkedIn] Image upload status: {upload_r.status_code}")

    # Step 3: create post
    payload = {
        "author": f"urn:li:person:{urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary":    {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [{"status": "READY", "media": asset_urn}],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    r = http_requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20,
    )
    return r.status_code, r.json()


# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI AI
# ═══════════════════════════════════════════════════════════════════════════════
GEMINI_MODELS_FALLBACK = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]
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
    for or_model in OPENROUTER_MODELS_FALLBACK:
        try:
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  CONFIG.get("APP_BASE_URL", "http://localhost:8000"),
                    "X-Title":       "LinkedIn Studio PRO",
                },
                json={"model": or_model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"[OpenRouter] {or_model}: {e}")
    return ""


def gemini_generate(prompt: str) -> str:
    total_keys = len(GEMINI_API_KEYS)
    if total_keys == 0:
        return openrouter_generate(prompt) or "[AI error: No API keys configured]"

    primary = CONFIG.get("GEMINI_MODEL", "gemini-2.0-flash")
    models_to_try = [primary] + [m for m in GEMINI_MODELS_FALLBACK if m != primary]

    for model_name in models_to_try:
        exhausted = 0
        for attempt in range(total_keys):
            try:
                model, key, key_idx = get_next_gemini_model(model_name, key_idx=attempt)
                resp = model.generate_content(prompt)
                return resp.text.strip()
            except Exception as e:
                err = str(e).lower()
                logger.warning(f"[Gemini] {model_name} key {attempt+1} failed: {str(e)[:120]}")
                if any(x in err for x in ("429","quota","rate limit","resource_exhausted")):
                    _key_cooldowns[attempt] = time.time() + _KEY_COOLDOWN_SECS
                    exhausted += 1
                    continue
                if "404" in err or "not found" in err:
                    exhausted = total_keys
                    break
                break
        if exhausted >= total_keys:
            continue

    result = openrouter_generate(prompt)
    if result:
        return result

    now = time.time()
    if _key_cooldowns:
        wait = max(5, min(_key_cooldowns.values()) - now + 2)
        logger.warning(f"[Gemini] All exhausted. Waiting {wait:.0f}s...")
        time.sleep(wait)
        _key_cooldowns.clear()
        try:
            model, _, _ = get_next_gemini_model("gemini-2.0-flash", key_idx=0)
            return model.generate_content(prompt).text.strip()
        except Exception as e:
            logger.error(f"[Gemini] Final retry failed: {e}")

    return "[AI temporarily unavailable. Please try again in 1 minute.]"


# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE SEARCH
# ═══════════════════════════════════════════════════════════════════════════════
def _search_stock(query: str, count: int) -> list:
    results = []
    if CONFIG["PIXABAY_API_KEY"] and len(results) < count:
        try:
            r = http_requests.get(
                "https://pixabay.com/api/",
                params={"key": CONFIG["PIXABAY_API_KEY"], "q": query, "image_type": "photo",
                        "per_page": min(count+3, 20), "safesearch": "true", "order": "popular",
                        "min_width": 800, "orientation": "horizontal"},
                timeout=10,
            )
            for hit in r.json().get("hits", [])[:count]:
                results.append({"url": hit["largeImageURL"], "thumb": hit["webformatURL"],
                                 "source": "Pixabay", "query": query, "id": str(hit.get("id","")),
                                 "photographer": hit.get("user","")})
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
                results.append({"url": p["src"]["large2x"], "thumb": p["src"]["medium"],
                                 "source": "Pexels", "query": query, "id": str(p.get("id","")),
                                 "photographer": p.get("photographer","")})
        except Exception as e:
            logger.debug(f"[Pexels] {e}")

    return results[:count]


def search_images(query: str, count: int = 9) -> list:
    return _search_stock(query, count)


def build_domain_image_queries(profile: dict, post_type: str, mood: str, topic: str) -> list:
    domain  = profile.get("domain", "").strip()
    product = profile.get("product", "").strip()
    company = profile.get("company", "")
    if HAS_GEMINI and domain:
        prompt = f"""Visual content strategist.
Company: {company}, Domain: {domain}, Product: {product}, Post: {post_type}, Topic: {topic}
Generate exactly 3 stock photo search queries (5-8 words each).
Return ONLY a JSON array of 3 strings. No markdown."""
        raw = gemini_generate(prompt)
        try:
            raw = re.sub(r"```json|```", "", raw).strip()
            queries = json.loads(raw)
            if isinstance(queries, list) and len(queries) >= 2:
                return queries[:3]
        except Exception:
            pass
    d  = " ".join(domain.lower().split()[:2]) or "business"
    pr = " ".join(product.lower().split()[:2]) or "technology"
    return [f"{pr} product professional", f"person using {pr} {d}", f"{d} industry modern"]


def fetch_images_for_post(profile: dict, post_type: str, mood: str, topic: str, count: int = 3) -> list:
    queries = build_domain_image_queries(profile, post_type, mood, topic)
    results = []
    per_q   = max(1, math.ceil(count / len(queries)))
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
    except Exception as e:
        logger.debug(f"[download_image] {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE GENERATION — Poster layouts
# ═══════════════════════════════════════════════════════════════════════════════
def _load_font(size: int, bold: bool = True):
    if not HAS_PIL:
        return None
    candidates = (["arialbd.ttf","Arial Bold.ttf","calibrib.ttf"] if bold
                  else ["arial.ttf","Arial.ttf","calibri.ttf"])
    candidates += [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(c1[i]*(1-t) + c2[i]*t) for i in range(3))


def build_poster_layout_1(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))
    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.75)
    bg = ImageEnhance.Contrast(bg).enhance(1.1)
    canvas.paste(bg.convert("RGBA"), (0, 0))
    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x in range(W):
        t = 1.0 - min(1.0, x/650)
        alpha = int(220*(t**0.7))
        col = _lerp_color(drk, (drk[0], drk[1]+5, drk[2]+8), 1-t)
        for y in range(H):
            overlay.putpixel((x, y), (col[0], col[1], col[2], alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    accent_bar = Image.new("RGBA", (W, H), (0,0,0,0))
    ImageDraw.Draw(accent_bar).rectangle([(0,0),(6,H)], fill=(*acc,255))
    canvas = Image.alpha_composite(canvas, accent_bar)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(28, bold=True)
    f_title = _load_font(82 if len(headline)<25 else 62, bold=True)
    f_tag   = _load_font(20, bold=False)
    f_sub   = _load_font(30, bold=False)
    draw.text((50,50), org_name.upper(), font=f_brand, fill=(*acc,255))
    draw.line([(50,88),(300,88)], fill=(*acc,180), width=3)
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.rounded_rectangle((50,96,50+len(pt_clean)*12+24,130), radius=6, fill=(*acc,30), outline=(*acc,100))
    draw.text((62,100), pt_clean.upper(), font=f_tag, fill=(*acc,220))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0,0)," ".join(curr),font=f_title)[2] > 700:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    y = 200
    for line in lines[:3]:
        draw.text((52,y+3), line, font=f_title, fill=(0,0,0,130))
        draw.text((50,y), line, font=f_title, fill=(255,255,255,255))
        y += int(f_title.size*1.15)
    if domain:
        tag = f"  {domain}  "
        tw = draw.textbbox((0,0),tag,font=f_sub)[2]
        draw.rounded_rectangle((50,H-80,50+tw+24,H-44), radius=10, fill=(*acc,25), outline=(*acc,80))
        draw.text((62,H-76), tag, font=f_sub, fill=(*acc,220))
    return canvas.convert("RGB")


def build_poster_layout_2(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))
    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.70)
    canvas.paste(bg.convert("RGBA"), (0, 0))
    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(H):
        t = max(0, (y - H*0.3)/(H*0.7))
        alpha = int(230*min(1.0, t**0.65))
        col = _lerp_color((10,12,20), drk, t)
        draw_ov.line([(0,y),(W,y)], fill=(*col,alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(26, bold=True)
    f_title = _load_font(90 if len(headline)<20 else 68, bold=True)
    f_tag   = _load_font(20, bold=False)
    org_w = draw.textbbox((0,0),org_name.upper(),font=f_brand)[2]
    draw.text(((W-org_w)//2,36), org_name.upper(), font=f_brand, fill=(*acc,240))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0,0)," ".join(curr),font=f_title)[2] > W-120:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    total_h = len(lines)*int(f_title.size*1.12)
    y = H - total_h - 100
    for line in lines[:3]:
        lw = draw.textbbox((0,0),line,font=f_title)[2]
        x = (W-lw)//2
        draw.text((x+3,y+3), line, font=f_title, fill=(0,0,0,100))
        draw.text((x,y), line, font=f_title, fill=(255,255,255,255))
        y += int(f_title.size*1.12)
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.line([(W//2-100,H-78),(W//2+100,H-78)], fill=(*acc,200), width=3)
    tw = draw.textbbox((0,0),pt_clean.upper(),font=f_tag)[2]
    draw.text(((W-tw)//2,H-62), pt_clean.upper(), font=f_tag, fill=(*acc,200))
    return canvas.convert("RGB")


LAYOUT_BUILDERS = [build_poster_layout_1, build_poster_layout_2]


def build_posters_for_images(images_data: list, headline: str, profile: dict,
                              post_type: str, gradient_name: str, topic: str) -> list:
    """Returns list of (local_path, source_name, public_url)"""
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
            bg_img    = Image.open(raw_path).convert("RGB")
            layout_fn = LAYOUT_BUILDERS[i % len(LAYOUT_BUILDERS)]
            poster    = layout_fn(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex)
            out_path  = os.path.join(CONFIG["CACHE_DIR"], f"poster_{i}_{int(time.time())}.png")
            poster.save(out_path, "PNG")
            public_url = upload_image_to_supabase(out_path)
            posters.append((out_path, item.get("source", "Stock Photo"), public_url))
        except Exception as e:
            logger.warning(f"[Poster] layout {i} error: {e}")
    return posters


def edit_image(image_path: str, operations: dict) -> str:
    if not HAS_PIL:
        return image_path
    try:
        img = Image.open(image_path).convert("RGB")
        if "crop" in operations:
            c = operations["crop"]
            img = img.crop((c["x"], c["y"], c["x"]+c["w"], c["y"]+c["h"]))
        if "resize" in operations:
            r = operations["resize"]
            img = img.resize((r["width"], r["height"]), Image.Resampling.LANCZOS)
        if "brightness" in operations:
            img = ImageEnhance.Brightness(img).enhance(float(operations["brightness"]))
        if "contrast" in operations:
            img = ImageEnhance.Contrast(img).enhance(float(operations["contrast"]))
        if "blur" in operations:
            img = img.filter(ImageFilter.GaussianBlur(radius=float(operations["blur"])))
        if "watermark" in operations:
            draw = ImageDraw.Draw(img)
            font = _load_font(int(img.size[0]*0.04))
            w, h = img.size
            draw.text((w-20,h-20), str(operations["watermark"]), font=font, fill=(255,255,255,100), anchor="rb")
        if "text_overlay" in operations:
            to = operations["text_overlay"]
            draw = ImageDraw.Draw(img)
            font = _load_font(int(to.get("size",48)))
            draw.text((to.get("x",50),to.get("y",50)), to.get("text",""), font=font,
                      fill=tuple(_hex_to_rgb(to.get("color","#ffffff")))+(255,))
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
        bold_map[c] = chr(0x1D400+i)
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        bold_map[c] = chr(0x1D41A+i)
    for i, c in enumerate("0123456789"):
        bold_map[c] = chr(0x1D7CE+i)
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
        stripped = line.strip()
        if stripped and all(w.startswith('#') for w in stripped.split()):
            tags.append(stripped)
        else:
            body.append(line)
    body_text = re.sub(r'\n{3,}', '\n\n', '\n'.join(body)).strip()
    return (body_text + '\n\n' + ' '.join(tags) if tags else body_text).strip()


def generate_post_text(profile: dict, post_type: str, tone: str, mood: str,
                        topic: str, extra_info: str = "") -> str:
    org_name   = profile.get("company", "")
    domain     = profile.get("domain", "")
    product    = profile.get("product", "")
    name       = profile.get("name", "Professional")
    is_company = profile.get("user_type", "individual") == "company"
    mood_desc  = MOODS.get(mood, "professional")

    prompt = f"""You are a senior LinkedIn content strategist.
Organization: {org_name or name}
Industry/Domain: {domain}
Product/Service: {product}
Account: {"Company Page (We/Our)" if is_company else "Individual (I/My)"}
Post Type: {post_type} | Tone: {tone} | Mood: {mood_desc}
Topic: {topic}
Extra Info: {extra_info}

Rules:
- Hook on line 1 referencing topic + domain
- 2-3 short paragraphs with domain-specific insights
- 3 bullets starting with ✦
- 1 CTA question for {domain} professionals
- 5 hashtags on last line
- Max 200 words. Output ONLY the post text."""
    return gemini_generate(prompt)


def generate_ai_topics(company, domain, product, name: str, count: int = 3) -> list:
    prompt = f"""LinkedIn content strategist for {domain or "B2B tech"}.
Company: {company}, Founder: {name}, Domain: {domain}, Product: {product}
Generate {count} HIGH-VALUE LinkedIn post ideas specific to "{domain}" selling "{product}".
Return ONLY a JSON array of {count} strings. No markdown. No numbering."""
    raw = gemini_generate(prompt)
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        topics = json.loads(raw)
        if isinstance(topics, list):
            return [str(t) for t in topics[:count]]
    except Exception:
        pass
    lines = [l.strip().strip('"').strip("'").strip("-").strip() for l in raw.split("\n") if l.strip()]
    return [l for l in lines if 3 < len(l) < 120][:count]


def rewrite_post(text: str, style: str) -> str:
    instruction = REWRITE_STYLES.get(style, REWRITE_STYLES["professional"])
    prompt = f"""{instruction}

Original post:
{text}

Requirements: Keep hashtags. Max 250 words. Return ONLY the rewritten post."""
    return clean_for_linkedin(gemini_generate(prompt))


def generate_post_variations(profile: dict, topic: str, post_type: str,
                               tone: str, count: int = 3) -> list:
    styles = ["Thought Leadership", "Story / Experience", "Data-Driven Analyst"][:count]
    variations = []
    for style in styles:
        text = generate_post_text(profile, post_type, style, "Professional", topic)
        variations.append({"style": style, "text": clean_for_linkedin(text)})
    return variations


# ═══════════════════════════════════════════════════════════════════════════════
#  EMAIL APPROVAL
# ═══════════════════════════════════════════════════════════════════════════════
def send_approval_email(to_email: str, approval_id: str, job_data: dict,
                         variations: list, image_urls: list) -> bool:
    if not CONFIG["SMTP_USER"] or not CONFIG["SMTP_PASS"]:
        logger.info(f"[Email] SMTP not configured — skipping approval email {approval_id}")
        return False

    base_url = CONFIG["APP_BASE_URL"]
    topic    = job_data.get("topic", job_data.get("text","LinkedIn Post")[:50])

    var_html = ""
    for i, v in enumerate(variations):
        label = chr(65+i)
        var_html += f"""
        <div style="background:#0a1628;border:1px solid #1e3a5f;border-radius:8px;padding:16px;margin:12px 0">
          <div style="color:#0ea5e9;font-weight:bold;font-size:13px;margin-bottom:8px">
            Variation {label} — {v.get('style','')}
          </div>
          <div style="color:#c8d6e5;font-size:12px;white-space:pre-wrap;line-height:1.7">
            {v.get('text','')[:600]}
          </div>
          <a href="{base_url}/approve/{approval_id}?choice={label.lower()}&variation={i}&image=0"
             style="display:inline-block;margin-top:10px;padding:8px 20px;background:#0ea5e9;
                    color:#000;border-radius:6px;font-size:12px;font-weight:bold;text-decoration:none">
            ✓ Choose Variation {label}
          </a>
        </div>"""

    img_html = "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
    for i, img_url in enumerate(image_urls[:3]):
        label = chr(65+i)
        img_html += f"""
        <div style="border:2px solid #1e3a5f;border-radius:8px;overflow:hidden;width:200px">
          <img src="{img_url}" style="width:200px;height:130px;object-fit:cover" alt="Image {label}">
          <div style="padding:8px;text-align:center;color:#0ea5e9;font-size:11px;font-weight:bold">
            Image {label} (index {i})
          </div>
        </div>"""
    img_html += "</div>"

    # NOTE: clicking a variation link approves variation + uses image 0 by default.
    # User can append &image=N to pick a specific image.
    html_body = f"""
    <html>
    <body style="background:#040608;color:#f0f6fc;font-family:sans-serif;padding:32px;max-width:700px;margin:0 auto">
      <div style="background:#0a1628;border:1px solid #1e3a5f;border-radius:16px;padding:32px">
        <h2 style="color:#0ea5e9;margin:0 0 8px">🚀 LinkedIn Post Awaiting Approval</h2>
        <p style="color:#64748b;margin:0 0 24px;font-size:13px">
          Topic: <strong style="color:#f0f6fc">{topic}</strong> ·
          Scheduled: <strong style="color:#f0f6fc">{job_data.get('datetime','—')}</strong>
        </p>
        <h3 style="color:#f0f6fc;margin:0 0 12px">📝 Select a Post Variation (click to approve)</h3>
        {var_html}
        <h3 style="color:#f0f6fc;margin:24px 0 12px">📸 Images available for this post</h3>
        {img_html}
        <div style="margin-top:24px;display:flex;gap:12px">
          <a href="{base_url}/approve/{approval_id}?action=reject"
             style="padding:10px 24px;background:rgba(239,68,68,0.2);color:#ef4444;
                    border-radius:6px;font-size:12px;text-decoration:none;font-weight:bold">
            ✗ Reject Post
          </a>
          <a href="{base_url}/approve/{approval_id}?action=skip"
             style="padding:10px 24px;background:rgba(100,116,139,0.2);color:#64748b;
                    border-radius:6px;font-size:12px;text-decoration:none;font-weight:bold">
            ⏭ Skip
          </a>
        </div>
      </div>
    </body>
    </html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🚀 LinkedIn Post Awaiting Approval — {topic[:40]}"
        msg["From"]    = CONFIG["SMTP_USER"]
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(CONFIG["SMTP_HOST"], CONFIG["SMTP_PORT"]) as server:
            server.starttls()
            server.login(CONFIG["SMTP_USER"], CONFIG["SMTP_PASS"])
            server.sendmail(CONFIG["SMTP_USER"], to_email, msg.as_string())
        logger.info(f"[Email] Approval email sent → {to_email}")
        return True
    except Exception as e:
        logger.warning(f"[Email] Failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════

def _process_approval_notifications():
    """Send approval emails for pending jobs approaching their scheduled time."""
    now     = datetime.datetime.now()
    profile = get_profile()
    lead_h  = CONFIG["APPROVAL_LEAD_HOURS"]

    for job in get_all_jobs():
        if job.get("status") != "pending":
            continue
        approval_email = job.get("approval_email") or profile.get("email", "")
        if not approval_email:
            continue
        job_id = str(job.get("id", ""))
        # Skip if approval already exists
        if any(str(a.get("job_id")) == job_id for a in get_approvals()):
            continue
        try:
            sched_dt = datetime.datetime.strptime(job.get("datetime","9999-12-31 23:59"), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if (sched_dt - now).total_seconds() / 3600 > lead_h:
            continue

        logger.info(f"[Scheduler] Creating approval for job {job_id}")
        try:
            topic      = job.get("topic", job.get("text","")[:50] or "LinkedIn Post")
            pdata      = {k: job.get(k,"") for k in ["company","domain","product","name","user_type"]}
            if not pdata["company"]:
                pdata.update(profile)
            variations = generate_post_variations(
                pdata, topic,
                job.get("post_type","Brand Announcement"),
                job.get("tone","Executive Authority")
            )
            images     = fetch_images_for_post(
                pdata, job.get("post_type","Brand Announcement"),
                job.get("mood","Professional"), topic, count=3
            )
            # Store FULL image URLs (not just thumbs) so scheduler can download them
            image_urls      = [img["url"]   for img in images]
            image_thumb_urls = [img["thumb"] for img in images]

            approval_id = str(uuid.uuid4())
            approval = {
                "id":             approval_id,
                "job_id":         job_id,
                "topic":          topic,
                "status":         "awaiting_approval",
                "variations":     variations,
                "image_urls":     image_urls,       # full-res URLs for posting
                "image_thumbs":   image_thumb_urls,  # thumbnails for email display
                "scheduled_for":  job.get("datetime",""),
                "created_at":     datetime.datetime.utcnow().isoformat(),
            }
            save_approval(approval)
            update_job_status(job_id, "awaiting_approval")
            send_approval_email(approval_email, approval_id, job, variations, image_thumb_urls)
            logger.info(f"[Scheduler] Approval {approval_id} created for job {job_id}")
        except Exception as e:
            logger.error(f"[Scheduler] Approval creation error for {job_id}: {e}")


def _post_approved_jobs():
    """
    Post all jobs whose status = 'approved' and scheduled time has passed.

    FIX SUMMARY:
    - Gets URN from job first, falls back to profile
    - Resolves post text: approved_text > job.text > AI-generate
    - Downloads image from approval.image_urls[selected_image] if available,
      else from job.image_url
    - Cleans up temp file after posting
    """
    now_str  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    token    = get_token()
    profile  = get_profile()

    due = [
        j for j in get_all_jobs()
        if j.get("status") == "approved"
        and j.get("datetime")
        and j.get("datetime") <= now_str
    ]
    if due:
        logger.info(f"[Scheduler] Found {len(due)} approved jobs due")

    for job in due:
        job_id = str(job.get("id", ""))
        # ── Resolve URN ──────────────────────────────────────────────────────
        urn = job.get("urn") or profile.get("urn", "")
        if not token or not urn:
            logger.error(f"[Scheduler] Job {job_id}: missing token or URN (urn={urn!r})")
            update_job_status(job_id, "failed (no token/urn)")
            continue

        try:
            # ── Resolve text ─────────────────────────────────────────────────
            text = (job.get("approved_text") or "").strip()
            if not text:
                text = (job.get("text") or "").strip()
            if not text and job.get("mode") == "ai_auto":
                pdata = {k: job.get(k,"") for k in ["company","domain","product","name","user_type"]}
                text = clean_for_linkedin(generate_post_text(
                    pdata,
                    job.get("post_type","Brand Announcement"),
                    job.get("tone","Executive Authority"),
                    job.get("mood","Professional"),
                    job.get("topic","industry trends")
                ))
            if not text:
                update_job_status(job_id, "failed (empty text)")
                continue

            # ── Resolve image ─────────────────────────────────────────────────
            # Priority order:
            # 1. Image from approval record (full-res URL at selected_image index)
            # 2. image_url stored on the job itself
            # 3. No image → text-only post
            image_path = None
            temp_to_delete = None

            # Try approval image first
            approval_record = None
            try:
                approvals = get_approvals()
                for a in approvals:
                    if str(a.get("job_id")) == job_id and a.get("status") == "approved":
                        approval_record = a
                        break
            except Exception:
                pass

            if approval_record:
                img_idx = int(approval_record.get("selected_image", 0) or 0)
                img_urls = approval_record.get("image_urls", [])
                if img_urls and img_idx < len(img_urls):
                    chosen_url = img_urls[img_idx]
                    logger.info(f"[Scheduler] Downloading approval image[{img_idx}]: {chosen_url}")
                    image_path = download_temp_image(chosen_url)
                    temp_to_delete = image_path

            # Fall back to job's own image_url
            if not image_path:
                job_image_url = job.get("image_url") or ""
                if job_image_url:
                    logger.info(f"[Scheduler] Downloading job image_url: {job_image_url}")
                    image_path = download_temp_image(job_image_url)
                    temp_to_delete = image_path

            # ── Post to LinkedIn ──────────────────────────────────────────────
            if image_path and os.path.exists(image_path):
                logger.info(f"[Scheduler] Posting WITH image: {image_path}")
                st, resp = linkedin_post_with_image(token, urn, text, image_path)
            else:
                logger.info(f"[Scheduler] Posting text-only")
                st, resp = linkedin_post_text(token, urn, text)

            new_status = "posted" if st in (200, 201) else f"failed (HTTP {st})"
            logger.info(f"[Scheduler] Job {job_id} → {new_status} | LinkedIn: {resp}")

            # Cleanup temp file
            if temp_to_delete:
                try:
                    os.unlink(temp_to_delete)
                except Exception:
                    pass

        except Exception as ex:
            new_status = f"failed ({str(ex)[:80]})"
            logger.error(f"[Scheduler] Job {job_id} error: {ex}")

        update_job_status(job_id, new_status, {"posted_at": datetime.datetime.utcnow().isoformat()})


def run_scheduler_daemon():
    logger.info("[Scheduler] Started — checking every 30s")
    cycle = 0
    while True:
        try:
            cycle += 1
            _post_approved_jobs()
            if cycle % 5 == 0:
                _process_approval_notifications()
        except Exception as loop_err:
            logger.error(f"[Scheduler] Loop error: {loop_err}")
        time.sleep(30)


# ═══════════════════════════════════════════════════════════════════════════════
#  FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=run_scheduler_daemon, daemon=True)
    t.start()
    logger.info("[App] Scheduler thread started")
    yield
    logger.info("[App] Shutting down")


app = FastAPI(title="LinkedIn Studio PRO", version="4.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ── Pydantic models ────────────────────────────────────────────────────────────
class ProfileIn(BaseModel):
    name: str
    company: str
    domain: str
    product: str
    user_type: str = "company"
    urn: Optional[str] = None
    email: Optional[str] = None

class GeneratePostIn(BaseModel):
    topic: str
    headline: Optional[str] = None
    post_type: str = "Brand Announcement"
    tone: str = "Executive Authority"
    mood: str = "Professional"
    gradient: str = "Navy Sapphire"
    image_count: int = 2

class RewriteIn(BaseModel):
    text: str
    style: str = "professional"

class CampaignIn(BaseModel):
    days: int
    topic: str
    start_datetime: str

class AutoCampaignIn(BaseModel):
    days: int
    posts_per_day: int = 1
    time_slots: Optional[List[str]] = None
    start_date: str
    industry: Optional[str] = None
    domain: Optional[str] = None
    product: Optional[str] = None
    tone: str = "Executive Authority"
    mood: str = "Professional"
    gradient: str = "Navy Sapphire"
    approval_email: Optional[str] = None

class PostNowIn(BaseModel):
    text: str
    image_path: Optional[str] = None

class ImageEditIn(BaseModel):
    image_path: str
    operations: Dict[str, Any]

class ImageSearchIn(BaseModel):
    query: str
    count: int = 9

class ApprovalActionIn(BaseModel):
    approval_id: str
    action: str
    variation_index: int = 0
    image_index: int = 0
    custom_text: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────
def _require_auth() -> str:
    token = get_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect LinkedIn first.")
    return token

def _require_profile() -> dict:
    p = get_profile()
    if not p.get("company"):
        raise HTTPException(status_code=400, detail="Set your brand profile first via POST /profile")
    return p

def _auth_result_page(success: bool, title: str, message: str) -> str:
    icon  = "✅" if success else "❌"
    color = "#10b981" if success else "#ef4444"
    return f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"><title>{title}</title>
<style>body{{background:#03050a;color:#e8f0fc;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:40px;background:#0e1828;border:1px solid #1b2d45;border-radius:16px}}</style>
</head><body>
<div class="card">
<div style="font-size:56px">{icon}</div>
<h2 style="color:{color};margin:16px 0 8px">{title}</h2>
<p style="color:#8aa0bc">{message}</p>
</div></body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok", "version": "4.0.0", "scheduler": "running",
        "gemini": HAS_GEMINI and len(GEMINI_API_KEYS) > 0,
        "linkedin_token": bool(get_token()),
        "supabase": bool(supabase),
        "pixabay": bool(CONFIG["PIXABAY_API_KEY"]),
        "pexels":  bool(CONFIG["PEXELS_API_KEY"]),
        "smtp":    bool(CONFIG["SMTP_USER"]),
        "pillow":  HAS_PIL,
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
        "supabase_connected": bool(supabase),
        "profile_set":        bool(profile.get("company")),
    }

@app.get("/analytics")
async def get_analytics():
    jobs = get_all_jobs()
    now  = datetime.datetime.now()
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
    total    = len(jobs)
    posted   = sum(1 for j in jobs if j.get("status") == "posted")
    failed   = sum(1 for j in jobs if "failed" in str(j.get("status","")))
    approved = sum(1 for j in jobs if j.get("status") in ("approved","posted"))
    return {
        "total_posts":    total,
        "posted":         posted,
        "failed":         failed,
        "approved":       approved,
        "approval_rate":  round(approved/total*100 if total else 0, 1),
        "success_rate":   round(posted/(posted+failed)*100 if (posted+failed) else 0, 1),
        "posts_per_week": weekly,
        "posts_per_day":  daily,
    }

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
async def auth_callback(code: str, state: Optional[str]=None, error: Optional[str]=None):
    if error:
        return HTMLResponse(content=_auth_result_page(False,"Auth Failed",f"LinkedIn error: {error}"), status_code=400)
    try:
        token            = linkedin_exchange_code(code)
        urn, name, email = linkedin_get_userinfo(token)
        profile          = get_profile()
        profile.update({"urn": urn, "name": name, "email": email or profile.get("email","")})
        save_profile(profile)
        logger.info(f"[Auth] LinkedIn connected: {name} ({urn})")
        safe_name  = urllib.parse.quote(name, safe="")
        safe_email = urllib.parse.quote(email or "", safe="")
        frontend   = CONFIG["APP_BASE_URL"]
        return HTMLResponse(content=f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"><title>LinkedIn Connected</title>
<style>body{{background:#03050a;color:#e8f0fc;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:40px;max-width:400px;background:#0e1828;border:1px solid #1b2d45;border-radius:16px}}</style>
</head><body>
<div class="card">
<div style="font-size:56px">✅</div>
<h2 style="color:#10b981;margin:16px 0 8px">LinkedIn Connected!</h2>
<p>Signed in as <strong>{name}</strong></p>
<p style="color:#4a6080;font-size:12px;margin-top:14px">You can close this tab.</p>
</div>
<script>
if(window.opener && !window.opener.closed){{
  window.opener.postMessage({{type:'linkedin_connected',name:'{safe_name}',email:'{safe_email}'}},'*');
  setTimeout(()=>window.close(),800);
}}else{{window.location.href='{frontend}?linkedin_connected=1&name={safe_name}';}}
</script></body></html>""")
    except HTTPException as he:
        return HTMLResponse(content=_auth_result_page(False,"Auth Failed",he.detail), status_code=he.status_code)
    except Exception as e:
        logger.error(f"[Auth] Callback error: {e}")
        return HTMLResponse(content=_auth_result_page(False,"Auth Failed",str(e)), status_code=500)

@app.get("/auth/status")
async def auth_status():
    profile = get_profile()
    return {"connected": bool(get_token()), "urn": profile.get("urn"),
            "name": profile.get("name"), "email": profile.get("email")}

@app.delete("/auth/disconnect")
async def auth_disconnect():
    delete_token()
    return {"status": "disconnected"}

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

# ── Topics ─────────────────────────────────────────────────────────────────────
@app.post("/generate-topics")
async def gen_topics():
    profile = get_profile()
    if not profile.get("company"):
        raise HTTPException(status_code=400, detail="Set your brand profile first.")
    topics = generate_ai_topics(
        company=profile.get("company",""),
        domain=profile.get("domain",""),
        product=profile.get("product",""),
        name=profile.get("name",""),
        count=3
    )
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

    images  = []
    posters = []
    if data.image_count > 0:
        images  = fetch_images_for_post(profile, data.post_type, data.mood, data.topic, count=data.image_count)
        posters = build_posters_for_images(images, headline, profile, data.post_type, data.gradient, data.topic)

    # ── FIX: return public Supabase URL (p[2]) when available, else serve local via /li_cache/ ──
    poster_urls = []
    for p in posters:
        local_path, source, public_url = p
        if public_url:
            poster_urls.append(public_url)
        else:
            # Serve from local cache endpoint
            poster_urls.append(f"li_cache/{os.path.basename(local_path)}")

    return {
        "text":          cleaned,
        "posters":       poster_urls,
        "image_sources": [p[1] for p in posters],
        "image_thumbs":  [img.get("thumb","") for img in images],
        "topic":         data.topic,
        "headline":      headline,
    }

# ── Image Search ───────────────────────────────────────────────────────────────
@app.post("/images/search")
async def image_search_post(data: ImageSearchIn):
    results = search_images(data.query, data.count)
    if not results:
        raise HTTPException(status_code=404, detail="No images found.")
    return {"images": results, "count": len(results)}

@app.get("/images/search")
async def image_search_get(q: str, count: int = 9):
    return {"images": search_images(q, count), "count": len(search_images(q, count))}

# ── Image Edit ─────────────────────────────────────────────────────────────────
@app.post("/images/edit")
async def image_edit_endpoint(data: ImageEditIn):
    if not os.path.exists(data.image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {data.image_path}")
    return {"edited_path": edit_image(data.image_path, data.operations), "original_path": data.image_path}

# ── Instant Post (multipart) ───────────────────────────────────────────────────
@app.post("/api/posts/instant")
async def publish_instant_post(
    text:  str          = Form(...),
    urn:   str          = Form(...),
    image: Optional[UploadFile] = File(None)
):
    token = get_token()
    if not token:
        raise HTTPException(status_code=401, detail="LinkedIn not authenticated.")

    image_path = None
    if image and image.filename:
        try:
            suffix = Path(image.filename).suffix or ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await image.read())
                image_path = tmp.name
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image save error: {e}")

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

# ── Post Now (legacy JSON endpoint) ───────────────────────────────────────────
@app.post("/post/now")
async def post_now(data: PostNowIn):
    token   = _require_auth()
    profile = get_profile()
    urn     = profile.get("urn")
    cleaned = clean_for_linkedin(data.text)
    image_path = data.image_path

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
):
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")
    try:
        datetime.datetime.strptime(scheduled_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime. Use: YYYY-MM-DD HH:MM")

    # Upload image immediately for persistence
    image_url = None
    if image and image.filename:
        try:
            suffix = Path(image.filename).suffix or ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await image.read())
                tmp_path = tmp.name
            image_url = upload_image_to_supabase(tmp_path)
            if not image_url:
                # Fallback: copy to scheduled_images dir (local only)
                import shutil
                dest = os.path.join(CONFIG["SCHEDULED_IMAGES_DIR"], f"sched_{uuid.uuid4()}{suffix}")
                shutil.copy2(tmp_path, dest)
                # Can't serve this after Render restart, but better than nothing
            try: os.unlink(tmp_path)
            except: pass
        except Exception as e:
            logger.error(f"[Schedule] Image upload error: {e}")
            raise HTTPException(status_code=500, detail=f"Image upload failed: {e}")

    # ── FIX: clean single job dict, no duplicate keys, no NameError ──
    job_id = str(uuid.uuid4())
    job = {
        "id":             job_id,
        "text":           text,
        "image_url":      image_url,       # Supabase public URL or None
        "datetime":       scheduled_datetime,
        "status":         "pending",
        "mode":           "manual",
        "post_type":      post_type or "",
        "urn":            urn,
        "company":        profile.get("company",""),
        "domain":         profile.get("domain",""),
        "product":        profile.get("product",""),
        "approval_email": profile.get("email",""),
        "created_at":     datetime.datetime.utcnow().isoformat(),
    }
    _supabase_insert_job(job)

    return {
        "status":        "scheduled",
        "job_id":        job_id,
        "scheduled_for": scheduled_datetime,
        "image_url":     image_url,
    }

# ── Campaign ───────────────────────────────────────────────────────────────────
@app.post("/campaign")
async def create_campaign(data: CampaignIn):
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing.")
    if not (1 <= data.days <= 90):
        raise HTTPException(status_code=400, detail="Days must be 1-90.")
    try:
        start_dt = datetime.datetime.strptime(data.start_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_datetime. Use YYYY-MM-DD HH:MM")

    created = []
    for i in range(data.days):
        schedule_dt = start_dt + datetime.timedelta(days=i)
        job_id = str(uuid.uuid4())
        job = {
            "id":         job_id,
            "datetime":   schedule_dt.strftime("%Y-%m-%d %H:%M"),
            "status":     "pending",
            "mode":       "ai_auto",
            "topic":      data.topic,
            "urn":        urn,
            "company":    profile.get("company",""),
            "domain":     profile.get("domain",""),
            "product":    profile.get("product",""),
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        _supabase_insert_job(job)  # FIX: uses safe insert with fallback
        created.append(job_id)

    return {"status": "campaign_created", "days": data.days, "topic": data.topic,
            "start": data.start_datetime, "job_ids": created}

# ── Auto Campaign ──────────────────────────────────────────────────────────────
@app.post("/campaign/auto")
async def auto_campaign(data: AutoCampaignIn, background_tasks: BackgroundTasks):
    profile = get_profile()
    urn     = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing.")
    if not (1 <= data.days <= 90):
        raise HTTPException(status_code=400, detail="Days must be 1-90.")

    industry   = data.industry or profile.get("domain","technology")
    domain     = data.domain   or profile.get("domain","SaaS")
    product    = data.product  or profile.get("product","software")
    total_posts = data.days * data.posts_per_day
    time_slots  = (data.time_slots or ["09:00","14:00","18:00"])[:data.posts_per_day]

    try:
        start_date = datetime.datetime.strptime(data.start_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_date. Use YYYY-MM-DD")

    topics = generate_ai_topics(industry, domain, product, profile.get("company",""), total_posts)
    if not topics:
        raise HTTPException(status_code=500, detail="Failed to generate topics.")
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
                "id":             job_id,
                "datetime":       sched.strftime("%Y-%m-%d %H:%M"),
                "status":         "pending",
                "mode":           "ai_auto",
                "topic":          topic,
                "tone":           data.tone,
                "mood":           data.mood,
                "gradient":       data.gradient,
                "urn":            urn,
                "company":        profile.get("company",""),
                "domain":         domain,
                "product":        product,
                "approval_email": data.approval_email or profile.get("email",""),
                "created_at":     datetime.datetime.utcnow().isoformat(),
            }
            _supabase_insert_job(job)  # FIX: safe insert with fallback
            created.append({"id": job_id, "topic": topic, "datetime": sched.strftime("%Y-%m-%d %H:%M")})

    return {"status": "auto_campaign_created", "days": data.days,
            "posts_per_day": data.posts_per_day, "total_posts": len(created),
            "topics_generated": len(topics), "jobs": created}

# ── Approvals ──────────────────────────────────────────────────────────────────
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
        text = data.custom_text or ""
        if not text:
            variations = approval.get("variations", [])
            if variations and data.variation_index < len(variations):
                text = variations[data.variation_index].get("text","")
        update_approval(data.approval_id, {
            "status": "approved", "selected_variation": data.variation_index,
            "selected_image": data.image_index, "approved_text": text,
            "approved_at": datetime.datetime.utcnow().isoformat(),
        })
        if job_id:
            # FIX: store approved_text AND selected_image on the job so scheduler can use them
            update_job_status(job_id, "approved", {
                "approved_text":  text,
                "selected_image": data.image_index,
            })
        return {"status": "approved", "approval_id": data.approval_id}

    elif data.action == "reject":
        update_approval(data.approval_id, {"status": "rejected"})
        if job_id: update_job_status(job_id, "rejected")
        return {"status": "rejected"}

    elif data.action == "skip":
        update_approval(data.approval_id, {"status": "skipped"})
        if job_id: update_job_status(job_id, "skipped")
        return {"status": "skipped"}

    raise HTTPException(status_code=400, detail="action must be: approve, reject, or skip")


@app.get("/approve/{approval_id}", response_class=HTMLResponse)
async def approval_link_handler(
    approval_id: str,
    action:    Optional[str] = None,
    choice:    Optional[str] = None,
    variation: Optional[int] = 0,
    image:     Optional[int] = 0,
):
    """One-click approval from email links."""
    approval = get_approval_by_id(approval_id)
    if not approval:
        return HTMLResponse(content=_auth_result_page(False,"Not Found","Approval record not found."), status_code=404)

    if action == "reject":
        update_approval(approval_id, {"status": "rejected"})
        if approval.get("job_id"): update_job_status(approval["job_id"], "rejected")
        msg, color = "❌ Post rejected.", "#ef4444"

    elif action == "skip":
        update_approval(approval_id, {"status": "skipped"})
        if approval.get("job_id"): update_job_status(approval["job_id"], "skipped")
        msg, color = "⏭ Post skipped.", "#64748b"

    elif choice:
        vi    = ord(choice.lower()) - ord('a')
        vars_ = approval.get("variations", [])
        text  = vars_[vi].get("text","") if vi < len(vars_) else ""
        img_idx = image if image is not None else 0

        update_approval(approval_id, {
            "status":            "approved",
            "selected_variation": vi,
            "selected_image":    img_idx,
            "approved_text":     text,
            "approved_at":       datetime.datetime.utcnow().isoformat(),
        })
        if approval.get("job_id"):
            # FIX: write approved_text + selected_image to job so _post_approved_jobs can read them
            update_job_status(approval["job_id"], "approved", {
                "approved_text":  text,
                "selected_image": img_idx,
            })
        msg, color = f"✅ Variation {choice.upper()} approved! Will post at scheduled time.", "#22c55e"

    else:
        msg, color = "⚠ Unknown action.", "#f59e0b"

    icon = "✅" if "approved" in msg.lower() else ("❌" if "rejected" in msg.lower() else "⏭")
    return HTMLResponse(content=f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"><title>Approval</title>
<style>body{{background:#03050a;color:#e8f0fc;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:40px;background:#0e1828;border:1px solid #1b2d45;border-radius:16px}}</style>
</head><body>
<div class="card">
<div style="font-size:56px">{icon}</div>
<h2 style="color:{color};margin:16px 0 8px">{msg}</h2>
<p style="color:#4a6080">You can close this tab.</p>
</div></body></html>""")


# ── Jobs ───────────────────────────────────────────────────────────────────────
@app.get("/jobs")
async def list_jobs(status: Optional[str] = None):
    jobs     = get_all_jobs(status)
    total    = len(jobs)
    return {
        "stats": {
            "total":    total,
            "pending":  sum(1 for j in jobs if j.get("status")=="pending"),
            "posted":   sum(1 for j in jobs if j.get("status")=="posted"),
            "failed":   sum(1 for j in jobs if "failed" in str(j.get("status",""))),
            "approved": sum(1 for j in jobs if j.get("status")=="approved"),
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
        except Exception as e: logger.warning(f"[Supabase] clear_all_jobs: {e}")
    _save_json(_JOBS_FILE, [])
    return {"status": "all_jobs_cleared"}

# ── Serve cached poster images ─────────────────────────────────────────────────
@app.get("/li_cache/{filename}")
async def serve_cache(filename: str):
    path = os.path.join(CONFIG["CACHE_DIR"], filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

# ── Debug ──────────────────────────────────────────────────────────────────────
@app.get("/debug/gemini")
def debug_gemini():
    return {"loaded_keys": len(GEMINI_API_KEYS),
            "keys_present": [f"KEY_{i+1}" for i,k in enumerate(GEMINI_API_KEYS) if k]}

# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home():
    for candidate in ["linkedin-studio-pro (4).html","index.html","frontend.html"]:
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="""<!DOCTYPE html><html>
<head><title>LinkedIn Studio PRO v4.0</title></head>
<body style="background:#03050a;color:#e8f0fc;font-family:system-ui;padding:40px;text-align:center">
<h1 style="color:#0ea5e9">LinkedIn Studio PRO v4.0</h1>
<p>Place <code>linkedin-studio-pro (4).html</code> in the same directory as <code>main.py</code>.</p>
<p><a href="/docs" style="color:#0ea5e9">→ API Docs</a></p>
</body></html>""")


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["PORT"], reload=False, log_level="info")
