"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         LinkedIn Studio PRO v3.0 — Domain-Aware AI Publishing Engine        ║
║   Auto Image Discovery · Gradient Layouts · Date Picker · Smart Scheduler   ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTALL:
  pip install customtkinter pillow requests google-generativeai tkcalendar

RUN:
  python linkedin_studio_pro.py

SCHEDULER-ONLY:
  python linkedin_studio_pro.py --scheduler-only
"""

import sys, os, json, time, threading, random, webbrowser
import http.server, socketserver, urllib.parse, base64, io
import argparse, datetime, textwrap, re, math
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox, filedialog
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    from tkcalendar import DateEntry
    HAS_TKCAL = True
except ImportError:
    HAS_TKCAL = False

# ═══════════════════════════════════════════════════════════════════════════════
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
import os

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
}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") 

os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
from supabase import create_client

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)
def save_job(job):

    supabase.table(
        "scheduled_posts"
    ).insert(job).execute()

def get_pending_jobs():

    result = supabase.table(
        "scheduled_posts"
    ).select("*").eq(
        "status",
        "pending"
    ).execute()

    return result.data
def update_job_status(
    job_id,
    status
):

    supabase.table(
        "scheduled_posts"
    ).update(
        {"status": status}
    ).eq(
        "id",
        job_id
    ).execute()

# ── Design Tokens ─────────────────────────────────────────────────────────────
BRAND = {
    "bg_deep":   "#060810",
    "bg_card":   "#0c0f1a",
    "bg_hover":  "#141824",
    "accent":    "#0ea5e9",
    "accent2":   "#38bdf8",
    "success":   "#22c55e",
    "warning":   "#fbbf24",
    "danger":    "#ef4444",
    "purple":    "#8b5cf6",
    "pink":      "#ec4899",
    "text_hi":   "#f0f6fc",
    "text_mid":  "#8b949e",
    "text_lo":   "#484f58",
    "border":    "#1e2433",
}

# Post type → domain-aware image search strategy
POST_TYPES = {
    "individual": [
        "💼 Thought Leadership",
        "✍️ Text Post",
        "🌟 Motivational",
        "📖 Story / Experience",
        "🔥 Hot Take / Opinion",
        "🎓 Career Milestone",
    ],
    "company": [
        "📢 Brand Announcement",
        "💼 Hiring / Recruiting",
        "🎉 Festival / Occasion",
        "🚀 Product / Feature Launch",
        "🏆 Company Milestone",
        "📅 Event / Workshop",
        "📰 Industry News",
        "❤️ Culture & Values",
    ],
}

TONES = [
    "Executive Authority",
    "Warm & Authentic",
    "Bold Marketing",
    "Data-Driven Analyst",
    "Storyteller",
    "Technical Expert",
    "Inspiring Coach",
]

# Visual mood → image query flavors
MOODS = {
    "🎯 Professional":     "professional corporate clean business modern",
    "🔥 Bold & Energetic": "bold dynamic energetic vibrant exciting",
    "💡 Innovative":       "innovative creative futuristic technology modern",
    "🎉 Celebratory":      "celebration success achievement festive joyful",
    "😌 Calm & Inspire":   "inspirational calm motivational serene peaceful",
    "🌍 Social Impact":    "community diversity purpose social impact",
    "😂 Fun & Relatable":  "fun relatable friendly warm approachable",
    "🔬 Research & Data":  "data research analytics science insights",
}

# Gradient color pairs for image overlays (name → (dark_bg, accent))
GRADIENTS = {
    "Navy Sapphire":      ("#0a192f", "#0ea5e9"),
    "Obsidian Emerald":   ("#020617", "#10b981"),
    "Deep Violet":        ("#1a0533", "#a855f7"),
    "Midnight Amber":     ("#1c1408", "#f59e0b"),
    "Charcoal Crimson":   ("#1a0000", "#ef4444"),
    "Dark Teal":          ("#042f2e", "#14b8a6"),
    "Slate Coral":        ("#1e1b2e", "#f97316"),
    "Graphite Sky":       ("#111827", "#38bdf8"),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE
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

# ═══════════════════════════════════════════════════════════════════════════════
#  LINKEDIN OAUTH
# ═══════════════════════════════════════════════════════════════════════════════

def linkedin_login_flow():
    auth_code = {}
    params = {
        "response_type": "code",
        "client_id":     CONFIG["LINKEDIN_CLIENT_ID"],
        "redirect_uri":  CONFIG["LINKEDIN_REDIRECT_URI"],
        "scope":         CONFIG["LINKEDIN_SCOPES"],
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)
    webbrowser.open(auth_url)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                auth_code["value"] = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                html = (
                    "<html><body style='background:#060810;display:flex;align-items:center;"
                    "justify-content:center;height:100vh;margin:0;font-family:sans-serif;'>"
                    "<div style='text-align:center;color:#f0f6fc;'>"
                    "<h2 style='font-size:60px;margin:0'>✓</h2>"
                    "<h2 style='color:#22c55e;margin:12px 0'>Authentication Successful!</h2>"
                    "<p style='color:#8b949e'>You may close this tab and return to LinkedIn Studio PRO</p>"
                    "</div></body></html>"
                )
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_response(400); self.end_headers()
        def log_message(self, *a): pass

    with socketserver.TCPServer(("", 8000), _Handler) as srv:
        srv.timeout = 120
        while "value" not in auth_code:
            srv.handle_request()

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type":    "authorization_code",
            "code":          auth_code["value"],
            "redirect_uri":  CONFIG["LINKEDIN_REDIRECT_URI"],
            "client_id":     CONFIG["LINKEDIN_CLIENT_ID"],
            "client_secret": CONFIG["LINKEDIN_CLIENT_SECRET"],
        }
    )
    token_data = resp.json()
    _save_json(CONFIG["TOKEN_FILE"], token_data)
    return token_data.get("access_token")

def linkedin_get_userinfo(access_token):
    r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
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
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    r = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20
    )
    return r.status_code, r.json()

def linkedin_post_with_image(access_token, urn, text, image_path):
    # Register upload
    reg_payload = {
        "registerUploadRequest": {
            "owner": f"urn:li:person:{urn}",
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "serviceRelationships": [
                {"identifier": "urn:li:userGeneratedContent", "relationshipType": "OWNER"}
            ]
        }
    }
    reg_r = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=reg_payload, timeout=15
    )
    reg_data = reg_r.json()
    upload_url = reg_data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn  = reg_data["value"]["asset"]

    with open(image_path, "rb") as img_f:
        requests.put(upload_url, data=img_f.read(),
                     headers={"Authorization": f"Bearer {access_token}"}, timeout=30)

    payload = {
        "author": f"urn:li:person:{urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [{"status": "READY", "media": asset_urn}]
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    r = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload, timeout=20
    )
    return r.status_code, r.json()

# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI AI
# ═══════════════════════════════════════════════════════════════════════════════

_gemini_model = None

def get_gemini():
    global _gemini_model
    if _gemini_model is None and HAS_GEMINI:
        genai.configure(api_key=CONFIG["GEMINI_API_KEY"])
        _gemini_model = genai.GenerativeModel(CONFIG["GEMINI_MODEL"])
    return _gemini_model

def gemini_generate(prompt, retries=3):
    m = get_gemini()
    if m is None:
        return "[Gemini not available — install google-generativeai]"
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
#  DOMAIN-AWARE IMAGE SEARCH (No generic search tab — auto-contextual)
# ═══════════════════════════════════════════════════════════════════════════════

def build_domain_image_queries(profile, post_type, mood, topic):
    """
    Builds 2–4 highly specific image queries based on:
    - Company domain/service (primary context)
    - Post type semantic meaning
    - Topic entered by user
    - Mood modifiers
    Returns list of query strings.
    """
    company  = profile.get("company", "")
    domain   = profile.get("domain", "")
    product  = profile.get("product", "")
    mood_w   = MOODS.get(mood, "professional corporate")

    # Strip emojis from post_type
    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()

    # Use Gemini to generate smart image queries if available
    if HAS_GEMINI and domain:
        prompt = f"""You are an expert visual content strategist for LinkedIn.

Company: {company}
Industry/Domain: {domain}
Product/Service: {product}
Post Type: {pt_clean}
Post Topic: {topic}
Visual Mood: {mood_w}

Generate exactly 3 short image search queries (5-8 words each) to find REAL stock photos
that are visually SPECIFIC to this company's domain and post type.

Rules:
- Query 1: Focus on the DOMAIN/INDUSTRY visual (e.g. "cloud server data center blue lights")
- Query 2: Focus on the PRODUCT/SERVICE visual (e.g. "software developer coding laptop dark")  
- Query 3: Focus on PEOPLE + domain context (e.g. "diverse team meeting office technology")
- Queries must be SPECIFIC to {domain} — not generic "business" images
- No company names, no text overlays

