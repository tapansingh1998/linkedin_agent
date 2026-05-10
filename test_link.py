"""
test_pipeline.py
----------------
Flow:
  STEP 1 → Gemini generates 5 topic ideas → email sent to you
  STEP 2 → You click a topic button in email → Gemini writes full post → email sent to you

Run: python test_pipeline.py
Then click a topic in your email to trigger Step 2.
"""

import os
import smtplib
import json
import secrets
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from google import genai

# ── Load .env ────────────────────────────────────────────────────────────────
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SENDER_EMAIL   = os.getenv("SENDER_EMAIL")
SENDER_PASS    = os.getenv("SENDER_PASS")
APPROVAL_EMAIL = os.getenv("APPROVAL_EMAIL")
BASE_URL       = "http://localhost:8888"

# In-memory token store {token: topic_text}
pending_topics: dict = {}

client = genai.Client(api_key=GEMINI_API_KEY)


# ── Step 1: Generate 5 topics via Gemini ─────────────────────────────────────

def generate_topics() -> list[str]:
    print("\n[1/2] Asking Gemini to generate 5 topic ideas...")

    prompt = """
You are a LinkedIn content strategist for Tapan Singh, an AI Engineer
focused on Agentic AI, LLMs, RAG pipelines, and MLOps.

Generate exactly 5 unique, engaging LinkedIn post topic ideas that would
perform well for an AI Engineer's audience.

Each topic should be specific, opinionated, and practical — not generic.
Topics should be trending or evergreen in the AI/ML space.

Respond ONLY with a JSON array of 5 strings. No explanation, no markdown fences.
Example: ["Topic 1", "Topic 2", "Topic 3", "Topic 4", "Topic 5"]
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()
    topics = json.loads(raw)
    print(f"✅ Got {len(topics)} topics:")
    for i, t in enumerate(topics, 1):
        print(f"   {i}. {t}")
    return topics


# ── Step 2: Generate full post for chosen topic ───────────────────────────────

def generate_post(topic: str) -> str:
    print(f"\n[Gemini] Writing post for: {topic}")

    prompt = f"""
You are an expert LinkedIn ghostwriter for AI engineers.
Write a LinkedIn post (150-200 words) for Tapan Singh, an AI Engineer
focused on Agentic AI and LLMs.

Topic: {topic}

Rules:
- Start with a bold hook (no "I am excited to share" clichés)
- Short paragraphs, 1-2 lines each
- Share a real insight or opinion
- End with a thought-provoking question
- Add 3-5 relevant hashtags at the bottom

Write ONLY the post. No intro, no explanation.
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    post = response.text.strip()
    print(f"✅ Post generated ({len(post)} chars)")
    return post


# ── Email: 5 topics with clickable buttons ────────────────────────────────────

def send_topics_email(topics: list[str]):
    print(f"\n📧 Sending topics email to {APPROVAL_EMAIL}...")

    buttons_html = ""
    for i, topic in enumerate(topics, 1):
        token = secrets.token_urlsafe(16)
        pending_topics[token] = topic
        url = f"{BASE_URL}/select?token={token}"
        buttons_html += f"""
        <a href="{url}" style="display:block;margin-bottom:12px;padding:14px 18px;
           background:#f8fafc;border:1.5px solid #e2e8f0;border-radius:10px;
           text-decoration:none;color:#1e293b;font-size:14px;line-height:1.5;">
          <span style="display:inline-block;width:26px;height:26px;border-radius:50%;
                background:#0a66c2;color:#fff;font-size:12px;font-weight:700;
                text-align:center;line-height:26px;margin-right:10px;">{i}</span>
          {topic}
        </a>"""

    html = f"""<!DOCTYPE html><html><head><style>
  body{{font-family:-apple-system,sans-serif;background:#f4f4f5;padding:32px 16px;margin:0}}
  .card{{background:#fff;border-radius:12px;max-width:580px;margin:0 auto;border:1px solid #e4e4e7;overflow:hidden}}
  .header{{background:#0a66c2;padding:20px 28px}}
  .header h1{{color:#fff;margin:0;font-size:18px}}
  .header p{{color:#bfdbfe;margin:4px 0 0;font-size:13px}}
  .body{{padding:24px 28px}}
  .label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#71717a;margin-bottom:14px}}
  .footer{{padding:14px 28px;border-top:1px solid #f1f5f9;font-size:12px;color:#a1a1aa}}
</style></head><body>
<div class="card">
  <div class="header">
    <h1>📋 Pick Your LinkedIn Topic</h1>
    <p>Gemini picked 5 ideas — click one to generate your post</p>
  </div>
  <div class="body">
    <div class="label">Choose one topic 👇</div>
    {buttons_html}
  </div>
  <div class="footer">
    After you click, Gemini will write the full post and email it back to you.
  </div>
</div></body></html>"""

    _send_email("🎯 LinkedIn Agent — Pick your topic!", html)
    print("✅ Topics email sent! Open your inbox and click a topic.")


