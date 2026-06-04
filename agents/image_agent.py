"""
Image Agent — finds a unique, topic-relevant image for each LinkedIn post.

Flow:
  1. Load image history (used IDs + past queries)
  2. Ask Gemini to extract visual search keywords from topic + details together
  3. Search Pexels with those keywords (fetch top 15)
  4. Skip any image IDs already used
  5. Pick the best remaining image, download it to a temp file
  6. Save ID + query to history so it's never repeated
"""

import json
import os
import tempfile
import httpx
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    PEXELS_API_KEY, IMAGE_HISTORY_FILE
)
from google import genai

PEXELS_SEARCH_URL   = "https://api.pexels.com/v1/search"
MAX_HISTORY_QUERIES = 20
MAX_HISTORY_IDS     = 200


# ── History helpers ───────────────────────────────────────────────────────────

def _load_history() -> dict:
    if os.path.exists(IMAGE_HISTORY_FILE):
        with open(IMAGE_HISTORY_FILE) as f:
            return json.load(f)
    return {"used_image_ids": [], "used_queries": []}


def _save_history(history: dict):
    history["used_image_ids"] = history["used_image_ids"][-MAX_HISTORY_IDS:]
    history["used_queries"]   = history["used_queries"][-MAX_HISTORY_QUERIES:]
    with open(IMAGE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ── Gemini: extract visual search keywords ────────────────────────────────────

def _extract_visual_query(topic: dict, used_queries: list[str]) -> str:
    """
    Ask Gemini to produce 3-4 word Pexels search query.
    Uses topic + details together so the image matches the actual intent,
    not just the headline. Works for both auto (RSS) and manual input.
    """
    topic_text   = topic.get("topic", "")
    details_text = topic.get("details", "")    # manual input
    angle_text   = topic.get("angle", "")      # auto input
    past_block   = "\n".join(f"- {q}" for q in used_queries[-10:]) or "none yet"

    # Combine all context so Gemini understands full intent
    context = details_text or angle_text or ""

    prompt = f"""
You are a visual content strategist. Pick the perfect Pexels stock-photo search query for a LinkedIn post.

POST TOPIC: {topic_text}
POST CONTEXT / INTENT: {context}

RECENTLY USED QUERIES (do NOT repeat — choose something visually distinct):
{past_block}

Rules:
- Return ONLY 3-4 words, nothing else — no explanation, no punctuation
- Must work well as a Pexels image search (real-world photos, not illustrations)
- Use BOTH the topic AND the context to find the right visual — the image must match the story being told
- If the context describes a business use case or product (e.g. voice bot for appointment booking), find an image that shows that real-world scenario (e.g. "customer service phone call")
- If the context is a technical insight (e.g. RAG retrieval failures), find a metaphor image (e.g. "data search documents")
- Avoid generic tech clichés like "artificial intelligence robot" or "laptop coding"

Examples:
  Topic: AI voice bot | Context: 24/7 appointment booking automation → "customer service phone office"
  Topic: RAG pipelines | Context: retrieval failures not LLM failures → "data search retrieval"
  Topic: MLOps | Context: deployment pipelines → "server room infrastructure"
  Topic: Fine-tuning LLMs | Context: prompt engineering beats fine-tuning → "precision detail engineering"
  Topic: Agentic AI | Context: autonomous decision making → "autonomous network connected"

Your query (3-4 words only):"""

    if GEMINI_API_KEY == "DUMMY_GEMINI_API_KEY":
        words = [w for w in topic_text.split() if len(w) > 3][:3]
        return " ".join(words) if words else "technology innovation future"

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    query = response.text.strip().strip('"').strip("'")
    query = " ".join(query.split()[:5])
    return query


# ── Pexels: search + filter ───────────────────────────────────────────────────

def _search_pexels(query: str, used_ids: list[int], per_page: int = 15) -> dict | None:
    if PEXELS_API_KEY == "DUMMY_PEXELS_API_KEY":
        print("[image_agent] DUMMY mode — skipping Pexels search")
        return None

    try:
        resp = httpx.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            timeout=10,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])

        if not photos:
            print(f"[image_agent] No Pexels results for query: '{query}'")
            return None

        for photo in photos:
            if photo["id"] not in used_ids:
                return photo

        print(f"[image_agent] All results for '{query}' already used — taking newest anyway")
        return photos[0]

    except Exception as e:
        print(f"[image_agent] Pexels search error: {e}")
        return None


# ── Download image to temp file ───────────────────────────────────────────────

def _download_image(photo: dict) -> str | None:
    url = photo.get("src", {}).get("large", "") or photo.get("src", {}).get("original", "")
    if not url:
        return None

    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "image/jpeg")
        ext = ".jpg" if "jpeg" in content_type else ".png"

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(resp.content)
        tmp.close()
        print(f"[image_agent] Downloaded image to {tmp.name} ({len(resp.content)//1024} KB)")
        return tmp.name

    except Exception as e:
        print(f"[image_agent] Image download error: {e}")
        return None


# ── Public entry point ────────────────────────────────────────────────────────

def run(topic: dict) -> dict:
    """
    Full image pipeline for one topic.
    Works for both auto (RSS) and manual (dashboard) topics.

    Returns:
        {
          "image_path":   "/tmp/xyz.jpg" | None,
          "image_url":    "https://pexels.com/..." | None,
          "pexels_query": "the search query used",
          "photographer": "Name" | None,
          "photo_id":     12345 | None,
        }
    """
    history = _load_history()

    query = _extract_visual_query(topic, history["used_queries"])
    print(f"[image_agent] Pexels query: '{query}'")

    photo = _search_pexels(query, history["used_image_ids"])

    if not photo:
        print("[image_agent] No image found — post will go text-only")
        return {
            "image_path":   None,
            "image_url":    None,
            "pexels_query": query,
            "photographer": None,
            "photo_id":     None,
        }

    image_path = _download_image(photo)

    history["used_image_ids"].append(photo["id"])
    history["used_queries"].append(query)
    _save_history(history)

    print(f"[image_agent] Image ready — ID {photo['id']} by {photo.get('photographer','unknown')}")

    return {
        "image_path":   image_path,
        "image_url":    photo.get("url"),
        "pexels_query": query,
        "photographer": photo.get("photographer"),
        "photo_id":     photo["id"],
    }