Return ONLY a JSON array of 3 strings. No explanation."""
        raw = gemini_generate(prompt)
        try:
            raw = re.sub(r"```json|```", "", raw).strip()
            queries = json.loads(raw)
            if isinstance(queries, list) and len(queries) >= 2:
                return queries[:4]
        except Exception:
            pass

    # Fallback: build queries from domain keywords
    domain_words = domain.lower().replace(",", " ").split()[:3]
    product_words = product.lower().replace(",", " ").split()[:2]
    mood_key = mood_w.split()[:2]

    post_visual_map = {
        "hiring":      f"{domain} team office workspace hiring people",
        "product":     f"{product} {domain} technology modern launch",
        "festival":    f"celebration festival india corporate office joy",
        "milestone":   f"{company} achievement success celebration {domain}",
        "event":       f"conference workshop seminar {domain} audience",
        "culture":     f"team culture diversity workplace {domain} people",
        "announcement":f"{domain} brand announcement modern corporate",
        "thought":     f"{domain} leadership executive professional modern",
        "news":        f"{domain} industry news media analytics",
    }

    base_key = next((k for k in post_visual_map if k in pt_clean.lower()), "thought")
    base_q   = post_visual_map[base_key]
    domain_q = f"{' '.join(domain_words)} professional modern {mood_w.split()[0]}"
    people_q = f"diverse business team {domain} collaboration"

    return [base_q, domain_q, people_q]


def fetch_images_for_post(profile, post_type, mood, topic, count=3):
    """Fetch 2–4 real images relevant to company domain + post type."""
    queries = build_domain_image_queries(profile, post_type, mood, topic)
    results = []
    per_q = max(1, math.ceil(count / len(queries)))

    for q in queries:
        if len(results) >= count:
            break
        imgs = _search_stock(q, per_q)
        results.extend(imgs)

    # Deduplicate by URL
    seen, unique = set(), []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    # Fill remainder with AI-generated if needed
    while len(unique) < count:
        enc  = urllib.parse.quote_plus(f"{queries[0]} professional high quality cinematic")
        seed = random.randint(1, 999999)
        unique.append({
            "url":    f"https://image.pollinations.ai/prompt/{enc}?width=1200&height=900&seed={seed}&nologo=true",
            "thumb":  f"https://image.pollinations.ai/prompt/{enc}?width=400&height=300&seed={seed}&nologo=true",
            "source": "AI Generated",
            "query":  queries[0],
        })

    return unique[:count]


def _search_stock(query, count):
    results = []

    # Pixabay
    if CONFIG["PIXABAY_API_KEY"] and len(results) < count:
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key":        CONFIG["PIXABAY_API_KEY"],
                    "q":          query,
                    "image_type": "photo",
                    "per_page":   min(count + 2, 10),
                    "safesearch": "true",
                    "order":      "popular",
                    "min_width":  800,
                    "orientation":"horizontal",
                },
                timeout=10
            )
            for hit in r.json().get("hits", [])[:count]:
                results.append({
                    "url":    hit["largeImageURL"],
                    "thumb":  hit["webformatURL"],
                    "source": "Pixabay",
                    "query":  query,
                })
        except Exception:
            pass

    # Pexels fallback
    if CONFIG["PEXELS_API_KEY"] and len(results) < count:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": CONFIG["PEXELS_API_KEY"]},
                params={"query": query, "per_page": count, "orientation": "landscape"},
                timeout=10,
            )
            for p in r.json().get("photos", []):
                if len(results) >= count:
                    break
                results.append({
                    "url":    p["src"]["large2x"],
                    "thumb":  p["src"]["medium"],
                    "source": "Pexels",
                    "query":  query,
                })
        except Exception:
            pass

    return results[:count]


def download_image(url, save_path):
    try:
        r = requests.get(url, timeout=45, stream=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return os.path.getsize(save_path) > 5000
    except Exception:
        pass
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#  AI TEXT GENERATION (Org-Aware)
# ═══════════════════════════════════════════════════════════════════════════════

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
    pt = post_type.lower()

    if "hiring" in pt:
        prompt = f"""{ctx}
Write a compelling LinkedIn HIRING post for: "{topic}".
- Opening hook about company culture/mission (punchy 1 line)
- 2 sentences about what makes this role exciting
- 3 must-have requirements using ✦ bullets
- Clear CTA (apply link placeholder)
- 5 relevant hashtags
- Voice: {"We're hiring (company)" if is_company else "I'm hiring"}
- Max 200 words. Start DIRECTLY with hook, NO preamble."""

    elif "festival" in pt or "occasion" in pt:
        prompt = f"""{ctx}
Write a warm LinkedIn festival/occasion greeting for: "{topic}".
- 2-3 heartfelt sentences connecting the occasion to company values
- Cultural sensitivity, positive inclusive language
- Tie back to organization mission naturally
- 3-4 hashtags. Max 120 words. NO preamble."""

    elif "product" in pt or "launch" in pt:
        prompt = f"""{ctx}
Write a LinkedIn product launch post for: "{topic}".
- Hook: 1 bold statement about the problem being solved
- What it is (1 sentence, simple)
- 3 key benefits using ✦ bullets
- CTA: try it / book a demo
- 5 hashtags. Max 200 words. NO preamble."""

    elif "milestone" in pt:
        prompt = f"""{ctx}
Write a LinkedIn company milestone post about: "{topic}".
- Open with the achievement/milestone (bold statement)
- Thank team/customers/community
- What this means for the future
- 3 ✦ highlights
- Forward-looking CTA
- 5 hashtags. Max 180 words. NO preamble."""

    elif "event" in pt or "workshop" in pt:
        prompt = f"""{ctx}
Write a LinkedIn event announcement for: "{topic}".
- Exciting hook about value attendees will get
- What / When / Where (concise)
- 3 ✦ reasons to attend
- RSVP CTA
- 5 hashtags. Max 180 words. NO preamble."""

    elif "thought" in pt:
        prompt = f"""{ctx}
Write a thought-leadership LinkedIn post on: "{topic}".
- Contrarian or insightful opening hook (makes people stop scrolling)
- Short paragraphs (1-2 sentences), mobile-optimized
- 3 ✦ key insights
- End with engaging question to drive comments
- 5 hashtags. Max 220 words. Personal voice. NO preamble."""

    elif "culture" in pt or "values" in pt:
        prompt = f"""{ctx}
Write a LinkedIn culture/values post about: "{topic}".
- Authentic human opening (not corporate-speak)
- Share a real example or story moment
- 3 ✦ values/principles highlighted
- Invite others to share experience
- 4 hashtags. Max 180 words. NO preamble."""

    elif "news" in pt:
        prompt = f"""{ctx}
Write a LinkedIn industry news commentary post on: "{topic}".
- Strong opening take / contrarian angle
- Explain why this matters to {domain}
- 3 ✦ implications for the industry
- Thought-provoking closing question
- 5 hashtags. Max 200 words. NO preamble."""

    else:
        prompt = f"""{ctx}