# ── Email: Final post ─────────────────────────────────────────────────────────

def send_post_email(topic: str, post_text: str):
    print(f"\n📧 Sending generated post to {APPROVAL_EMAIL}...")

    html = f"""<!DOCTYPE html><html><head><style>
  body{{font-family:-apple-system,sans-serif;background:#f4f4f5;padding:32px 16px;margin:0}}
  .card{{background:#fff;border-radius:12px;max-width:580px;margin:0 auto;border:1px solid #e4e4e7;overflow:hidden}}
  .header{{background:#0a66c2;padding:20px 28px}}
  .header h1{{color:#fff;margin:0;font-size:18px}}
  .header p{{color:#bfdbfe;margin:4px 0 0;font-size:13px}}
  .body{{padding:24px 28px}}
  .label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#71717a;margin-bottom:8px}}
  .topic-pill{{display:inline-block;background:#eff6ff;color:#1d4ed8;border-radius:6px;padding:5px 12px;font-size:13px;margin-bottom:18px}}
  .post{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;font-size:14px;line-height:1.8;white-space:pre-wrap}}
  .badge{{display:inline-block;background:#dcfce7;color:#166534;border-radius:6px;padding:3px 10px;font-size:12px;font-weight:600;margin-bottom:16px}}
  .footer{{padding:14px 28px;border-top:1px solid #f1f5f9;font-size:12px;color:#a1a1aa}}
</style></head><body>
<div class="card">
  <div class="header">
    <h1>✍️ Your LinkedIn Post is Ready</h1>
    <p>Gemini wrote your post based on your selected topic</p>
  </div>
  <div class="body">
    <div class="badge">✓ Post generated</div>
    <div class="label">Topic</div>
    <div class="topic-pill">{topic}</div>
    <div class="label">Post</div>
    <div class="post">{post_text}</div>
  </div>
  <div class="footer">
    Next step: Approve &amp; Post button will be added in the full pipeline!
  </div>
</div></body></html>"""

    _send_email("✅ LinkedIn Post Ready — Review it!", html)
    print(f"✅ Post email sent to {APPROVAL_EMAIL}!")


# ── Shared email sender ───────────────────────────────────────────────────────

def _send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = APPROVAL_EMAIL
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, APPROVAL_EMAIL, msg.as_string())


# ── Local HTTP server to catch topic click ────────────────────────────────────

class SelectionHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence default logs

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token  = params.get("token", [None])[0]

        if parsed.path == "/select" and token and token in pending_topics:
            topic = pending_topics.pop(token)
            print(f"\n🎯 Topic selected: {topic}")

            # Respond to browser immediately
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#f0fdf4;">
            <h2 style="color:#166534;">&#10003; Topic received!</h2>
            <p style="color:#4b5563;">Gemini is writing your post now.<br>
            Check your inbox in about 10 seconds.</p>
            </body></html>""")

            # Generate post + send email in background thread
            def handle():
                post = generate_post(topic)
                send_post_email(topic, post)
                print("\n🎉 Full pipeline complete! Check your inbox.\n")
            threading.Thread(target=handle, daemon=True).start()

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Token not found or already used.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  LinkedIn Agent — 2-Step Pipeline Test")
    print("=" * 50)

    # Validate env vars
    missing = [v for v in ["GEMINI_API_KEY","SENDER_EMAIL","SENDER_PASS","APPROVAL_EMAIL"] if not os.getenv(v)]
    if missing:
        print(f"\n❌ Missing in .env: {', '.join(missing)}\n")
        exit(1)

    # Step 1 — topics → email
    topics = generate_topics()
    send_topics_email(topics)

    print("\n" + "─" * 50)
    print("  📬 Check your inbox and click a topic!")
    print("  Waiting for your selection...")
    print("  Press Ctrl+C to stop.")
    print("─" * 50 + "\n")

    # Step 2 — wait for click via local server
    server = HTTPServer(("localhost", 8888), SelectionHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped.")