"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      LinkedIn Studio PRO v3.0 — FastAPI Web Edition (Render-Ready)          ║
║   REST API + Background Scheduler · No GUI · Runs on Render Web Service     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys, os, json, time, threading, random, webbrowser
import urllib.parse, base64, io
import datetime, textwrap, re, math
from pathlib import Path
from contextlib import asynccontextmanager

# ── FastAPI ───────────────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

import requests as http_requests

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "LINKEDIN_CLIENT_ID":     os.environ.get("LINKEDIN_CLIENT_ID"),
    "LINKEDIN_CLIENT_SECRET": os.environ.get("LINKEDIN_CLIENT_SECRET"),
    "LINKEDIN_REDIRECT_URI":  os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback"),
    "LINKEDIN_SCOPES":        os.environ.get("LINKEDIN_SCOPES", "openid profile w_member_social email"),
    "GEMINI_API_KEY":         os.environ.get("GEMINI_API_KEY"),
    "GEMINI_MODEL":           os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
    "PIXABAY_API_KEY":        os.environ.get("PIXABAY_API_KEY"),
    "PEXELS_API_KEY":         os.environ.get("PEXELS_API_KEY"),
    "TOKEN_FILE":             os.environ.get("TOKEN_FILE", "li_tokens.json"),
    "PROFILE_FILE":           os.environ.get("PROFILE_FILE", "li_profile.json"),
    "SCHEDULER_FILE":         os.environ.get("SCHEDULER_FILE", "scheduler_jobs.json"),
    "CACHE_DIR":              os.environ.get("CACHE_DIR", "li_cache"),
    "SCHEDULED_IMAGES_DIR":   os.environ.get("SCHEDULED_IMAGES_DIR", "scheduled_images"),
    "PORT":                   int(os.environ.get("PORT", 8000)),
}