Write a professional LinkedIn post about: "{topic}".
- Powerful 1-line hook
- Short paragraphs (1-2 sentences)
- 3 ✦ value-packed points
- CTA question for comments
- 5 relevant hashtags
- {"Company voice (We/Our)" if is_company else "Personal voice (I/My)"}
- Max 200 words. NO preamble."""

    return gemini_generate(prompt)


def clean_for_linkedin(text):
    """
    Remove markdown **bold** syntax and reformat for LinkedIn:
    - Strips ** and * markers
    - CAPITALIZES key topic words and section headers
    - Preserves ✦ bullets, emojis, hashtags
    - Keeps clean line spacing
    """
    if not text:
        return text

    import re

    # Remove ```code blocks``` if any
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()

    # Extract words that were **bold** — we'll CAPITALIZE them instead
    bold_words = re.findall(r'\*\*(.+?)\*\*', text)

    # Replace **word** with UPPERCASE version
    def uppercase_bold(m):
        inner = m.group(1).strip()
        # If it's a short phrase (headline/keyword), fully uppercase
        if len(inner.split()) <= 5:
            return inner.upper()
        # Longer phrase — just remove the markers, keep as-is
        return inner

    text = re.sub(r'\*\*(.+?)\*\*', uppercase_bold, text)

    # Remove remaining single * italic markers
    text = re.sub(r'\*(.+?)\*', r'\1', text)

    # Remove # markdown headers (keep the text)
    text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)

    # Clean up excessive blank lines (max 1 blank line between paragraphs)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Ensure hashtags are on their own line at the end if they aren't
    lines  = text.strip().split('\n')
    body   = []
    tags   = []
    for line in lines:
        stripped = line.strip()
        # Line is purely hashtags
        if stripped and all(w.startswith('#') for w in stripped.split()):
            tags.append(stripped)
        else:
            body.append(line)

    if tags:
        text = '\n'.join(body).rstrip() + '\n\n' + ' '.join(tags)
    else:
        text = '\n'.join(body).strip()

    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  POSTER BUILDER — Multiple Gradient Layouts
# ═══════════════════════════════════════════════════════════════════════════════

def _load_font(size, bold=True):
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "calibrib.ttf", "segoeuib.ttf",
         "trebucbd.ttf", "verdanab.ttf"] if bold
        else ["arial.ttf", "Arial.ttf", "calibri.ttf", "segoeui.ttf",
              "trebuc.ttf", "verdana.ttf"]
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
    return tuple(int(c1[i] * (1-t) + c2[i] * t) for i in range(3))


def build_poster_layout_1(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    """Layout 1: Left-side gradient fade with centered top headline."""
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))

    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.75)
    bg = ImageEnhance.Contrast(bg).enhance(1.1)
    canvas.paste(bg.convert("RGBA"), (0, 0))

    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)

    # Left gradient overlay
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x in range(W):
        t = 1.0 - min(1.0, x / 650)
        alpha = int(220 * (t ** 0.7))
        col = _lerp_color(drk, (drk[0], drk[1]+5, drk[2]+8), 1-t)
        for y in range(H):
            overlay.putpixel((x, y), (col[0], col[1], col[2], alpha))
    canvas = Image.alpha_composite(canvas, overlay)

    # Accent bar
    accent_bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(accent_bar).rectangle([(0, 0), (6, H)], fill=(*acc, 255))
    canvas = Image.alpha_composite(canvas, accent_bar)

    draw = ImageDraw.Draw(canvas)

    # Org badge
    f_brand = _load_font(28, bold=True)
    f_title = _load_font(82 if len(headline) < 25 else 62, bold=True)
    f_sub   = _load_font(30, bold=False)
    f_tag   = _load_font(20, bold=False)

    draw.text((50, 50), org_name.upper(), font=f_brand, fill=(*acc, 255))
    draw.line([(50, 88), (300, 88)], fill=(*acc, 180), width=3)

    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    draw.rounded_rectangle((50, 96, 50+len(pt_clean)*12+24, 130),
                            radius=6, fill=(*acc, 30), outline=(*acc, 100))
    draw.text((62, 100), pt_clean.upper(), font=f_tag, fill=(*acc, 220))

    # Headline — wrapped
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
        draw.text((52, y+3), line, font=f_title, fill=(0, 0, 0, 130))
        draw.text((50, y), line, font=f_title, fill=(255, 255, 255, 255))
        y += int(f_title.size * 1.15)

    # Domain tag bottom
    if domain:
        tag = f"  {domain}  "
        tw = draw.textbbox((0,0), tag, font=f_sub)[2]
        draw.rounded_rectangle((50, H-80, 50+tw+24, H-44),
                                radius=10, fill=(*acc, 25), outline=(*acc, 80))
        draw.text((62, H-76), tag, font=f_sub, fill=(*acc, 220))

    return canvas.convert("RGB")


def build_poster_layout_2(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    """Layout 2: Bottom-heavy gradient with centered headline & decorative geometry."""
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))

    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.7)
    canvas.paste(bg.convert("RGBA"), (0, 0))

    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)

    # Bottom gradient
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(H):
        t = max(0, (y - H*0.3) / (H * 0.7))
        alpha = int(230 * min(1.0, t ** 0.65))
        col = _lerp_color((10, 12, 20), drk, t)
        ImageDraw.Draw(overlay).line([(0, y), (W, y)], fill=(*col, alpha))
    canvas = Image.alpha_composite(canvas, overlay)

    # Top vignette
    for y in range(int(H*0.35)):
        t = 1.0 - y / (H*0.35)
        alpha = int(160 * t ** 1.2)
        ImageDraw.Draw(canvas).line([(0, y), (W, y)], fill=(5, 8, 18, alpha))

    draw = ImageDraw.Draw(canvas)

    # Decorative circle
    cx, cy, cr = W - 120, 120, 80
    for r in range(cr, 0, -1):
        a = int(60 * (r / cr))
        draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=(*acc, a), width=1)
    draw.ellipse([(cx-8, cy-8), (cx+8, cy+8)], fill=(*acc, 200))

    f_brand  = _load_font(26, bold=True)
    f_title  = _load_font(90 if len(headline) < 20 else 68, bold=True)
    f_sub    = _load_font(32, bold=False)
    f_tag    = _load_font(20, bold=False)

    # Org name center
    org_w = draw.textbbox((0, 0), org_name.upper(), font=f_brand)[2]
    draw.text(((W - org_w)//2, 36), org_name.upper(), font=f_brand, fill=(*acc, 240))

    # Headline centered
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
        draw.text((x+3, y+3), line, font=f_title, fill=(0, 0, 0, 100))
        draw.text((x, y), line, font=f_title, fill=(255, 255, 255, 255))
        y += int(f_title.size * 1.12)

    # Accent line below headline
    draw.line([(W//2-100, H-78), (W//2+100, H-78)], fill=(*acc, 200), width=3)

    pt_clean = re.sub(r'[^\w\s/]', '', post_type).strip()
    tw = draw.textbbox((0, 0), pt_clean.upper(), font=f_tag)[2]
    draw.text(((W-tw)//2, H-62), pt_clean.upper(), font=f_tag, fill=(*acc, 200))

    return canvas.convert("RGB")


def build_poster_layout_3(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex):
    """Layout 3: Split diagonal gradient with right-aligned bold text."""
    W, H = 1200, 900
    canvas = Image.new("RGBA", (W, H))

    bg = bg_img.resize((W, H), Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.65)
    bg = ImageEnhance.Color(bg).enhance(1.15)
    canvas.paste(bg.convert("RGBA"), (0, 0))

    acc = _hex_to_rgb(accent_hex)
    drk = _hex_to_rgb(dark_hex)

    # Diagonal gradient from top-right to bottom-left
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(H):
        for x in range(W):
            t = ((W - x)/W * 0.6 + y/H * 0.4)
            alpha = int(210 * min(1.0, t ** 0.8))
            col = _lerp_color(drk, (5, 8, 18), t)
            overlay.putpixel((x, y), (*col, alpha))
    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)

    f_brand = _load_font(26, bold=True)
    f_title = _load_font(76 if len(headline) < 28 else 56, bold=True)
    f_sub   = _load_font(28, bold=False)
    f_tag   = _load_font(19, bold=False)

    # Right-side vertical accent bar
    draw.rectangle([(W-8, 0), (W, H)], fill=(*acc, 200))

    # Org name — right aligned
    org_w = draw.textbbox((0, 0), org_name.upper(), font=f_brand)[2]
    draw.text((W - org_w - 30, 42), org_name.upper(), font=f_brand, fill=(*acc, 240))
    draw.line([(W - org_w - 30, 80), (W-30, 80)], fill=(*acc, 160), width=2)

    # Headline — right aligned
    words = headline.upper().split()
    lines, curr = [], []
    for w in words:
        curr.append(w)
        if draw.textbbox((0, 0), " ".join(curr), font=f_title)[2] > 720:
            curr.pop()
            if curr: lines.append(" ".join(curr))
            curr = [w]
    lines.append(" ".join(curr))
    y = H//2 - (len(lines) * int(f_title.size * 1.1))//2
    for line in lines[:3]:
        lw = draw.textbbox((0, 0), line, font=f_title)[2]
        x  = W - lw - 30
        draw.text((x+3, y+3), line, font=f_title, fill=(0, 0, 0, 100))
        draw.text((x, y), line, font=f_title, fill=(255, 255, 255, 255))
        y += int(f_title.size * 1.1)

    # Domain + post type badge bottom-right
    if domain:
        tag = f"  {domain}  ·  {re.sub(r'[^\\w\\s/]', '', post_type).strip()}  "
        tw = draw.textbbox((0, 0), tag, font=f_sub)[2]
        draw.rounded_rectangle((W - tw - 60, H-72, W-30, H-40),
                                radius=8, fill=(*acc, 20), outline=(*acc, 70))
        draw.text((W - tw - 48, H-68), tag, font=f_sub, fill=(*acc, 200))

    return canvas.convert("RGB")


LAYOUT_BUILDERS = [
    build_poster_layout_1,
    build_poster_layout_2,
    build_poster_layout_3,
]


def build_posters_for_images(images_data, headline, profile, post_type, gradient_name, topic):
    """
    Downloads images and creates poster for each with unique layout.
    Returns list of (poster_path, source_label).
    """
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
            # Try pollinations as fallback
            enc  = urllib.parse.quote_plus(item.get("query", "business professional"))
            seed = random.randint(1, 999999)
            url2 = f"https://image.pollinations.ai/prompt/{enc}?width=1200&height=900&seed={seed}&nologo=true"
            ok   = download_image(url2, raw_path)
            item["source"] = "AI Generated"
        if not ok:
            continue

        try:
            bg_img   = Image.open(raw_path).convert("RGB")
            layout_fn = LAYOUT_BUILDERS[i % len(LAYOUT_BUILDERS)]
            poster   = layout_fn(bg_img, headline, org_name, post_type, domain, accent_hex, dark_hex)
            out_path = os.path.join(CONFIG["CACHE_DIR"], f"poster_{i}_{int(time.time())}.png")
            poster.save(out_path, "PNG")
            posters.append((out_path, item.get("source", "Stock Photo")))
        except Exception as e:
            print(f"Poster build error for image {i}: {e}")
            continue

    return posters

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════

def run_scheduler_daemon():
    """Background scheduler — reads pending jobs from Supabase (or local JSON fallback)
    and posts them to LinkedIn at the scheduled time. Generates domain-aware poster
    images for every post, just like the compose page does."""
    print("Scheduler daemon started. Checking every 30 seconds...")
    while True:
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            tokens  = _load_json(CONFIG["TOKEN_FILE"]) or {}
            token   = tokens.get("access_token")

            pending = get_pending_jobs()

            for job in pending:
                job_dt = job.get("datetime", "")
                if not job_dt or job_dt > now_str:
                    continue

                job_id = job.get("id")

                if not token or not job.get("urn"):
                    update_job_status(job_id, "failed (no auth)")
                    continue

                try:
                    # Build a fake profile dict from job fields
                    job_profile = {
                        "company": job.get("company", ""),
                        "domain":  job.get("domain", ""),
                        "product": job.get("product", ""),
                        "name":    job.get("company", ""),
                        "user_type": "company",
                    }

                    # ── AI AUTO CAMPAIGN MODE ────────────────────────────
                    if job.get("mode") == "ai_auto":
                        topic      = job.get("topic", "industry trends")
                        post_type  = job.get("campaign_mode", "💼 Thought Leadership")
                        mood       = "🎯 Professional"

                        prompt = f"""
Company: {job.get('company', '')}
Domain: {job.get('domain', '')}
Service: {job.get('product', '')}
Topic: {topic}

