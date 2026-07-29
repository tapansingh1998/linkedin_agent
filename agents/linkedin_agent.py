"""
Agent 3 — LinkedIn Publisher
Handles OAuth token storage and posting via LinkedIn UGC Posts API.
Token is persisted in Render environment variable so it survives restarts.
Supports image upload via LinkedIn Assets API.
"""
import base64
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
    try:
        with open(LINKEDIN_TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)
        print(f"[linkedin_agent] Token saved to {LINKEDIN_TOKEN_FILE}")
    except Exception as e:
        print(f"[linkedin_agent] Warning: Could not save token file: {e}")

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

def _decode_id_token(id_token: str) -> dict:
    """
    Decode the JWT id_token payload without signature verification.
    LinkedIn returns this alongside access_token when openid scope is granted.
    """
    try:
        # JWT structure: header.payload.signature — we only need payload
        payload_b64 = id_token.split(".")[1]
        # Pad base64 to a multiple of 4
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        print(f"[linkedin_agent] Could not decode id_token: {e}")
        return {}


def get_profile(access_token: str, token_data: dict | None = None) -> dict:
    """
    Get LinkedIn member profile to extract the person URN.

    Strategy (in order):
    1. Decode id_token JWT from token_data — zero extra API calls, no 401 risk.
    2. Call /v2/userinfo — requires 'openid profile' product on LinkedIn App.
    """
    # Strategy 1 — decode id_token locally (preferred, no API call needed)
    if token_data and token_data.get("id_token"):
        claims = _decode_id_token(token_data["id_token"])
        if claims.get("sub"):
            print("[linkedin_agent] Profile resolved from id_token ✓")
            return claims

    # Strategy 2 — fallback to /v2/userinfo API
    print("[linkedin_agent] Falling back to /v2/userinfo API call")
    resp = httpx.get(
        f"{LINKEDIN_API}/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


# ── Image upload ──────────────────────────────────────────────────────────────

def _register_image_upload(person_urn: str, access_token: str) -> tuple[str, str]:
    """
    Step 1 of LinkedIn image upload:
    Register the upload → get (upload_url, image_asset_urn).
    """
    payload = {
        "registerUploadRequest": {
            "owner": person_urn,
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "serviceRelationships": [
                {
                    "identifier": "urn:li:userGeneratedContent",
                    "relationshipType": "OWNER",
                }
            ],
        }
    }
    resp = httpx.post(
        f"{LINKEDIN_API}/assets?action=registerUpload",
        json=payload,
        headers={
            "Authorization":             f"Bearer {access_token}",
            "Content-Type":              "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data       = resp.json()
    upload_url = data["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    image_urn  = data["value"]["asset"]
    return upload_url, image_urn


def _upload_image_bytes(upload_url: str, image_path: str, access_token: str):
    """Step 2: PUT the image bytes to the signed LinkedIn upload URL."""
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    resp = httpx.put(
        upload_url,
        content=image_bytes,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "image/jpeg",
        },
        timeout=30,
    )
    resp.raise_for_status()
    print(f"[linkedin_agent] Image uploaded ({len(image_bytes) // 1024} KB)")


def upload_image(image_path: str, person_urn: str, access_token: str) -> str | None:
    """
    Full image upload flow.
    Returns the LinkedIn image asset URN, or None on any failure.
    Post will fall back to text-only gracefully.
    """
    try:
        upload_url, image_urn = _register_image_upload(person_urn, access_token)
        _upload_image_bytes(upload_url, image_path, access_token)
        print(f"[linkedin_agent] Image URN: {image_urn}")
        return image_urn
    except Exception as e:
        print(f"[linkedin_agent] Image upload failed: {e} — falling back to text-only")
        return None


# ── Posting ───────────────────────────────────────────────────────────────────

def post_to_linkedin(post_text: str, access_token: str, image_path: str | None = None, token_data: dict | None = None) -> dict:
    """
    Create a LinkedIn post via UGC Posts API.
    Attaches image if image_path is provided and upload succeeds.
    Falls back to text-only post if image upload fails.
    Returns the API response dict.
    """
    profile    = get_profile(access_token, token_data)
    person_urn = f"urn:li:person:{profile['sub']}"

    # Try image upload
    image_urn = None
    if image_path:
        image_urn = upload_image(image_path, person_urn, access_token)

    if image_urn:
        share_content = {
            "shareCommentary":    {"text": post_text},
            "shareMediaCategory": "IMAGE",
            "media": [
                {
                    "status": "READY",
                    "media":  image_urn,
                }
            ],
        }
    else:
        share_content = {
            "shareCommentary":    {"text": post_text},
            "shareMediaCategory": "NONE",
        }

    payload = {
        "author":        person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content
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
        timeout=15,
    )
    resp.raise_for_status()
    post_id = resp.headers.get("x-restli-id", "unknown")
    print(f"[linkedin_agent] Post published! ID: {post_id} | with_image: {image_urn is not None}")
    return resp.json() if resp.text else {"status": "published"}


# ── Entry point ───────────────────────────────────────────────────────────────

def run_post(post_text: str, image_path: str | None = None) -> dict:
    """
    Main entry: load token and publish post (with optional image).
    Raises RuntimeError if not authenticated yet.
    """
    # Dummy mode
    if LINKEDIN_CLIENT_ID == "DUMMY_CLIENT_ID":
        print("[linkedin_agent] DUMMY mode — simulating post")
        print(f"[linkedin_agent] Would post:\n{post_text[:120]}...")
        if image_path:
            print(f"[linkedin_agent] Would attach image: {image_path}")
        return {"status": "dummy_published", "post_preview": post_text[:120]}

    token_data = load_token()
    if not token_data:
        raise RuntimeError(
            "No LinkedIn token found. Visit /auth/linkedin to authenticate first."
        )

    # Pass full token_data so post_to_linkedin can use id_token for profile resolution
    return post_to_linkedin(post_text, token_data["access_token"], image_path, token_data)