os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
os.makedirs(CONFIG["SCHEDULED_IMAGES_DIR"], exist_ok=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[Supabase] Connection failed: {e}")

# ── Design constants ──────────────────────────────────────────────────────────

POST_TYPES = {
    "individual": [
        "Thought Leadership", "Text Post", "Motivational",
        "Story / Experience", "Hot Take / Opinion", "Career Milestone",
    ],
    "company": [
        "Brand Announcement", "Hiring / Recruiting", "Festival / Occasion",
        "Product / Feature Launch", "Company Milestone", "Event / Workshop",
        "Industry News", "Culture & Values",
    ],
}

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

# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def get_token():
    data = _load_json(CONFIG["TOKEN_FILE"])
    return data.get("access_token") if data else None

def get_profile():
    return _load_json(CONFIG["PROFILE_FILE"]) or {}

def save_profile(d):
    _save_json(CONFIG["PROFILE_FILE"], d)

# ── Supabase helpers ──────────────────────────────────────────────────────────

def save_job_db(job):
    if supabase:
        try:
            supabase.table("scheduled_posts").insert(job).execute()
        except Exception as e:
            print(f"[Supabase save_job] {e}")

def update_job_status(job_id, status):
    if supabase:
        try:
            supabase.table("scheduled_posts").update({"status": status}).eq("id", job_id).execute()
        except Exception as e:
            print(f"[Supabase update_status] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  LINKEDIN API
# ═══════════════════════════════════════════════════════════════════════════════

def linkedin_get_auth_url():
    params = {
        "response_type": "code",
        "client_id":     CONFIG["LINKEDIN_CLIENT_ID"],
        "redirect_uri":  CONFIG["LINKEDIN_REDIRECT_URI"],
        "scope":         CONFIG["LINKEDIN_SCOPES"],
    }
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)

def linkedin_exchange_code(code: str):
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
    token_data = resp.json()
    _save_json(CONFIG["TOKEN_FILE"], token_data)
    return token_data.get("access_token")

def linkedin_get_userinfo(access_token):
    r = http_requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    info = r.json()
    return info.get("sub"), info.get("name", "User"), info.get("email", "")

def linkedin_post_text(access_token, urn, text):
    payload = {
        "author": f"urn:li:person:{urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    r = http_requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload,
        timeout=20,
    )
    return r.status_code, r.json()

def linkedin_post_with_image(access_token, urn, text, image_path):
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
        json=reg_payload,
        timeout=15,
    )
    reg_data = reg_r.json()
    upload_url = reg_data["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn = reg_data["value"]["asset"]

    with open(image_path, "rb") as img_f:
        http_requests.put(
            upload_url,
            data=img_f.read(),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    payload = {
        "author": f"urn:li:person:{urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
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
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload,
        timeout=20,
    )
    return r.status_code, r.json()

# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI AI
# ═══════════════════════════════════════════════════════════════════════════════

_gemini_model = None

def get_gemini():
    global _gemini_model
    if _gemini_model is None and HAS_GEMINI and CONFIG["GEMINI_API_KEY"]:
        genai.configure(api_key=CONFIG["GEMINI_API_KEY"])
        _gemini_model = genai.GenerativeModel(CONFIG["GEMINI_MODEL"])
    return _gemini_model

def gemini_generate(prompt, retries=3):
    m = get_gemini()
    if m is None:
        return "[Gemini not available]"
    for attempt in range(1, retries + 1):
        try:
            resp = m.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                time.sleep(attempt * 8)
            else:
                return f"[AI error: {e}]"
    return "[AI quota exhausted — try again later]"

# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE SEARCH & POSTER BUILDER  (unchanged logic from original)
# ═══════════════════════════════════════════════════════════════════════════════

def build_domain_image_queries(profile, post_type, mood, topic):
    company  = profile.get("company", "")
    domain   = profile.get("domain", "").strip()
    product  = profile.get("product", "").strip()
    mood_w   = MOODS.get(mood, "professional corporate")
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()

    if HAS_GEMINI and domain:
        prompt = f"""You are a visual content strategist.
Company: {company}
Industry/Domain: {domain}
Product/Service: {product}
Post Type: {pt_clean}
Topic: {topic}

Generate exactly 3 stock photo search queries (5-8 words each).
Return ONLY a JSON array of 3 strings. No markdown. No explanation."""
        raw = gemini_generate(prompt)
        try:
            raw = re.sub(r"```json|```", "", raw).strip()
            queries = json.loads(raw)
            if isinstance(queries, list) and len(queries) >= 2:
                return queries[:3]
        except Exception:
            pass

    domain_words  = domain.lower().replace(",", " ").split()[:3]
    product_words = product.lower().replace(",", " ").split()[:3]
    d  = " ".join(domain_words[:2])
    pr = " ".join(product_words[:2])
    return [
        f"{pr} product professional",
        f"person using {pr} {d}",
        f"{d} industry modern {pr}",
    ]

def _search_stock(query, count):
    results = []
    if CONFIG["PIXABAY_API_KEY"] and len(results) < count:
        try:
            r = http_requests.get(
                "https://pixabay.com/api/",
                params={
                    "key": CONFIG["PIXABAY_API_KEY"], "q": query,
                    "image_type": "photo", "per_page": min(count + 2, 10),
                    "safesearch": "true", "order": "popular",
                    "min_width": 800, "orientation": "horizontal",
                },
                timeout=10,
            )
            for hit in r.json().get("hits", [])[:count]:
                results.append({"url": hit["largeImageURL"], "thumb": hit["webformatURL"],
                                 "source": "Pixabay", "query": query})
        except Exception:
            pass

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
                                 "source": "Pexels", "query": query})
        except Exception:
            pass
    return results[:count]

def fetch_images_for_post(profile, post_type, mood, topic, count=3):
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

    domain  = profile.get("domain", "technology")
    product = profile.get("product", "product")
    while len(unique) < count:
        ai_prompt = f"{product} {domain} professional high quality product photography"
        enc  = urllib.parse.quote_plus(ai_prompt)
        seed = random.randint(1, 999999)
        unique.append({
            "url":    f"https://image.pollinations.ai/prompt/{enc}?width=1200&height=900&seed={seed}&nologo=true",
            "thumb":  f"https://image.pollinations.ai/prompt/{enc}?width=400&height=300&seed={seed}&nologo=true",
            "source": "AI Generated", "query": ai_prompt,
        })
    return unique[:count]