Write a professional LinkedIn thought-leadership post.
Requirements:
- Human sounding, industry focused
- Powerful 1-line hook (NO ** markdown)
- Short paragraphs (1-2 sentences each)
- 3 key insights using ✦ bullets
- End with engaging question for comments
- 5 relevant hashtags on last line
- 200-300 words. NO ** markdown. NO preamble."""

                        raw_text = gemini_generate(prompt).strip()
                        ai_post  = clean_for_linkedin(raw_text)

                    # ── NORMAL SCHEDULED POST ────────────────────────────
                    else:
                        topic     = job.get("topic", job.get("text", "")[:60])
                        post_type = job.get("post_type", "💼 Thought Leadership")
                        mood      = "🎯 Professional"
                        raw_text  = job.get("text", "")
                        ai_post   = clean_for_linkedin(raw_text)

                    # ── GENERATE DOMAIN-AWARE POSTER IMAGE ───────────────
                    poster_path = None
                    try:
                        images = fetch_images_for_post(
                            job_profile, post_type, mood, topic, count=1
                        )
                        if images:
                            # Extract a short headline from the post text
                            first_line = ai_post.split('\n')[0].strip()
                            headline   = first_line[:60] if first_line else topic[:60]

                            posters = build_posters_for_images(
                                images,
                                headline,
                                job_profile,
                                post_type,
                                list(GRADIENTS.keys())[0],  # default gradient
                                topic,
                            )
                            if posters:
                                poster_path = posters[0][0]
                                print(f"Job {job_id}: poster generated → {poster_path}")
                    except Exception as img_err:
                        print(f"Job {job_id}: image generation failed ({img_err}), posting text only")

                    # ── POST TO LINKEDIN ─────────────────────────────────
                    if poster_path and os.path.exists(poster_path):
                        st, _ = linkedin_post_with_image(
                            token, job["urn"], ai_post, poster_path
                        )
                    else:
                        st, _ = linkedin_post_text(token, job["urn"], ai_post)

                    new_status = "posted" if st in (200, 201) else f"failed ({st})"

                except Exception as e:
                    new_status = f"failed ({e})"

                update_job_status(job_id, new_status)
                print(f"Job {job_id}: {new_status}")

        except Exception as e:
            print(f"Scheduler Error: {e}")

        time.sleep(30)
# ═══════════════════════════════════════════════════════════════════════════════
#  DATE PICKER WIDGET (fallback if tkcalendar not installed)
# ═══════════════════════════════════════════════════════════════════════════════

class SimpleDateTimePicker(ctk.CTkFrame):
    """Compact date+time picker using spinboxes — no external deps."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        now = datetime.datetime.now() + datetime.timedelta(hours=1)

        ctk.CTkLabel(self, text="📅", font=("Helvetica", 14)).pack(side="left", padx=(0, 4))

        self.year_var  = tk.StringVar(value=str(now.year))
        self.month_var = tk.StringVar(value=f"{now.month:02d}")
        self.day_var   = tk.StringVar(value=f"{now.day:02d}")
        self.hour_var  = tk.StringVar(value=f"{now.hour:02d}")
        self.min_var   = tk.StringVar(value=f"{now.minute:02d}")

        style_kw = dict(height=36, font=("Helvetica", 12),
                        fg_color=BRAND["bg_hover"], border_color=BRAND["border"])

        ctk.CTkEntry(self, textvariable=self.year_var,  width=64, **style_kw).pack(side="left", padx=2)
        ctk.CTkLabel(self, text="-", text_color=BRAND["text_mid"]).pack(side="left")
        ctk.CTkEntry(self, textvariable=self.month_var, width=46, **style_kw).pack(side="left", padx=2)
        ctk.CTkLabel(self, text="-", text_color=BRAND["text_mid"]).pack(side="left")
        ctk.CTkEntry(self, textvariable=self.day_var,   width=46, **style_kw).pack(side="left", padx=2)
        ctk.CTkLabel(self, text="  ⏰", text_color=BRAND["text_mid"]).pack(side="left")
        ctk.CTkEntry(self, textvariable=self.hour_var,  width=46, **style_kw).pack(side="left", padx=2)
        ctk.CTkLabel(self, text=":", text_color=BRAND["text_mid"]).pack(side="left")
        ctk.CTkEntry(self, textvariable=self.min_var,   width=46, **style_kw).pack(side="left", padx=2)

    def get_datetime_str(self):
        return (f"{self.year_var.get()}-{self.month_var.get()}-{self.day_var.get()} "
                f"{self.hour_var.get()}:{self.min_var.get()}")

    def validate(self):
        try:
            datetime.datetime.strptime(self.get_datetime_str(), "%Y-%m-%d %H:%M")
            return True
        except ValueError:
            return False

# ═══════════════════════════════════════════════════════════════════════════════
#  POSTER PREVIEW CARD
# ═══════════════════════════════════════════════════════════════════════════════

