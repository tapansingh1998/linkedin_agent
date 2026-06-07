"""
Email Agent — sends the generated post to your inbox
with an Approve button. Clicking Approve hits the FastAPI endpoint.
Uses Resend for reliable email delivery.
"""
import resend
import secrets
import json
import os
from html import escape
from config import (
    SENDER_EMAIL, APPROVAL_EMAIL, APP_BASE_URL
)

# Initialize Resend
resend.api_key = os.getenv("RESEND_API_KEY")

# Simple file-based token store (works fine for single user)
TOKEN_STORE_FILE = "pending_approvals.json"


# ── Token store helpers ───────────────────────────────────────────────────────

def _load_store() -> dict:
    if os.path.exists(TOKEN_STORE_FILE):
        with open(TOKEN_STORE_FILE) as f:
            return json.load(f)
    return {}


def _save_store(store: dict):
    with open(TOKEN_STORE_FILE, "w") as f:
        json.dump(store, f, indent=2)


def create_approval_token(post_text: str, topic: dict, image_data: dict | None = None) -> str:
    """Generate a secure token and persist {token: {post, topic, image_data}}."""
    token = secrets.token_urlsafe(32)
    store = _load_store()
    store[token] = {
        "type": "post_approval",
        "post": post_text,
        "topic": topic,
        "image_data": image_data or {},
    }
    _save_store(store)
    return token


def create_topic_selection_tokens(topics: list[dict]) -> list[dict]:
    """Generate one token per topic option and persist the topic data."""
    store = _load_store()
    tokenized_topics = []
    for topic in topics:
        token = secrets.token_urlsafe(32)
        store[token] = {"type": "topic_selection", "topic": topic}
        tokenized_topics.append({"token": token, "topic": topic})
    _save_store(store)
    return tokenized_topics


def get_pending_post(token: str) -> dict | None:
    """Retrieve and consume a pending approval token."""
    store = _load_store()
    data = store.pop(token, None)
    if data and data.get("type") != "post_approval":
        store[token] = data
        return None
    if data:
        data.pop("type", None)
        _save_store(store)
    return data


def get_pending_topic(token: str) -> dict | None:
    """Retrieve and consume a pending topic selection token."""
    store = _load_store()
    data = store.pop(token, None)
    if data and data.get("type") != "topic_selection":
        store[token] = data
        return None
    if data:
        data.pop("type", None)
        _save_store(store)
    return data


# ── Shared email sender ───────────────────────────────────────────────────────

def _send_email(subject: str, html: str):
    resend.Emails.send({
        "from": SENDER_EMAIL,
        "to": APPROVAL_EMAIL,
        "subject": subject,
        "html": html,
    })


# ── Topic selection email ─────────────────────────────────────────────────────

def _build_topic_selection_email(tokenized_topics: list[dict]) -> str:
    topic_cards = ""
    for index, item in enumerate(tokenized_topics, start=1):
        topic = item["topic"]
        select_url = f"{APP_BASE_URL}/select-topic/{item['token']}"
        topic_cards += f"""
<div style="border:1px solid #e2e8f0;border-radius:8px;padding:14px;margin-bottom:12px;background:#f8fafc;">
  <div style="color:#1d4ed8;font-size:11px;font-weight:700;text-transform:uppercase;">Topic {index}</div>
  <div style="font-size:15px;font-weight:600;margin:6px 0;color:#0f172a;">{escape(topic.get('topic', ''))}</div>
  <div style="font-size:13px;color:#334155;margin-bottom:10px;">{escape(topic.get('angle', ''))}</div>
  <a href="{select_url}" style="display:inline-block;background:#0a66c2;color:#fff;border-radius:6px;padding:9px 16px;font-size:13px;font-weight:600;text-decoration:none;">Select this topic</a>
</div>"""

    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#f4f4f5;padding:24px;margin:0;">
<div style="background:#fff;border-radius:12px;max-width:600px;margin:0 auto;border:1px solid #e4e4e7;overflow:hidden;">
  <div style="background:#0a66c2;padding:20px 24px;">
    <h1 style="color:#fff;margin:0;font-size:18px;">Choose Today's LinkedIn Topic</h1>
    <p style="color:#bfdbfe;margin:4px 0 0;font-size:13px;">Pick one — agent will draft the post + find a unique image for your approval.</p>
  </div>
  <div style="padding:20px 24px;">{topic_cards}</div>
  <div style="padding:12px 24px;border-top:1px solid #f1f5f9;font-size:11px;color:#71717a;">
    Selecting a topic only creates a draft. It will not publish until you approve.
  </div>
