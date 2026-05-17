"""
Agent 3 — LinkedIn Publisher
Handles OAuth token storage and posting via LinkedIn UGC Posts API.
Token is persisted in Render environment variable so it survives restarts.
"""
import json
import os
import httpx
from config import (
    LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI, LINKEDIN_TOKEN_FILE
)

LINKEDIN_API       = "https://api.linkedin.com/v2"
LINKEDIN_AUTH_URL  = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

RENDER_API_KEY    = os.getenv("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "")


# ── Render env var persistence ────────────────────────────────────────────────

def _save_token_to_render(token_data: dict):
    """Push token JSON into Render environment variable LINKEDIN_TOKEN_JSON."""
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("[linkedin_agent] RENDER_API_KEY or RENDER_SERVICE_ID not set — skipping Render persist")
        return

    try:
        # First get all existing env vars so we don't wipe them
        resp = httpx.get(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars",
            headers={
                "Authorization": f"Bearer {RENDER_API_KEY}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        existing = {item["envVar"]["key"]: item["envVar"]["value"] for item in resp.json()}

        # Update or add LINKEDIN_TOKEN_JSON
        existing["LINKEDIN_TOKEN_JSON"] = json.dumps(token_data)

        # PUT all env vars back
        payload = [{"key": k, "value": v} for k, v in existing.items()]
        put_resp = httpx.put(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars",
            headers={
                "Authorization": f"Bearer {RENDER_API_KEY}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        put_resp.raise_for_status()
        print("[linkedin_agent] Token persisted to Render env var LINKEDIN_TOKEN_JSON ✓")
    except Exception as e:
        print(f"[linkedin_agent] Warning: Could not persist token to Render: {e}")


# ── Token management ──────────────────────────────────────────────────────────

def load_token() -> dict | None:
    """
    Load token — checks in this order:
    1. LINKEDIN_TOKEN_JSON env var (survives Render restarts)
    2. linkedin_token.json file (local dev fallback)
    """
    # Priority 1 — env var (production)
    token_json = os.getenv("LINKEDIN_TOKEN_JSON", "")
    if token_json:
        try:
            token = json.loads(token_json)
            print("[linkedin_agent] Token loaded from env var ✓")
            return token
        except Exception:
            print("[linkedin_agent] Warning: LINKEDIN_TOKEN_JSON is malformed")

    # Priority 2 — file (local dev)
    if os.path.exists(LINKEDIN_TOKEN_FILE):
        with open(LINKEDIN_TOKEN_FILE) as f:
            print("[linkedin_agent] Token loaded from file ✓")
            return json.load(f)

    return None


def save_token(token_data: dict):
    """
    Persist token to:
    1. Render env var (survives restarts)
    2. Local file (local dev)
    """
    # Always save to file as local fallback
    try:
        with open(LINKEDIN_TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)
        print(f"[linkedin_agent] Token saved to {LINKEDIN_TOKEN_FILE}")
    except Exception as e:
        print(f"[linkedin_agent] Warning: Could not save token file: {e}")

    # Save to Render env var for persistence
    _save_token_to_render(token_data)


def exchange_code_for_token(code: str) -> dict:
    """Exchange OAuth authorization code for access token."""
    resp = httpx.post(LINKEDIN_TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  LINKEDIN_REDIRECT_URI,
        "client_id":     LINKEDIN_CLIENT_ID,
        "client_secret": LINKEDIN_CLIENT_SECRET,
    })
    resp.raise_for_status()
    token = resp.json()
    save_token(token)
    return token


def get_auth_url() -> str:
    """Build the LinkedIn OAuth authorization URL."""
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id":     LINKEDIN_CLIENT_ID,
        "redirect_uri":  LINKEDIN_REDIRECT_URI,
        "scope":         "openid profile w_member_social",
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


# ── Profile ───────────────────────────────────────────────────────────────────

def get_profile(access_token: str) -> dict:
    """Fetch LinkedIn member profile to get URN."""
    resp = httpx.get(
        f"{LINKEDIN_API}/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


# ── Posting ───────────────────────────────────────────────────────────────────

def post_to_linkedin(post_text: str, access_token: str) -> dict:
    """
    Create a LinkedIn text post via UGC Posts API.
    Returns the API response dict.
    """
    profile = get_profile(access_token)
    person_urn = f"urn:li:person:{profile['sub']}"

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    resp = httpx.post(
        f"{LINKEDIN_API}/ugcPosts",
        json=payload,
        headers={
            "Authorization":             f"Bearer {access_token}",
            "Content-Type":              "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    resp.raise_for_status()
    print(f"[linkedin_agent] Post published! ID: {resp.headers.get('x-restli-id', 'unknown')}")
    return resp.json() if resp.text else {"status": "published"}


def run_post(post_text: str) -> dict:
    """
    Main entry: load token and publish post.
    Raises RuntimeError if not authenticated yet.
    """
    # Dummy mode
    if LINKEDIN_CLIENT_ID == "DUMMY_CLIENT_ID":
        print("[linkedin_agent] DUMMY mode — simulating post")
        print(f"[linkedin_agent] Would post:\n{post_text[:120]}...")
        return {"status": "dummy_published", "post_preview": post_text[:120]}

    token_data = load_token()
    if not token_data:
        raise RuntimeError(
            "No LinkedIn token found. Visit /auth/linkedin to authenticate first."
        )

    return post_to_linkedin(post_text, token_data["access_token"])