class PosterCard(ctk.CTkFrame):
    """Clickable poster preview card."""
    def __init__(self, parent, poster_path, source_label, index, on_select, **kwargs):
        super().__init__(parent, fg_color=BRAND["bg_card"],
                         corner_radius=14, border_width=2,
                         border_color=BRAND["border"], **kwargs)
        self.poster_path = poster_path
        self.index = index
        self.on_select = on_select
        self.selected = False

        # Thumbnail
        try:
            img = Image.open(poster_path).convert("RGB")
            img.thumbnail((320, 240), Image.Resampling.LANCZOS)
            self._ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                          size=(img.width, img.height))
            lbl = ctk.CTkLabel(self, image=self._ctk_img, text="")
            lbl.pack(padx=8, pady=(8, 4))
            lbl.bind("<Button-1>", lambda e: self._click())
        except Exception:
            ctk.CTkLabel(self, text="⚠️ Preview Error",
                         text_color=BRAND["danger"]).pack(pady=20)

        ctk.CTkLabel(self, text=f"Layout {index+1}  ·  {source_label}",
                     font=("Helvetica", 11), text_color=BRAND["text_mid"]).pack()

        self.sel_btn = ctk.CTkButton(
            self, text="Select This Poster", height=34,
            font=("Helvetica", 12, "bold"),
            fg_color=BRAND["accent"], hover_color="#0284c7",
            command=self._click
        )
        self.sel_btn.pack(fill="x", padx=8, pady=(4, 8))

    def _click(self):
        self.on_select(self.index, self.poster_path)

    def set_selected(self, val):
        self.selected = val
        if val:
            self.configure(border_color=BRAND["accent"], border_width=3)
            self.sel_btn.configure(text="✓ Selected", fg_color=BRAND["success"])
        else:
            self.configure(border_color=BRAND["border"], border_width=2)
            self.sel_btn.configure(text="Select This Poster", fg_color=BRAND["accent"])

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class App:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.geometry("1500x920")
        self.root.minsize(1200, 800)
        self.root.title("LinkedIn Studio PRO v3.0 — AI Publishing Engine")
        self.root.configure(fg_color=BRAND["bg_deep"])

        self.active_page = None
        self.token       = get_token()
        self.profile     = get_profile()
        self.linkedin_urn = self.profile.get("urn")
        self.linkedin_name = self.profile.get("name", "")
        self.user_type   = self.profile.get("user_type")

        # Generation state
        self.generated_text   = ""
        self.poster_cards     = []      # list of PosterCard widgets
        self.poster_paths     = []      # list of poster file paths
        self.selected_poster  = None    # currently selected poster path
        self.selected_poster_idx = -1
        self.generation_complete = False

        self._build_root_layout()
        self._build_all_pages()

        threading.Thread(target=run_scheduler_daemon, daemon=True).start()

        if self.token and self.profile.get("urn"):
            self._on_logged_in(auto=True)
        else:
            self._show_page("login")

    # ── Root Layout ──────────────────────────────────────────────────────────
    def _schedule_ai_campaign(self):
        try:
            days = int(self.days_entry.get())
        except:
            messagebox.showwarning("Invalid", "Enter valid number of days")
            return

        if days < 1:
            return

        jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []

        company = self.profile.get("company", "")
        domain  = self.profile.get("domain", "")
        product = self.profile.get("product", "")

        start_time = self.compose_dt_picker.get_datetime()

        for i in range(days):

            schedule_dt = start_time + datetime.timedelta(days=i)

            topic_prompt = f"""
            Company: {company}
            Domain: {domain}
            Product: {product}

            Generate ONE unique LinkedIn topic.
            Day {i+1} of {days}

            Return topic only.
            """

            topic = gemini_generate(topic_prompt).strip()

            jobs.append({
                "id": int(time.time()*1000) + i,
                "datetime": schedule_dt.strftime("%Y-%m-%d %H:%M"),
                "status": "pending",
                "mode": "ai_auto",
                "topic": topic,
                "urn": self.linkedin_urn,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            })

        _save_json(CONFIG["SCHEDULER_FILE"], jobs)

        messagebox.showinfo(
            "Success",
            f"{days} AI posts scheduled successfully."
        )

        self._refresh_queue()
    def _build_root_layout(self):
        self.sidebar = ctk.CTkFrame(self.root, width=270,
                                     fg_color=BRAND["bg_card"],
                                     corner_radius=0,
                                     border_width=1, border_color=BRAND["border"])
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo block
        hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        hdr.pack(fill="x", padx=22, pady=(28, 16))
        ctk.CTkLabel(hdr, text="LinkedIn Studio",
                     font=("Helvetica", 20, "bold"),
                     text_color=BRAND["text_hi"]).pack(anchor="w")
        ctk.CTkLabel(hdr, text="PRO · v3.0 AI ENGINE",
                     font=("Helvetica", 9, "bold"),
                     text_color=BRAND["accent"]).pack(anchor="w", pady=2)

        # Separator
        ctk.CTkFrame(self.sidebar, height=1,
                     fg_color=BRAND["border"]).pack(fill="x", padx=16, pady=4)

        # Profile status
        self.profile_box = ctk.CTkFrame(self.sidebar,
                                         fg_color=BRAND["bg_hover"],
                                         corner_radius=12,
                                         border_width=1, border_color=BRAND["border"])
        self.profile_box.pack(fill="x", padx=14, pady=10)
        self.status_dot = ctk.CTkLabel(self.profile_box,
                                        text="● Not Connected",
                                        font=("Helvetica", 12, "bold"),
                                        text_color=BRAND["danger"])
        self.status_dot.pack(anchor="w", padx=14, pady=(10, 2))
        self.user_lbl = ctk.CTkLabel(self.profile_box, text="",
                                      font=("Helvetica", 12),
                                      text_color=BRAND["text_mid"])
        self.user_lbl.pack(anchor="w", padx=14, pady=(0, 10))

        # Nav buttons
        self.nav_btns = {}
        navs = [
            ("compose",   "📝  Compose & Generate"),
            ("scheduler", "📅  Content Scheduler"),
            ("settings",  "⚙️  Profile Settings"),
        ]
        ctk.CTkLabel(self.sidebar, text="NAVIGATION",
                     font=("Helvetica", 9, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w", padx=22, pady=(16, 4))
        for key, text in navs:
            btn = ctk.CTkButton(
                self.sidebar, text=text,
                font=("Helvetica", 13, "bold"),
                height=44, anchor="w",
                fg_color="transparent",
                text_color=BRAND["text_mid"],
                hover_color=BRAND["bg_hover"],
                corner_radius=10,
                command=lambda k=key: self._navigate(k)
            )
            btn.pack(fill="x", padx=12, pady=2)
            self.nav_btns[key] = btn

        # LinkedIn sign-in btn
        self.connect_btn = ctk.CTkButton(
            self.sidebar,
            text="🔗  Sign in with LinkedIn",
            height=44, font=("Helvetica", 13, "bold"),
            fg_color="#0a66c2", hover_color="#004182",
            corner_radius=10, command=self._start_login
        )
        self.connect_btn.pack(side="bottom", fill="x", padx=14, pady=14)

        # Content area
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(side="right", fill="both", expand=True)

    def _build_all_pages(self):
        self.pages = {}
        for key in ["login", "onboard", "compose", "scheduler", "settings"]:
            f = ctk.CTkScrollableFrame(
                self.content, fg_color="transparent",
                scrollbar_button_color=BRAND["border"],
                scrollbar_button_hover_color=BRAND["bg_hover"]
            )
            self.pages[key] = f
        self._build_login_page()
        self._build_onboard_page()
        self._build_compose_page()
        self._build_scheduler_page()
        self._build_settings_page()

    def _show_page(self, key):
        if self.active_page:
            self.active_page.pack_forget()
        page = self.pages.get(key)
        if page:
            page.pack(fill="both", expand=True)
            self.active_page = page
        for k, btn in self.nav_btns.items():
            btn.configure(
                fg_color=BRAND["bg_hover"] if k == key else "transparent",
                text_color=BRAND["accent2"] if k == key else BRAND["text_mid"]
            )

    def _navigate(self, key):
        if key in ("compose", "scheduler") and not self.token:
            messagebox.showwarning("Login Required", "Please sign in with LinkedIn first.")
            return
        self._show_page(key)

    # ── Login Page ───────────────────────────────────────────────────────────

    def _build_login_page(self):
        p = self.pages["login"]
        card = ctk.CTkFrame(p, fg_color=BRAND["bg_card"],
                             corner_radius=24, border_width=1,
                             border_color=BRAND["border"])
        card.pack(expand=True, padx=200, pady=60, fill="both")

        ctk.CTkFrame(card, height=4, fg_color=BRAND["accent"],
                     corner_radius=0).pack(fill="x")
        ctk.CTkLabel(card, text="⚡",
                     font=("Helvetica", 60)).pack(pady=(44, 8))
        ctk.CTkLabel(card, text="LinkedIn Studio PRO",
                     font=("Helvetica", 28, "bold"),
                     text_color=BRAND["text_hi"]).pack()
        ctk.CTkLabel(card,
                     text="Domain-aware AI content engine for brands & professionals",
                     font=("Helvetica", 14),
                     text_color=BRAND["text_mid"]).pack(pady=6)

        ctk.CTkButton(card,
                      text="🚀  Sign in with LinkedIn",
                      height=52, font=("Helvetica", 15, "bold"),
                      fg_color="#0a66c2", hover_color="#004182",
                      corner_radius=14, command=self._start_login
                      ).pack(pady=44, padx=120, fill="x")

    # ── Onboard Page ─────────────────────────────────────────────────────────

    def _build_onboard_page(self):
        p = self.pages["onboard"]
        card = ctk.CTkFrame(p, fg_color=BRAND["bg_card"],
                             corner_radius=24, border_width=1,
                             border_color=BRAND["border"])
        card.pack(expand=True, padx=100, pady=40, fill="both")

        ctk.CTkLabel(card, text="🏢  Brand Profile Setup",
                     font=("Helvetica", 22, "bold"),
                     text_color=BRAND["text_hi"]).pack(pady=24)

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=60)

        self.ob_type_var = ctk.StringVar(value="company")
        r_row = ctk.CTkFrame(form, fg_color="transparent")
        r_row.pack(fill="x", pady=12)
        ctk.CTkRadioButton(r_row, text="Company / Brand Page",
                           variable=self.ob_type_var, value="company",
                           font=("Helvetica", 13)).pack(side="left", padx=20)
        ctk.CTkRadioButton(r_row, text="Individual Professional",
                           variable=self.ob_type_var, value="individual",
                           font=("Helvetica", 13)).pack(side="left", padx=20)

        self.ob_vars = {}
        fields = [
            ("name",    "👤  Your Name / Profile Title",      "Your Full Name"),
            ("company", "🏢  Organization / Brand Name",      "E.g. TechCorp Solutions"),
            ("domain",  "🌐  Industry / Domain",              "E.g. Cloud Computing, Fintech, Healthcare"),
            ("product", "📦  Product / Service",              "E.g. SaaS analytics platform, Consulting"),
        ]
        for key, label, ph in fields:
            ctk.CTkLabel(form, text=label,
                         font=("Helvetica", 12, "bold"),
                         text_color=BRAND["text_mid"],
                         anchor="w").pack(fill="x", pady=(10, 2))
            var = ctk.StringVar(value=self.profile.get(key, ""))
            ctk.CTkEntry(form, textvariable=var, height=48,
                         placeholder_text=ph, font=("Helvetica", 13),
                         fg_color=BRAND["bg_hover"],
                         border_color=BRAND["border"]).pack(fill="x", pady=(0, 4))
            self.ob_vars[key] = var

        ctk.CTkButton(card,
                      text="✅  Save & Continue",
                      height=54, font=("Helvetica", 15, "bold"),
                      fg_color=BRAND["accent"], hover_color="#0284c7",
                      corner_radius=12, command=self._save_onboard
                      ).pack(padx=60, pady=(20, 40), fill="x")

    def _save_onboard(self):
        prof = {
            "urn":       self.linkedin_urn,
            "name":      self.ob_vars["name"].get().strip() or self.linkedin_name,
            "company":   self.ob_vars["company"].get().strip(),
            "domain":    self.ob_vars["domain"].get().strip(),
            "product":   self.ob_vars["product"].get().strip(),
            "user_type": self.ob_type_var.get(),
        }
        if not prof["company"] or not prof["domain"]:
            messagebox.showwarning("Required", "Please fill in Company Name and Domain.")
            return
        self.profile   = prof
        self.user_type = prof["user_type"]
        save_profile(prof)
        self._on_logged_in(auto=False)

    # ── COMPOSE PAGE ─────────────────────────────────────────────────────────

    def _build_compose_page(self):
        p = self.pages["compose"]

        # ── TOP CONTROL PANEL ────────────────────────────────────────────────
        ctrl_card = ctk.CTkFrame(p, fg_color=BRAND["bg_card"],
                                  corner_radius=18, border_width=1,
                                  border_color=BRAND["border"])
        ctrl_card.pack(fill="x", padx=20, pady=(20, 12))

        # Title
        title_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        title_row.pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(title_row, text="📝  AI Compose Studio",
                     font=("Helvetica", 16, "bold"),
                     text_color=BRAND["accent2"]).pack(side="left")
        ctk.CTkLabel(title_row,
                     text="Select type → enter topic → AI finds images & writes post",
                     font=("Helvetica", 12),
                     text_color=BRAND["text_mid"]).pack(side="left", padx=14)

        # Controls row 1
        row1 = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=6)

        # Post Type
        col1 = ctk.CTkFrame(row1, fg_color="transparent")
        col1.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(col1, text="POST TYPE",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        utype  = self.user_type or "company"
        pt_vals = POST_TYPES.get(utype, POST_TYPES["company"])
        self.post_type_var = ctk.StringVar(value=pt_vals[0])
        self.post_type_menu = ctk.CTkOptionMenu(
            col1, variable=self.post_type_var, values=pt_vals,
            height=44, font=("Helvetica", 13),
            fg_color=BRAND["bg_hover"], button_color=BRAND["border"],
            dropdown_fg_color=BRAND["bg_card"]
        )
        self.post_type_menu.pack(fill="x", pady=2)

        # Tone
        col2 = ctk.CTkFrame(row1, fg_color="transparent")
        col2.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(col2, text="VOICE & TONE",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        self.tone_var = ctk.StringVar(value=TONES[0])
        ctk.CTkOptionMenu(col2, variable=self.tone_var, values=TONES,
                          height=44, font=("Helvetica", 13),
                          fg_color=BRAND["bg_hover"], button_color=BRAND["border"],
                          dropdown_fg_color=BRAND["bg_card"]
                          ).pack(fill="x", pady=2)

        # Mood
        col3 = ctk.CTkFrame(row1, fg_color="transparent")
        col3.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(col3, text="VISUAL MOOD",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        self.mood_var = ctk.StringVar(value="🎯 Professional")
        ctk.CTkOptionMenu(col3, variable=self.mood_var,
                          values=list(MOODS.keys()),
                          height=44, font=("Helvetica", 13),
                          fg_color=BRAND["bg_hover"], button_color=BRAND["border"],
                          dropdown_fg_color=BRAND["bg_card"]
                          ).pack(fill="x", pady=2)

        # Gradient
        col4 = ctk.CTkFrame(row1, fg_color="transparent")
        col4.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(col4, text="GRADIENT STYLE",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        self.gradient_var = ctk.StringVar(value=list(GRADIENTS.keys())[0])
        ctk.CTkOptionMenu(col4, variable=self.gradient_var,
                          values=list(GRADIENTS.keys()),
                          height=44, font=("Helvetica", 13),
                          fg_color=BRAND["bg_hover"], button_color=BRAND["border"],
                          dropdown_fg_color=BRAND["bg_card"]
                          ).pack(fill="x", pady=2)

        # Controls row 2
        row2 = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(6, 8))

        # Topic input
        topic_col = ctk.CTkFrame(row2, fg_color="transparent")
        topic_col.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(topic_col, text="TOPIC / FOCUS",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        self.topic_in = ctk.CTkEntry(
            topic_col, height=44,
            placeholder_text="What is this post about? E.g. 'We're hiring a Senior DevOps Engineer'",
            font=("Helvetica", 13),
            fg_color=BRAND["bg_hover"], border_color=BRAND["border"]
        )
        self.topic_in.pack(fill="x", pady=2)

        # Headline input
        hl_col = ctk.CTkFrame(row2, fg_color="transparent")
        hl_col.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(hl_col, text="POSTER HEADLINE",
                     font=("Helvetica", 10, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w")
        self.headline_in = ctk.CTkEntry(
            hl_col, height=44,
            placeholder_text="Bold headline text for the poster overlay",
            font=("Helvetica", 13),
            fg_color=BRAND["bg_hover"], border_color=BRAND["border"]
        )
        self.headline_in.pack(fill="x", pady=2)

        # Generate button
        self.gen_btn = ctk.CTkButton(
            row2, text="⚡  Generate",
            height=44, width=160,
            font=("Helvetica", 14, "bold"),
            fg_color=BRAND["accent"], hover_color="#0284c7",
            corner_radius=12, command=self._trigger_generation
        )
        self.gen_btn.pack(side="left", pady=(18, 0))

        # ── PROGRESS BAR ─────────────────────────────────────────────────────
        self.progress_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=20, pady=4)
        self.progress_lbl = ctk.CTkLabel(
            self.progress_frame, text="",
            font=("Helvetica", 12), text_color=BRAND["accent"]
        )
        self.progress_lbl.pack(anchor="w")
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame, height=6,
            fg_color=BRAND["border"], progress_color=BRAND["accent"]
        )

        # ── OUTPUT AREA ───────────────────────────────────────────────────────
        output_row = ctk.CTkFrame(p, fg_color="transparent")
        output_row.pack(fill="both", expand=True, padx=20, pady=8)

        # Left: Text output
        text_card = ctk.CTkFrame(output_row, fg_color=BRAND["bg_card"],
                                  corner_radius=16, border_width=1,
                                  border_color=BRAND["border"])
        text_card.pack(side="left", fill="both", expand=True, padx=(0, 10))

        text_hdr = ctk.CTkFrame(text_card, fg_color="transparent")
        text_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(text_hdr, text="📝  Generated Post Text",
                     font=("Helvetica", 13, "bold"),
                     text_color=BRAND["text_hi"]).pack(side="left")

        btn_row = ctk.CTkFrame(text_hdr, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="📋 Copy", height=30, width=80,
                      font=("Helvetica", 11),
                      fg_color=BRAND["bg_hover"], hover_color=BRAND["border"],
                      command=self._copy_text).pack(side="left", padx=4)
        self.edit_btn = ctk.CTkButton(
            btn_row, text="✏️ Edit", height=30, width=80,
            font=("Helvetica", 11),
            fg_color=BRAND["bg_hover"], hover_color=BRAND["border"],
            command=self._toggle_edit
        )
        self.edit_btn.pack(side="left", padx=4)

        self.txt_out = ctk.CTkTextbox(
            text_card, font=("Segoe UI", 13),
            fg_color="transparent", text_color=BRAND["text_hi"],
            wrap="word", height=300
        )
        self.txt_out.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.txt_out.configure(state="disabled")

        # Right: Image count selector + Post Now + Schedule
        action_card = ctk.CTkFrame(output_row, fg_color=BRAND["bg_card"],
                                    corner_radius=16, border_width=1,
                                    border_color=BRAND["border"], width=320)
        action_card.pack(side="right", fill="both", expand=False)
        action_card.pack_propagate(True)

        ctk.CTkLabel(action_card, text="🚀  Publish Controls",
                     font=("Helvetica", 13, "bold"),
                     text_color=BRAND["text_hi"]).pack(anchor="w", padx=18, pady=(14, 6))

        ctk.CTkLabel(action_card, text="NUMBER OF POSTER VARIANTS",
                     font=("Helvetica", 9, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w", padx=18, pady=(8, 2))
        self.img_count_var = ctk.StringVar(value="3")
        ctk.CTkOptionMenu(
            action_card, variable=self.img_count_var,
            values=["2", "3", "4"],
            height=40, font=("Helvetica", 13),
            fg_color=BRAND["bg_hover"], button_color=BRAND["border"],
            dropdown_fg_color=BRAND["bg_card"]
        ).pack(fill="x", padx=18, pady=4)

        # Selected poster display
        ctk.CTkLabel(action_card, text="SELECTED POSTER",
                     font=("Helvetica", 9, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w", padx=18, pady=(14, 2))
        self.selected_lbl = ctk.CTkLabel(
            action_card, text="None selected",
            font=("Helvetica", 12), text_color=BRAND["text_mid"]
        )
        self.selected_lbl.pack(anchor="w", padx=18)
        self.selected_preview = ctk.CTkLabel(action_card, text="")
        self.selected_preview.pack(padx=18, pady=4)

        # Save poster btn
        ctk.CTkButton(action_card, text="💾  Save Poster",
                      height=38, font=("Helvetica", 12, "bold"),
                      fg_color=BRAND["bg_hover"], hover_color=BRAND["border"],
                      command=self._save_poster).pack(fill="x", padx=18, pady=(6, 4))

        # Post Now btn
        self.post_now_btn = ctk.CTkButton(
            action_card, text="🚀  Post to LinkedIn Now",
            height=50, font=("Helvetica", 13, "bold"),
            fg_color=BRAND["success"], hover_color="#16a34a",
            corner_radius=12, command=self._post_now
        )
        self.post_now_btn.pack(fill="x", padx=18, pady=(10, 4))


      
        # Scheduler
        ctk.CTkFrame(action_card, height=1,
                     fg_color=BRAND["border"]).pack(fill="x", padx=18, pady=10)
        ctk.CTkLabel(action_card, text="SCHEDULE FOR LATER",
                     font=("Helvetica", 9, "bold"),
                     text_color=BRAND["text_lo"]).pack(anchor="w", padx=18)

        self.compose_dt_picker = SimpleDateTimePicker(action_card)
        self.compose_dt_picker.pack(fill="x", padx=18, pady=6)

        # ==========================================
        # AUTO CAMPAIGN SETTINGS
        # ==========================================

        ctk.CTkLabel(
            action_card,
            text="AUTO CONTENT CAMPAIGN",
            font=("Helvetica", 9, "bold"),
            text_color=BRAND["text_lo"]
        ).pack(anchor="w", padx=18, pady=(12,2))

        self.days_entry = ctk.CTkEntry(
            action_card,
            placeholder_text="How many days? e.g. 30"
        )
        self.days_entry.pack(fill="x", padx=18, pady=4)

        self.campaign_mode = ctk.StringVar(value="ai")

        ctk.CTkRadioButton(
            action_card,
            text="AI Professional Topics",
            variable=self.campaign_mode,
            value="ai"
        ).pack(anchor="w", padx=18)

        ctk.CTkRadioButton(
            action_card,
            text="Use My Manual Topic",
            variable=self.campaign_mode,
            value="manual"
        ).pack(anchor="w", padx=18)

        ctk.CTkButton(
            action_card,
            text="🤖 Generate & Schedule Campaign",
            height=42,
            fg_color=BRAND["accent"],
            command=self._schedule_ai_campaign
        ).pack(fill="x", padx=18, pady=(8,10))

        # ==========================================
        # NORMAL ONE-TIME SCHEDULE
        # ==========================================

        ctk.CTkButton(
            action_card,
            text="📅 Add To Schedule Queue",
            height=42,
            font=("Helvetica", 12, "bold"),
            fg_color=BRAND["purple"],
            hover_color="#7c3aed",
            corner_radius=10,
            command=self._schedule_job
        ).pack(fill="x", padx=18, pady=(4,18))
        # ── POSTER GALLERY AREA ───────────────────────────────────────────────
        gallery_hdr = ctk.CTkFrame(p, fg_color="transparent")
        gallery_hdr.pack(fill="x", padx=20, pady=(12, 4))
        ctk.CTkLabel(gallery_hdr, text="🎨  Generated Poster Variants",
                     font=("Helvetica", 14, "bold"),
                     text_color=BRAND["accent2"]).pack(side="left")
        ctk.CTkLabel(gallery_hdr,
                     text="AI automatically finds domain-relevant images & applies gradient layouts",
                     font=("Helvetica", 11), text_color=BRAND["text_mid"]).pack(side="left", padx=12)

        self.gallery_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.gallery_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.gallery_placeholder = ctk.CTkLabel(
            self.gallery_frame,
            text="⚡  Generate a post to see AI-created poster variants here",
            font=("Helvetica", 13), text_color=BRAND["text_lo"]
        )
        self.gallery_placeholder.pack(pady=30)
      
    # ── Generation ───────────────────────────────────────────────────────────

    def _trigger_generation(self):
        topic    = self.topic_in.get().strip()
        headline = self.headline_in.get().strip()
        if not topic:
            messagebox.showwarning("Topic Required", "Please enter a topic for the post.")
            return
        if not headline:
            headline = topic[:50]

        count = int(self.img_count_var.get())
        self.gen_btn.configure(state="disabled", text="⏳  Generating...")
        self._progress_show("🤖  AI is writing post text...")

        threading.Thread(
            target=self._generation_worker,
            args=(topic, headline, count),
            daemon=True
        ).start()

    def _progress_show(self, msg):
        self.progress_lbl.configure(text=msg)
        self.progress_bar.pack(fill="x", pady=4)
        self.progress_bar.start()

    def _progress_hide(self):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.progress_lbl.configure(text="")

    def _generation_worker(self, topic, headline, count):
        # Step 1: Generate text
        self.root.after(0, lambda: self._progress_show("🤖  Writing post with AI..."))
        text = generate_post_text(
            self.profile, self.post_type_var.get(),
            self.tone_var.get(), self.mood_var.get(), topic
        )

        self.root.after(0, lambda: self._set_text(text))
        self.root.after(0, lambda: self._progress_show("🔍  Finding domain-relevant images..."))

        # Step 2: Fetch images (domain-aware)
        images = fetch_images_for_post(
            self.profile, self.post_type_var.get(),
            self.mood_var.get(), topic, count=count
        )

        self.root.after(0, lambda: self._progress_show(f"🎨  Building {count} poster variants..."))

        # Step 3: Build posters
        posters = build_posters_for_images(
            images, headline, self.profile,
            self.post_type_var.get(), self.gradient_var.get(), topic
        )

        self.generated_text = text
        self.poster_paths   = [p[0] for p in posters]

        def _done():
            self._progress_hide()
            self._render_gallery(posters)
            self.gen_btn.configure(state="normal", text="⚡  Generate")

        self.root.after(0, _done)

    def _set_text(self, text):
        cleaned = clean_for_linkedin(text)
        self.txt_out.configure(state="normal")
        self.txt_out.delete("1.0", "end")
        self.txt_out.insert("1.0", cleaned)
        self.txt_out.configure(state="disabled")

    def _render_gallery(self, posters):
        # Clear
        for w in self.gallery_frame.winfo_children():
            w.destroy()
        self.poster_cards = []
        self.selected_poster = None
        self.selected_poster_idx = -1

        if not posters:
            ctk.CTkLabel(self.gallery_frame,
                         text="⚠️ No posters generated — check internet connection.",
                         text_color=BRAND["danger"]).pack(pady=20)
            return

        # Row of cards
        cards_row = ctk.CTkFrame(self.gallery_frame, fg_color="transparent")
        cards_row.pack(fill="x")

        for i, (path, src) in enumerate(posters):
            card = PosterCard(cards_row, path, src, i,
                              on_select=self._on_poster_selected)
            card.pack(side="left", padx=10, pady=6)
            self.poster_cards.append(card)

        # Auto-select first
        if posters:
            self._on_poster_selected(0, posters[0][0])

    def _on_poster_selected(self, idx, path):
        self.selected_poster = path
        self.selected_poster_idx = idx
        for i, card in enumerate(self.poster_cards):
            card.set_selected(i == idx)
        self.selected_lbl.configure(text=f"Poster {idx+1} selected ✓",
                                     text_color=BRAND["success"])
        # Show mini preview
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((260, 195), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                    size=(img.width, img.height))
            self.selected_preview.configure(image=ctk_img, text="")
            self.selected_preview._ref = ctk_img
        except Exception:
            pass

    def _copy_text(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.txt_out.get("1.0", "end").strip())
        messagebox.showinfo("Copied", "Post text copied to clipboard!")

    def _toggle_edit(self):
        current = self.txt_out.cget("state")
        if current == "disabled":
            self.txt_out.configure(state="normal")
            self.edit_btn.configure(text="🔒 Lock", fg_color=BRAND["purple"])
        else:
            self.txt_out.configure(state="disabled")
            self.edit_btn.configure(text="✏️ Edit", fg_color=BRAND["bg_hover"])

    def _save_poster(self):
        if not self.selected_poster or not os.path.exists(self.selected_poster):
            messagebox.showwarning("No Poster", "Please select a poster first.")
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png")],
            initialfile="linkedin_poster.png"
        )
        if p:
            import shutil
            shutil.copy(self.selected_poster, p)
            messagebox.showinfo("Saved", f"Poster saved to:\n{p}")

    def _post_now(self):
        txt = self.txt_out.get("1.0", "end").strip()
        if not txt:
            messagebox.showwarning("No Content", "Generate post content first.")
            return
        if not self.token or not self.linkedin_urn:
            messagebox.showwarning("Not Connected", "Please sign in with LinkedIn.")
            return
        self.post_now_btn.configure(state="disabled", text="⏳  Posting...")
        threading.Thread(target=self._post_worker, args=(txt,), daemon=True).start()
    def _schedule_ai_campaign(self):
        try:
            days = int(self.days_entry.get())
        except:
            messagebox.showwarning(
                "Invalid",
                "Enter valid number of days"
            )
            return
        jobs = _load_json(
            CONFIG["SCHEDULER_FILE"]
        ) or []
        start_dt = self.compose_dt_picker.get_datetime()
        company = self.profile.get(
            "company",
            ""
        )
        domain = self.profile.get(
            "domain",
            ""
        )
        product = self.profile.get(
    "product",
    ""
) or self.profile.get(
    "service",
    ""
)

        for i in range(days):

            schedule_dt = start_dt + datetime.timedelta(days=i)

            jobs.append({
                "id": int(time.time()*1000)+i,
                "datetime": schedule_dt.strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "status": "pending",
                "mode": "ai_auto",
                "company": company,
                "domain": domain,
                "product": product,
                "urn": self.linkedin_urn
            })

        _save_json(
            CONFIG["SCHEDULER_FILE"],
            jobs
        )
        self._refresh_queue()
        messagebox.showinfo(
            "Success",
            f"{days} AI posts scheduled"
        )

       
    def _post_worker(self, txt):
        try:
            txt = clean_for_linkedin(txt)   # strip ** markdown before posting
            if self.selected_poster and os.path.exists(self.selected_poster):
                st, resp = linkedin_post_with_image(
                    self.token, self.linkedin_urn, txt, self.selected_poster
                )
            else:
                st, resp = linkedin_post_text(self.token, self.linkedin_urn, txt)

            def _done():
                self.post_now_btn.configure(state="normal", text="🚀  Post to LinkedIn Now")
                if st in (200, 201):
                    messagebox.showinfo("✅ Posted!", "Your post is live on LinkedIn!")
                else:
                    messagebox.showerror("Failed", f"Status {st}\n{resp}")

            self.root.after(0, _done)
        except Exception as e:
            self.root.after(0, lambda: self.post_now_btn.configure(
                state="normal", text="🚀  Post to LinkedIn Now"
            ))
            self.root.after(0, lambda e=e: messagebox.showerror("Error", str(e)))

    def _schedule_job(self):

        txt = self.txt_out.get("1.0", "end").strip()

        if not txt:
            messagebox.showwarning(
                "No Content",
                "Generate post content first."
            )
            return

        if not self.compose_dt_picker.validate():
            messagebox.showwarning(
                "Invalid Date",
                "Please enter a valid date/time."
            )
            return

        dt_str = self.compose_dt_picker.get_datetime_str()

        jobs = _load_json(
            CONFIG["SCHEDULER_FILE"]
        ) or []

        jobs.append({
            "id": int(time.time() * 1000),
            "datetime": dt_str,
            "status": "pending",
            "text": txt,
            "urn": self.linkedin_urn,
            "image_path": getattr(
                self,
                "selected_image_path",
                None
            )
        })

        _save_json(
            CONFIG["SCHEDULER_FILE"],
            jobs
        )

        self._refresh_queue()

        messagebox.showinfo(
            "Success",
            "Post added to schedule."
        )

    def _schedule_ai_campaign(self):
        try:
            days = int(self.days_entry.get())
        except:
            messagebox.showwarning(
                "Invalid",
                "Enter number of days"
            )
            return

        jobs = _load_json(
            CONFIG["SCHEDULER_FILE"]
        ) or []

        dt_str = self.compose_dt_picker.get_datetime_str()

        try:
            start_dt = datetime.datetime.strptime(
                dt_str,
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            messagebox.showerror(
                "Schedule Error",
                f"Invalid datetime: {dt_str}"
            )
            return

        company = self.profile.get(
            "company",
            ""
        )

        domain = self.profile.get(
            "domain",
            ""
        )

        product = self.profile.get(
            "product",
            ""
        )

        topic = self.topic_in.get().strip()

        mode = self.campaign_mode.get()

        for i in range(days):

            schedule_dt = start_dt + datetime.timedelta(days=i)

            jobs.append({
                "id": int(time.time()*1000)+i,
                "datetime": schedule_dt.strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "status": "pending",
                "mode": "ai_auto",
                "campaign_mode": mode,
                "topic": topic,
                "company": company,
                "domain": domain,
                "product": product,
                "urn": self.linkedin_urn
            })

        _save_json(
            CONFIG["SCHEDULER_FILE"],
            jobs
        )

        messagebox.showinfo(
            "Campaign Created",
            f"{days} days scheduled successfully."
        )
    # ── SCHEDULER PAGE ───────────────────────────────────────────────────────

    def _build_scheduler_page(self):
        p = self.pages["scheduler"]

        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(hdr, text="📅  Content Schedule Queue",
                     font=("Helvetica", 18, "bold"),
                     text_color=BRAND["text_hi"]).pack(side="left")
        ctk.CTkButton(hdr, text="🔄 Refresh", height=34, width=100,
                      font=("Helvetica", 12),
                      fg_color=BRAND["bg_hover"], hover_color=BRAND["border"],
                      command=self._refresh_queue).pack(side="right")

        # Stats bar
        self.stats_row = ctk.CTkFrame(p, fg_color="transparent")
        self.stats_row.pack(fill="x", padx=20, pady=8)

        # Queue
        self.queue_card = ctk.CTkFrame(p, fg_color=BRAND["bg_card"],
                                        corner_radius=16, border_width=1,
                                        border_color=BRAND["border"])
        self.queue_card.pack(fill="both", expand=True, padx=20, pady=8)

        q_inner_hdr = ctk.CTkFrame(self.queue_card, fg_color="transparent")
        q_inner_hdr.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(q_inner_hdr, text="Scheduled Posts",
                     font=("Helvetica", 14, "bold"),
                     text_color=BRAND["accent2"]).pack(side="left")

        self.queue_frame = ctk.CTkScrollableFrame(
            self.queue_card, fg_color="transparent", height=500,
            scrollbar_button_color=BRAND["border"]
        )
        self.queue_frame.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        self._refresh_queue()

    def _refresh_queue(self):
        for w in self.stats_row.winfo_children():
            w.destroy()
        for w in self.queue_frame.winfo_children():
            w.destroy()

        jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []

        # Stats
        total   = len(jobs)
        pending = sum(1 for j in jobs if j.get("status") == "pending")
        posted  = sum(1 for j in jobs if j.get("status") == "posted")
        failed  = sum(1 for j in jobs if "failed" in j.get("status", ""))

        for label, count, color in [
            ("Total", total, BRAND["text_mid"]),
            ("Pending", pending, BRAND["warning"]),
            ("Posted", posted, BRAND["success"]),
            ("Failed", failed, BRAND["danger"]),
        ]:
            stat = ctk.CTkFrame(self.stats_row, fg_color=BRAND["bg_card"],
                                corner_radius=10, border_width=1,
                                border_color=BRAND["border"])
            stat.pack(side="left", padx=6)
            ctk.CTkLabel(stat, text=str(count),
                         font=("Helvetica", 26, "bold"),
                         text_color=color).pack(padx=24, pady=(10, 2))
            ctk.CTkLabel(stat, text=label,
                         font=("Helvetica", 11),
                         text_color=BRAND["text_mid"]).pack(padx=24, pady=(0, 10))

        if not jobs:
            ctk.CTkLabel(self.queue_frame,
                         text="📭  No scheduled posts yet.\n"
                              "Compose a post and use 'Add to Schedule Queue'.",
                         font=("Helvetica", 13),
                         text_color=BRAND["text_lo"]).pack(pady=40)
            return

        for j in reversed(jobs):
            status = j.get("status", "pending")
            st_color = (BRAND["success"] if status == "posted"
                        else BRAND["danger"] if "failed" in status
                        else BRAND["warning"])

            row = ctk.CTkFrame(self.queue_frame, fg_color=BRAND["bg_hover"],
                               corner_radius=12, border_width=1,
                               border_color=BRAND["border"])
            row.pack(fill="x", padx=6, pady=5)

            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.pack(fill="x", padx=14, pady=(10, 4))

            ctk.CTkLabel(meta,
                         text=f"🕒 {j.get('datetime', '—')}",
                         font=("Helvetica", 13, "bold"),
                         text_color=BRAND["text_hi"]).pack(side="left")

            ctk.CTkLabel(meta,
                         text=f"● {status.upper()}",
                         font=("Helvetica", 11, "bold"),
                         text_color=st_color).pack(side="right", padx=6)

            pt = j.get("post_type", "")
            if pt:
                ctk.CTkLabel(meta, text=pt,
                             font=("Helvetica", 11),
                             text_color=BRAND["accent"]).pack(side="right", padx=12)

            preview = j.get("text", "")[:160] + ("..." if len(j.get("text","")) > 160 else "")
            ctk.CTkLabel(row, text=preview,
                         font=("Helvetica", 12),
                         text_color=BRAND["text_mid"],
                         justify="left", anchor="w",
                         wraplength=900).pack(anchor="w", padx=14, pady=(0, 8))

            has_img = bool(j.get("image_path") and os.path.exists(j.get("image_path", "")))
            ctk.CTkLabel(row,
                         text="🖼️ With poster image" if has_img else "📝 Text only",
                         font=("Helvetica", 10),
                         text_color=BRAND["text_lo"]).pack(anchor="w", padx=14, pady=(0, 10))

            # Delete button
            def _delete(job_id=j.get("id")):
                all_jobs = _load_json(CONFIG["SCHEDULER_FILE"]) or []
                all_jobs = [jj for jj in all_jobs if jj.get("id") != job_id]
                _save_json(CONFIG["SCHEDULER_FILE"], all_jobs)
                self._refresh_queue()

            ctk.CTkButton(row, text="🗑 Remove", height=28, width=90,
                          font=("Helvetica", 11),
                          fg_color=BRAND["danger"], hover_color="#b91c1c",
                          command=_delete).pack(anchor="e", padx=14, pady=(0, 8))

    # ── SETTINGS PAGE ────────────────────────────────────────────────────────

    def _build_settings_page(self):
        p = self.pages["settings"]
        card = ctk.CTkFrame(p, fg_color=BRAND["bg_card"],
                             corner_radius=18, border_width=1,
                             border_color=BRAND["border"])
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(card, text="⚙️  Profile & Settings",
                     font=("Helvetica", 18, "bold"),
                     text_color=BRAND["text_hi"]).pack(anchor="w", padx=24, pady=20)

        # Current profile display
        info_frame = ctk.CTkFrame(card, fg_color=BRAND["bg_hover"],
                                   corner_radius=12)
        info_frame.pack(fill="x", padx=24, pady=8)

        prof = self.profile
        for k, v in [
            ("Name", prof.get("name", "—")),
            ("Company", prof.get("company", "—")),
            ("Domain", prof.get("domain", "—")),
            ("Product/Service", prof.get("product", "—")),
            ("Account Type", prof.get("user_type", "—").title()),
            ("LinkedIn URN", prof.get("urn", "—")),
        ]:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(row, text=f"{k}:",
                         font=("Helvetica", 12, "bold"),
                         text_color=BRAND["text_mid"], width=140,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=str(v),
                         font=("Helvetica", 12),
                         text_color=BRAND["text_hi"],
                         anchor="w").pack(side="left")

        ctk.CTkButton(card, text="✏️  Edit Profile",
                      height=46, font=("Helvetica", 13, "bold"),
                      fg_color=BRAND["accent"], hover_color="#0284c7",
                      corner_radius=10,
                      command=lambda: self._show_page("onboard")
                      ).pack(padx=24, pady=20, anchor="w")

        # Clear cache
        ctk.CTkButton(card, text="🗑  Clear Image Cache",
                      height=40, font=("Helvetica", 12),
                      fg_color=BRAND["bg_hover"], hover_color=BRAND["border"],
                      command=self._clear_cache
                      ).pack(padx=24, pady=4, anchor="w")

    def _clear_cache(self):
        import shutil
        try:
            shutil.rmtree(CONFIG["CACHE_DIR"])
            os.makedirs(CONFIG["CACHE_DIR"], exist_ok=True)
            messagebox.showinfo("Cache Cleared", "Image cache cleared successfully.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _start_login(self):
        self.connect_btn.configure(state="disabled", text="⏳  Connecting...")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        try:
            tok = linkedin_login_flow()
            if tok:
                self.token = tok
                urn, name, email = linkedin_get_userinfo(tok)
                self.linkedin_urn  = urn
                self.linkedin_name = name
                self.profile["urn"]  = urn
                self.profile["name"] = name
                save_profile(self.profile)
                self.root.after(0, self._on_logged_in)
            else:
                self.root.after(0, self._on_logout)
        except Exception as e:
            self.root.after(0, self._on_logout)
            self.root.after(0, lambda e=e: messagebox.showerror("Auth Error", str(e)))

    def _on_logged_in(self, auto=False):
        self.status_dot.configure(text="● Connected", text_color=BRAND["success"])
        self.user_lbl.configure(text=self.profile.get("name", "User"))
        self.connect_btn.configure(text="✓  Connected",
                                    state="disabled",
                                    fg_color=BRAND["bg_hover"])

        # Refresh post type options based on user_type
        utype  = self.profile.get("user_type", "company")
        pt_vals = POST_TYPES.get(utype, POST_TYPES["company"])
        if hasattr(self, "post_type_menu"):
            self.post_type_menu.configure(values=pt_vals)
            self.post_type_var.set(pt_vals[0])

        if not self.profile.get("company"):
            self._show_page("onboard")
        else:
            self._show_page("compose")

    def _on_logout(self):
        self.token = None
        self.linkedin_urn = None
        self.status_dot.configure(text="● Not Connected", text_color=BRAND["danger"])
        self.user_lbl.configure(text="")
        self.connect_btn.configure(text="🔗  Sign in with LinkedIn",
                                    state="normal", fg_color="#0a66c2")
        self._show_page("login")

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Studio PRO v3.0")
    parser.add_argument("--scheduler-only", action="store_true",
                        help="Run background scheduler daemon only (no GUI)")
    args, _ = parser.parse_known_args()

    if args.scheduler_only:
        print("=" * 60)
        print("  LinkedIn Studio PRO v3.0 — Scheduler Daemon Running")
        print("  Checking every 15 seconds for pending posts...")
        print("=" * 60)
        run_scheduler_daemon()
    else:
        app = App()
        app.run()


if __name__ == "__main__":
    main()