</div>
</body></html>"""


# ── Approval email ────────────────────────────────────────────────────────────

def _build_html_email(
    post_text: str,
    topic: dict,
    approve_url: str,
    image_data: dict | None = None,
) -> str:
    escaped_post  = escape(post_text).replace("\n", "<br>")
    escaped_topic = escape(topic.get('topic', 'AI News')[:80])

    # Image preview block — only shown when Pexels found an image
    image_section = ""
    if image_data and image_data.get("image_url"):
        photographer = escape(image_data.get("photographer") or "Pexels")
        pexels_url   = escape(image_data.get("image_url") or "https://pexels.com")
        query        = escape(image_data.get("pexels_query") or "")
        image_section = f"""
<div style="font-size:11px;font-weight:600;text-transform:uppercase;color:#71717a;margin:16px 0 6px;">
  Image (auto-selected via Pexels)
</div>
<div style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  <a href="{pexels_url}" target="_blank">
    <img src="{pexels_url}" alt="Post image"
         style="width:100%;max-height:300px;object-fit:cover;display:block;">
  </a>
  <div style="padding:8px 12px;background:#f8fafc;font-size:12px;color:#64748b;">
    🔍 Query: <strong>{query}</strong> &nbsp;·&nbsp;
    📷 Photo by <a href="{pexels_url}" style="color:#1d4ed8;">{photographer}</a> on Pexels
  </div>
</div>"""

    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#f4f4f5;padding:24px;margin:0;">
<div style="background:#fff;border-radius:12px;max-width:600px;margin:0 auto;border:1px solid #e4e4e7;overflow:hidden;">
  <div style="background:#0a66c2;padding:20px 24px;">
    <h1 style="color:#fff;margin:0;font-size:18px;">LinkedIn Post Ready</h1>
    <p style="color:#bfdbfe;margin:4px 0 0;font-size:13px;">Approve to publish post{"&nbsp;+ image" if image_data and image_data.get("image_url") else ""} instantly.</p>
  </div>
  <div style="padding:20px 24px;">
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;color:#71717a;margin-bottom:4px;">Topic</div>
    <div style="display:inline-block;background:#eff6ff;color:#1d4ed8;border-radius:6px;padding:4px 10px;font-size:13px;margin-bottom:16px;">{escaped_topic}</div>
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;color:#71717a;margin-bottom:4px;">Draft Post</div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;font-size:14px;line-height:1.7;color:#1e293b;">{escaped_post}</div>
    {image_section}
  </div>
  <div style="padding:0 24px 24px;">
    <a href="{approve_url}" style="display:inline-block;background:#0a66c2;color:#fff;border-radius:8px;padding:12px 28px;font-size:15px;font-weight:600;text-decoration:none;">Approve &amp; Post to LinkedIn</a>
  </div>
  <div style="padding:12px 24px;border-top:1px solid #f1f5f9;font-size:11px;color:#a1a1aa;">
    Auto-generated by your LinkedIn AI agent. Post will not publish unless you click Approve.
  </div>
</div>
</body></html>"""


# ── Public send functions ─────────────────────────────────────────────────────

def send_topic_selection_email(topics: list[dict]) -> list[dict]:
    """Send email with 5 topic options. Returns [{token, topic}, ...]."""
    tokenized_topics = create_topic_selection_tokens(topics)
    html_body = _build_topic_selection_email(tokenized_topics)

    if not os.getenv("RESEND_API_KEY"):
        print("[email_agent] DUMMY mode - skipping real send")
        for item in tokenized_topics:
            print(f"[email_agent] Topic select URL: {APP_BASE_URL}/select-topic/{item['token']}")
        return tokenized_topics

    _send_email("[LinkedIn Agent] Choose today's topic", html_body)
    print(f"[email_agent] Topic selection email sent to {APPROVAL_EMAIL}")
    return tokenized_topics


def send_approval_email(post_text: str, topic: dict, image_data: dict | None = None) -> str:
    """
    Send approval email with post draft + image preview.
    Returns the approval token.
    """
    token = create_approval_token(post_text, topic, image_data)
    approve_url = f"{APP_BASE_URL}/approve/{token}"
    html_body = _build_html_email(post_text, topic, approve_url, image_data)

    if not os.getenv("RESEND_API_KEY"):
        print("[email_agent] DUMMY mode — skipping real send")
        print(f"[email_agent] Approve URL would be: {approve_url}")
        if image_data and image_data.get("image_url"):
            print(f"[email_agent] Image: {image_data['image_url']} (query: {image_data.get('pexels_query')})")
        return token

    _send_email(
        f"[LinkedIn Agent] Post ready: {topic.get('topic', 'AI Update')[:50]}",
        html_body,
    )
    print(f"[email_agent] Approval email sent to {APPROVAL_EMAIL}")
    return token