def download_image(url, save_path):
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

# ── Fonts ─────────────────────────────────────────────────────────────────────

def _load_font(size, bold=True):
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "calibrib.ttf", "segoeuib.ttf"] if bold
        else ["arial.ttf", "Arial.ttf", "calibri.ttf", "segoeui.ttf"]
    )
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

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))

# ── Poster layouts (same as original) ────────────────────────────────────────

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
        t = 1.0 - min(1.0, x / 650)
        alpha = int(220 * (t ** 0.7))
        col = _lerp_color(drk, (drk[0], drk[1] + 5, drk[2] + 8), 1 - t)
        for y in range(H):
            overlay.putpixel((x, y), (col[0], col[1], col[2], alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    ImageDraw.Draw(Image.new("RGBA", (W, H), (0, 0, 0, 0)))
    accent_bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(accent_bar).rectangle([(0, 0), (6, H)], fill=(*acc, 255))
    canvas = Image.alpha_composite(canvas, accent_bar)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(28, bold=True)
    f_title = _load_font(82 if len(headline) < 25 else 62, bold=True)
    f_tag   = _load_font(20, bold=False)
    f_sub   = _load_font(30, bold=False)
    draw.text((50, 50), org_name.upper(), font=f_brand, fill=(*acc, 255))
    draw.line([(50, 88), (300, 88)], fill=(*acc, 180), width=3)
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.rounded_rectangle((50, 96, 50 + len(pt_clean) * 12 + 24, 130),
                            radius=6, fill=(*acc, 30), outline=(*acc, 100))
    draw.text((62, 100), pt_clean.upper(), font=f_tag, fill=(*acc, 220))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0, 0), " ".join(curr), font=f_title)[2] > 700:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    y = 200
    for line in lines[:3]:
        draw.text((52, y + 3), line, font=f_title, fill=(0, 0, 0, 130))
        draw.text((50, y), line, font=f_title, fill=(255, 255, 255, 255))
        y += int(f_title.size * 1.15)
    if domain:
        tag = f"  {domain}  "
        tw = draw.textbbox((0, 0), tag, font=f_sub)[2]
        draw.rounded_rectangle((50, H - 80, 50 + tw + 24, H - 44),
                                radius=10, fill=(*acc, 25), outline=(*acc, 80))
        draw.text((62, H - 76), tag, font=f_sub, fill=(*acc, 220))
    return canvas.convert("RGB")

