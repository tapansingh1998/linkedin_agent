"""
Email Agent — sends the generated post to your inbox
with an Approve button. Clicking Approve hits the FastAPI endpoint.
"""
import smtplib
import secrets
import json
import os
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import (
    SMTP_PORT, SENDER_EMAIL, SENDER_PASS,
    APPROVAL_EMAIL, APP_BASE_URL
)

# Simple file-based token store (works fine for single user)
TOKEN_STORE_FILE = "pending_approvals.json"


def _load_store() -> dict:
    if os.path.exists(TOKEN_STORE_FILE):
        with open(TOKEN_STORE_FILE) as f:
            return json.load(f)
    return {}


def _save_store(store: dict):
    with open(TOKEN_STORE_FILE, "w") as f:
        json.dump(store, f, indent=2)


def create_approval_token(post_text: str, topic: dict) -> str:
    """Generate a secure token and persist {token: {post, topic}}."""
    token = secrets.token_urlsafe(32)
    store = _load_store()
    store[token] = {"type": "post_approval", "post": post_text, "topic": topic}
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


def _build_topic_selection_email(tokenized_topics: list[dict]) -> str:
    topic_cards = []
    for index, item in enumerate(tokenized_topics, start=1):
        topic = item["topic"]
        select_url = f"{APP_BASE_URL}/select-topic/{item['token']}"
        topic_cards.append(f"""
        <div class="topic-card">
          <div class="topic-number">Topic {index}</div>
          <h2>{escape(topic.get('topic', 'AI News'))}</h2>
          <p><strong>Angle:</strong> {escape(topic.get('angle', ''))}</p>
          <p>{escape(topic.get('reasoning', ''))}</p>
          <a href="{select_url}" class="btn-select">Select this topic</a>
        </div>
        """)

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f4f4f5; margin: 0; padding: 32px 16px; color: #18181b; }}
  .card {{ background: #fff; border-radius: 12px; max-width: 680px;
           margin: 0 auto; overflow: hidden; border: 1px solid #e4e4e7; }}
  .header {{ background: #0a66c2; padding: 24px 32px; }}
  .header h1 {{ color: #fff; margin: 0; font-size: 20px; font-weight: 600; }}
  .header p  {{ color: #bfdbfe; margin: 4px 0 0; font-size: 14px; }}
  .body {{ padding: 24px 32px; }}
  .topic-card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px;
                 margin-bottom: 16px; background: #f8fafc; }}
  .topic-number {{ color: #1d4ed8; font-size: 12px; font-weight: 700;
                   text-transform: uppercase; letter-spacing: .06em; }}
  h2 {{ font-size: 17px; margin: 8px 0 10px; color: #0f172a; }}
  p {{ font-size: 14px; line-height: 1.6; color: #334155; margin: 8px 0; }}
  .btn-select {{ display: inline-block; background: #0a66c2; color: #fff;
                 border-radius: 8px; padding: 11px 18px; font-size: 14px;
                 font-weight: 600; text-decoration: none; margin-top: 10px; }}
  .footer {{ padding: 16px 32px; border-top: 1px solid #f1f5f9;
             font-size: 12px; color: #71717a; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>Choose Today's LinkedIn Topic</h1>
    <p>Pick one topic and the agent will draft the post for your final approval.</p>
  </div>
  <div class="body">
    {''.join(topic_cards)}
  </div>
  <div class="footer">
    Selecting a topic only creates a draft. It will not publish to LinkedIn until you approve the generated post.
  </div>
</div>
</body>
</html>
"""


def _build_html_email(post_text: str, topic: dict, approve_url: str) -> str:
    escaped_post = escape(post_text).replace("\n", "<br>")
    escaped_topic = escape(topic.get('topic', 'AI News')[:80])
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f4f4f5; margin: 0; padding: 32px 16px; color: #18181b; }}
  .card {{ background: #fff; border-radius: 12px; max-width: 600px;
           margin: 0 auto; overflow: hidden;
           border: 1px solid #e4e4e7; }}
  .header {{ background: #0a66c2; padding: 24px 32px; }}
  .header h1 {{ color: #fff; margin: 0; font-size: 20px; font-weight: 600; }}
  .header p  {{ color: #bfdbfe; margin: 4px 0 0; font-size: 14px; }}
  .body {{ padding: 28px 32px; }}
  .label {{ font-size: 11px; font-weight: 600; letter-spacing: .08em;
            text-transform: uppercase; color: #71717a; margin-bottom: 6px; }}
  .topic-pill {{ display:inline-block; background:#eff6ff; color:#1d4ed8;
                 border-radius:6px; padding:4px 10px; font-size:13px;
                 margin-bottom:20px; }}
  .post-box {{ background: #f8fafc; border: 1px solid #e2e8f0;
               border-radius: 8px; padding: 20px; font-size: 15px;
               line-height: 1.7; white-space: pre-wrap; color: #1e293b; }}
  .actions {{ padding: 0 32px 28px; display:flex; gap:12px; }}
  .btn-approve {{ background: #0a66c2; color: #fff; border: none;
                  border-radius: 8px; padding: 14px 32px; font-size: 15px;
                  font-weight: 600; text-decoration: none; cursor: pointer; }}
  .btn-reject  {{ background: #fff; color: #71717a; border: 1px solid #e4e4e7;
                  border-radius: 8px; padding: 14px 32px; font-size: 15px;
                  text-decoration: none; cursor: pointer; }}
  .footer {{ padding: 16px 32px; border-top: 1px solid #f1f5f9;
             font-size: 12px; color: #a1a1aa; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>LinkedIn Post Ready for Review</h1>
    <p>Your AI agent has drafted a post — approve to publish instantly.</p>
  </div>
  <div class="body">
    <div class="label">Topic</div>
    <div class="topic-pill">{escaped_topic}</div>
    <div class="label">Draft Post</div>
    <div class="post-box">{escaped_post}</div>
  </div>
  <div class="actions">
    <a href="{approve_url}" class="btn-approve">Approve &amp; Post to LinkedIn</a>
    <a href="#" class="btn-reject">Discard</a>
  </div>
  <div class="footer">
    This email was generated automatically by your LinkedIn AI agent.
    The Discard link simply does nothing — the post will not be published unless you click Approve.
  </div>
</div>
</body>
</html>
"""


def send_topic_selection_email(topics: list[dict]) -> list[dict]:
    """
    Send an email with five topic options.
    Returns [{token, topic}, ...] so the run log can show pending choices.
    """
    tokenized_topics = create_topic_selection_tokens(topics)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[LinkedIn Agent] Choose today's topic"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = APPROVAL_EMAIL

    html_body = _build_topic_selection_email(tokenized_topics)
    msg.attach(MIMEText(html_body, "html"))

    if SENDER_EMAIL == "dummy.sender@gmail.com":
        print("[email_agent] DUMMY mode - skipping real SMTP send")
        for item in tokenized_topics:
            print(f"[email_agent] Topic select URL: {APP_BASE_URL}/select-topic/{item['token']}")
        return tokenized_topics

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, APPROVAL_EMAIL, msg.as_string())

    print(f"[email_agent] Topic selection email sent to {APPROVAL_EMAIL}")
    return tokenized_topics


def send_approval_email(post_text: str, topic: dict) -> str:
    """
    Create approval token, send HTML email with Approve button.
    Returns the approval token.
    """
    token = create_approval_token(post_text, topic)
    approve_url = f"{APP_BASE_URL}/approve/{token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[LinkedIn Agent] Post ready: {topic.get('topic', 'AI Update')[:50]}"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = APPROVAL_EMAIL

    html_body = _build_html_email(post_text, topic, approve_url)
    msg.attach(MIMEText(html_body, "html"))

    if SENDER_EMAIL == "dummy.sender@gmail.com":
        print("[email_agent] DUMMY mode — skipping real SMTP send")
        print(f"[email_agent] Approve URL would be: {approve_url}")
        return token

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, APPROVAL_EMAIL, msg.as_string())

    print(f"[email_agent] Approval email sent to {APPROVAL_EMAIL}")
    return token