def build_poster_layout_2(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))
    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.7)
    canvas.paste(bg.convert("RGBA"), (0, 0))
    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(H):
        t = max(0, (y - H * 0.3) / (H * 0.7))
        alpha = int(230 * min(1.0, t ** 0.65))
        col = _lerp_color((10, 12, 20), drk, t)
        ImageDraw.Draw(overlay).line([(0, y), (W, y)], fill=(*col, alpha))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    f_brand = _load_font(26, bold=True)
    f_title = _load_font(90 if len(headline) < 20 else 68, bold=True)
    f_tag   = _load_font(20, bold=False)
    org_w = draw.textbbox((0, 0), org_name.upper(), font=f_brand)[2]
    draw.text(((W - org_w) // 2, 36), org_name.upper(), font=f_brand, fill=(*acc, 240))
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0, 0), " ".join(curr), font=f_title)[2] > W - 120:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    total_h = len(lines) * int(f_title.size * 1.12)
    y = H - total_h - 100
    for line in lines[:3]:
        lw = draw.textbbox((0, 0), line, font=f_title)[2]
        x  = (W - lw) // 2
        draw.text((x + 3, y + 3), line, font=f_title, fill=(0, 0, 0, 100))
        draw.text((x, y), line, font=f_title, fill=(255, 255, 255, 255))
        y += int(f_title.size * 1.12)
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.line([(W // 2 - 100, H - 78), (W // 2 + 100, H - 78)], fill=(*acc, 200), width=3)
    tw = draw.textbbox((0, 0), pt_clean.upper(), font=f_tag)[2]
    draw.text(((W - tw) // 2, H - 62), pt_clean.upper(), font=f_tag, fill=(*acc, 200))
    return canvas.convert("RGB")

LAYOUT_BUILDERS = [build_poster_layout_1, build_poster_layout_2]

def build_posters_for_images(images_data, headline, profile, post_type, gradient_name, topic):
    org_name  = profile.get("company", profile.get("name", ""))
    domain    = profile.get("domain", "")
    grad_list = list(GRADIENTS.values())
    g_keys    = list(GRADIENTS.keys())
    g_idx     = g_keys.index(gradient_name) if gradient_name in g_keys else 0
    dark_hex, accent_hex = grad_list[g_idx]

    posters = []
    for i, item in enumerate(images_data):
        raw_path = os.path.join(CONFIG["CACHE_DIR"], f"raw_bg_{i}_{int(time.time())}.jpg")
        ok = download_image(item["url"], raw_path)
        if not ok:
            enc  = urllib.parse.quote_plus(item.get("query", "business professional"))
            seed = random.randint(1, 999999)
            url2 = f"https://image.pollinations.ai/prompt/{enc}?width=1200&height=900&seed={seed}&nologo=true"
            ok   = download_image(url2, raw_path)
            item["source"] = "AI Generated"
        if not ok:
            continue
        try:
            bg_img    = Image.open(raw_path).convert("RGB")
            layout_fn = LAYOUT_BUILDERS[i % len(LAYOUT_BUILDERS)]
            poster    = layout_fn(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex)
            out_path  = os.path.join(CONFIG["CACHE_DIR"], f"poster_{i}_{int(time.time())}.png")
            poster.save(out_path, "PNG")
            posters.append((out_path, item.get("source", "Stock Photo")))
        except Exception as e:
            print(f"Poster build error {i}: {e}")
    return posters

# ═══════════════════════════════════════════════════════════════════════════════
#  TEXT GENERATION + LINKEDIN FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def _unicode_bold(text):
    bold_map = {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        bold_map[c] = chr(0x1D400 + i)
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        bold_map[c] = chr(0x1D41A + i)
    for i, c in enumerate("0123456789"):
        bold_map[c] = chr(0x1D7CE + i)
    return "".join(bold_map.get(c, c) for c in text)

def clean_for_linkedin(text):
    if not text:
        return text
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    lines = text.split('\n')
    processed = []
    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r'^#{1,4}\s+(.+)$', stripped)
        if heading_match:
            processed.append(_unicode_bold(heading_match.group(1).strip().upper()))
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

def generate_post_text(profile, post_type, tone, mood, topic, extra_info=""):
    org_name   = profile.get("company", "")
    domain     = profile.get("domain", "")
    product    = profile.get("product", "")
    name       = profile.get("name", "Professional")
    utype      = profile.get("user_type", "individual")
    is_company = utype == "company"
    mood_desc  = MOODS.get(mood, "professional")
    ctx = f"""
Organization: {org_name or name}
Domain / Industry: {domain}
Product / Service: {product}
Account Type: {"Company Page" if is_company else "Individual Professional"}
Post Type: {post_type}
Tone: {tone}
Mood: {mood_desc}
Topic: {topic}
Extra Info: {extra_info}
"""
    prompt = f"""{ctx}
Write a professional LinkedIn post about: "{topic}".
- Powerful 1-line **bold** hook
- Short paragraphs (1-2 sentences)
- 3 ✦ value-packed points
- CTA question for comments
- 5 relevant hashtags on last line
- {"Company voice (We/Our)" if is_company else "Personal voice (I/My)"}
- Max 200 words. NO preamble."""
    return gemini_generate(prompt)

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND SCHEDULER (runs as a thread inside the FastAPI process)
# ═══════════════════════════════════════════════════════════════════════════════

def _scheduler_mark_done(job_id, status):
    all_jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    for j in all_jobs:
        if j.get("id") == job_id:
            j["status"] = status
            break
    _save_json(CONFIG["SCHEDULER_FILE"], all_jobs)
    update_job_status(job_id, status)

def run_scheduler_daemon():
    print("[Scheduler] Started — checking every 30s")
    while True:
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            tokens  = _load_json(CONFIG["TOKEN_FILE"]) or {}
            token   = tokens.get("access_token")
            all_jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
            due = [j for j in all_jobs
                   if j.get("status", "pending") == "pending"
                   and j.get("datetime", "9999") <= now_str]

            for job in due:
                job_id = job.get("id")
                urn    = job.get("urn", "")
                print(f"[Scheduler] Processing job {job_id}")

                if not token or not urn:
                    _scheduler_mark_done(job_id, "failed (no token/urn)")
                    continue

                try:
                    if job.get("mode") == "ai_auto":
                        topic   = job.get("topic", "industry trends")
                        prompt  = (
                            f"Company: {job.get('company','')}\nDomain: {job.get('domain','')}\n"
                            f"Product: {job.get('product','')}\nTopic: {topic}\n\n"
                            "Write a LinkedIn post. Bold headline first, 3 ✦ bullets, 5 hashtags. 200 words max."
                        )
                        text = clean_for_linkedin(gemini_generate(prompt).strip())
                    else:
                        text = clean_for_linkedin(job.get("text", ""))

                    if not text:
                        _scheduler_mark_done(job_id, "failed (empty text)")
                        continue

                    image_path = job.get("image_path")
                    if image_path and os.path.exists(image_path):
                        st, resp = linkedin_post_with_image(token, urn, text, image_path)
                    else:
                        st, resp = linkedin_post_text(token, urn, text)

                    new_status = "posted" if st in (200, 201) else f"failed (HTTP {st})"
                    print(f"[Scheduler] Job {job_id} → {new_status}")
                except Exception as ex:
                    new_status = f"failed ({ex})"
                    print(f"[Scheduler] Job {job_id} error: {ex}")

                _scheduler_mark_done(job_id, new_status)

        except Exception as loop_err:
            print(f"[Scheduler loop error] {loop_err}")
        time.sleep(30)

# ═══════════════════════════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background scheduler thread on startup
    t = threading.Thread(target=run_scheduler_daemon, daemon=True)
    t.start()
    print("[App] Scheduler thread started")
    yield
    print("[App] Shutting down")

app = FastAPI(
    title="LinkedIn Studio PRO",
    description="Domain-aware AI LinkedIn publishing engine",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    name: str
    company: str
    domain: str
    product: str
    user_type: str = "company"
    urn: Optional[str] = None

class GeneratePostIn(BaseModel):
    topic: str
    headline: Optional[str] = None
    post_type: str = "Brand Announcement"
    tone: str = "Executive Authority"
    mood: str = "Professional"
    gradient: str = "Navy Sapphire"
    image_count: int = 2

class ScheduleJobIn(BaseModel):
    text: str
    scheduled_datetime: str          # "YYYY-MM-DD HH:MM"
    post_type: Optional[str] = ""
    image_path: Optional[str] = None

class CampaignIn(BaseModel):
    days: int
    topic: str
    start_datetime: str              # "YYYY-MM-DD HH:MM"

class PostNowIn(BaseModel):
    text: str
    image_path: Optional[str] = None

# ── Health & home ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home():
    profile = get_profile()
    token   = get_token()
    jobs    = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    pending = sum(1 for j in jobs if j.get("status") == "pending")
    posted  = sum(1 for j in jobs if j.get("status") == "posted")

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>LinkedIn Studio PRO</title>
      <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ background: #060810; color: #f0f6fc; font-family: 'Segoe UI', sans-serif;
                min-height: 100vh; padding: 40px 20px; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ font-size: 2rem; color: #38bdf8; margin-bottom: 6px; }}
        .sub {{ color: #8b949e; margin-bottom: 32px; font-size: 0.95rem; }}
        .card {{ background: #0c0f1a; border: 1px solid #1e2433; border-radius: 16px;
                  padding: 24px; margin-bottom: 20px; }}
        .card h2 {{ color: #38bdf8; font-size: 1.1rem; margin-bottom: 14px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px;
                   font-size: 0.8rem; font-weight: 600; margin-right: 8px; }}
        .green  {{ background: #14532d; color: #22c55e; }}
        .yellow {{ background: #3f2800; color: #fbbf24; }}
        .red    {{ background: #3f0000; color: #ef4444; }}
        .blue   {{ background: #0c2a44; color: #38bdf8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                  gap: 16px; margin-top: 16px; }}
        .stat {{ background: #141824; border-radius: 12px; padding: 20px; text-align: center; }}
        .stat-num {{ font-size: 2rem; font-weight: bold; color: #38bdf8; }}
        .stat-label {{ font-size: 0.85rem; color: #8b949e; margin-top: 4px; }}
        .endpoint {{ background: #0a0d16; border-radius: 8px; padding: 10px 16px;
                      margin: 6px 0; font-family: monospace; font-size: 0.88rem; }}
        .method {{ color: #22c55e; margin-right: 10px; font-weight: bold; }}
        .path   {{ color: #38bdf8; }}
        .desc   {{ color: #8b949e; font-size: 0.82rem; margin-top: 3px; padding-left: 48px; }}
        a {{ color: #38bdf8; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h1>⚡ LinkedIn Studio PRO</h1>
        <p class="sub">Domain-Aware AI Publishing Engine · v3.0 · Running on Render</p>

        <div class="card">
          <h2>🔌 Connection Status</h2>
          {"<span class='badge green'>● LinkedIn Connected</span>" if token else "<span class='badge red'>● LinkedIn Not Connected</span>"}
          {"<span class='badge green'>● Profile Set</span>" if profile.get('company') else "<span class='badge yellow'>● Profile Not Set</span>"}
          {"<span class='badge green'>● Gemini Ready</span>" if HAS_GEMINI and CONFIG['GEMINI_API_KEY'] else "<span class='badge red'>● Gemini Not Configured</span>"}
          {"<span class='badge green'>● Supabase Connected</span>" if supabase else "<span class='badge yellow'>● Supabase Not Connected</span>"}
          <p style="margin-top:14px; color:#8b949e; font-size:0.9rem;">
            To connect LinkedIn: <a href="/auth/login">GET /auth/login</a>
          </p>
        </div>

        <div class="card">
          <h2>📊 Scheduler Stats</h2>
          <div class="grid">
            <div class="stat"><div class="stat-num">{len(jobs)}</div><div class="stat-label">Total Jobs</div></div>
            <div class="stat"><div class="stat-num" style="color:#fbbf24">{pending}</div><div class="stat-label">Pending</div></div>
            <div class="stat"><div class="stat-num" style="color:#22c55e">{posted}</div><div class="stat-label">Posted</div></div>
            <div class="stat"><div class="stat-num" style="color:#8b949e">{profile.get('company','—')}</div><div class="stat-label">Company</div></div>
          </div>
        </div>

        <div class="card">
          <h2>🔗 API Endpoints</h2>

          <div class="endpoint"><span class="method">GET</span><span class="path">/auth/login</span></div>
          <div class="desc">Redirects to LinkedIn OAuth login</div>

          <div class="endpoint"><span class="method">GET</span><span class="path">/auth/callback?code=...</span></div>
          <div class="desc">LinkedIn OAuth callback — exchanges code for token</div>

          <div class="endpoint"><span class="method">POST</span><span class="path">/profile</span></div>
          <div class="desc">Save brand profile (name, company, domain, product, user_type)</div>

          <div class="endpoint"><span class="method">GET</span><span class="path">/profile</span></div>
          <div class="desc">Get current brand profile</div>

          <div class="endpoint"><span class="method">POST</span><span class="path">/generate</span></div>
          <div class="desc">Generate AI post text + poster images for a topic</div>

          <div class="endpoint"><span class="method">POST</span><span class="path">/post/now</span></div>
          <div class="desc">Immediately post text (+ optional image) to LinkedIn</div>

          <div class="endpoint"><span class="method">POST</span><span class="path">/schedule</span></div>
          <div class="desc">Add a post to the scheduler queue</div>

          <div class="endpoint"><span class="method">POST</span><span class="path">/campaign</span></div>
          <div class="desc">Schedule an AI-powered multi-day content campaign</div>

          <div class="endpoint"><span class="method">GET</span><span class="path">/jobs</span></div>
          <div class="desc">List all scheduled jobs</div>

          <div class="endpoint"><span class="method">DELETE</span><span class="path">/jobs/{{job_id}}</span></div>
          <div class="desc">Delete a scheduled job</div>

          <div class="endpoint"><span class="method">GET</span><span class="path">/health</span></div>
          <div class="desc">Health check</div>

          <div class="endpoint"><span class="method">GET</span><span class="path">/docs</span></div>
          <div class="desc">Interactive Swagger UI (auto-generated by FastAPI)</div>
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "scheduler": "running",
        "gemini": HAS_GEMINI and bool(CONFIG["GEMINI_API_KEY"]),
        "linkedin_token": bool(get_token()),
        "supabase": bool(supabase),
    }

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    from fastapi.responses import RedirectResponse
    url = linkedin_get_auth_url()
    return RedirectResponse(url=url)

@app.get("/auth/callback")
async def auth_callback(code: str):
    try:
        token = linkedin_exchange_code(code)
        if not token:
            raise HTTPException(status_code=400, detail="Token exchange failed")
        urn, name, email = linkedin_get_userinfo(token)
        profile = get_profile()
        profile.update({"urn": urn, "name": name, "email": email})
        save_profile(profile)
        return HTMLResponse(content=f"""
        <html><body style='background:#060810;color:#f0f6fc;font-family:sans-serif;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
        <div style='text-align:center'>
          <h2 style='font-size:60px;margin:0'>✓</h2>
          <h2 style='color:#22c55e'>Authentication Successful!</h2>
          <p style='color:#8b949e'>Logged in as: <strong>{name}</strong> ({email})</p>
          <p style='color:#8b949e;margin-top:12px'>You can now use the API. 
          Next: <a href='/profile' style='color:#38bdf8'>POST /profile</a> to set your brand profile.</p>
        </div></body></html>""")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Profile ───────────────────────────────────────────────────────────────────

@app.post("/profile")
async def set_profile(data: ProfileIn):
    profile = get_profile()
    profile.update(data.dict())
    save_profile(profile)
    return {"status": "saved", "profile": profile}

@app.get("/profile")
async def read_profile():
    return get_profile()

# ── Generate Post ─────────────────────────────────────────────────────────────

@app.post("/generate")
async def generate(data: GeneratePostIn):
    profile = get_profile()
    if not profile.get("company"):
        raise HTTPException(status_code=400, detail="Set your profile first via POST /profile")

    headline = data.headline or data.topic[:50]

    # Generate text
    raw_text = generate_post_text(
        profile, data.post_type, data.tone, data.mood, data.topic
    )
    cleaned_text = clean_for_linkedin(raw_text)

    # Fetch images
    images = fetch_images_for_post(
        profile, data.post_type, data.mood, data.topic, count=data.image_count
    )

    # Build posters
    posters = build_posters_for_images(
        images, headline, profile, data.post_type, data.gradient, data.topic
    )

    poster_paths = [p[0] for p in posters]

    return {
        "text": cleaned_text,
        "posters": poster_paths,
        "image_sources": [p[1] for p in posters],
        "topic": data.topic,
        "headline": headline,
    }

# ── Post Now ──────────────────────────────────────────────────────────────────

@app.post("/post/now")
async def post_now(data: PostNowIn):
    token = get_token()
    profile = get_profile()
    urn = profile.get("urn")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth/login first.")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Re-authenticate.")

    cleaned = clean_for_linkedin(data.text)

    if data.image_path and os.path.exists(data.image_path):
        st, resp = linkedin_post_with_image(token, urn, cleaned, data.image_path)
    else:
        st, resp = linkedin_post_text(token, urn, cleaned)

    if st in (200, 201):
        return {"status": "posted", "linkedin_response": resp}
    else:
        raise HTTPException(status_code=st, detail=resp)

# ── Schedule Single Job ───────────────────────────────────────────────────────

@app.post("/schedule")
async def schedule_job(data: ScheduleJobIn):
    profile = get_profile()
    urn = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")

    # Validate datetime
    try:
        datetime.datetime.strptime(data.scheduled_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use YYYY-MM-DD HH:MM")

    # Copy image to permanent location
    image_path = None
    if data.image_path and os.path.exists(data.image_path):
        import shutil
        sched_dir = CONFIG["SCHEDULED_IMAGES_DIR"]
        dest = os.path.join(sched_dir, f"sched_{int(time.time()*1000)}.png")
        shutil.copy2(data.image_path, dest)
        image_path = dest

    jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    job = {
        "id":         int(time.time() * 1000),
        "datetime":   data.scheduled_datetime,
        "status":     "pending",
        "text":       data.text,
        "urn":        urn,
        "image_path": image_path,
        "post_type":  data.post_type,
        "company":    profile.get("company", ""),
        "domain":     profile.get("domain", ""),
        "product":    profile.get("product", ""),
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    jobs.append(job)
    _save_json(CONFIG["SCHEDULER_FILE"], jobs)
    save_job_db(job)

    return {
        "status": "scheduled",
        "job_id": job["id"],
        "scheduled_for": data.scheduled_datetime,
        "has_image": bool(image_path),
    }

# ── Campaign ──────────────────────────────────────────────────────────────────

@app.post("/campaign")
async def create_campaign(data: CampaignIn):
    profile = get_profile()
    urn = profile.get("urn")
    if not urn:
        raise HTTPException(status_code=400, detail="LinkedIn URN missing. Authenticate first.")
    if data.days < 1 or data.days > 90:
        raise HTTPException(status_code=400, detail="Days must be between 1 and 90.")

    try:
        start_dt = datetime.datetime.strptime(data.start_datetime, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_datetime. Use YYYY-MM-DD HH:MM")

    jobs     = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    created  = []
    company  = profile.get("company", "")
    domain   = profile.get("domain", "")
    product  = profile.get("product", "")

    for i in range(data.days):
        schedule_dt = start_dt + datetime.timedelta(days=i)
        job_id = int(time.time() * 1000) + i
        job = {
            "id":           job_id,
            "datetime":     schedule_dt.strftime("%Y-%m-%d %H:%M"),
            "status":       "pending",
            "mode":         "ai_auto",
            "topic":        data.topic,
            "urn":          urn,
            "company":      company,
            "domain":       domain,
            "product":      product,
            "created_at":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        jobs.append(job)
        created.append(job_id)
        time.sleep(0.001)   # ensure unique ms timestamps

    _save_json(CONFIG["SCHEDULER_FILE"], jobs)
    save_job_db({"campaign": True, "days": data.days, "topic": data.topic})

    return {
        "status": "campaign_created",
        "days": data.days,
        "topic": data.topic,
        "start": data.start_datetime,
        "job_ids": created,
    }

# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.get("/jobs")
async def list_jobs(status: Optional[str] = None):
    jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    if status:
        jobs = [j for j in jobs if j.get("status", "").lower() == status.lower()]
    total   = len(jobs)
    pending = sum(1 for j in jobs if j.get("status") == "pending")
    posted  = sum(1 for j in jobs if j.get("status") == "posted")
    failed  = sum(1 for j in jobs if "failed" in j.get("status", ""))
    return {
        "stats": {"total": total, "pending": pending, "posted": posted, "failed": failed},
        "jobs": list(reversed(jobs)),
    }

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: int):
    jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
    before = len(jobs)
    jobs   = [j for j in jobs if j.get("id") != job_id]
    if len(jobs) == before:
        raise HTTPException(status_code=404, detail="Job not found")
    _save_json(CONFIG["SCHEDULER_FILE"], jobs)
    return {"status": "deleted", "job_id": job_id}

@app.delete("/jobs")
async def clear_all_jobs():
    _save_json(CONFIG["SCHEDULER_FILE"], [])
    return {"status": "all_jobs_cleared"}

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=CONFIG["PORT"], reload=False)
