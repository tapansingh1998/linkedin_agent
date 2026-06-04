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
You are a visual director choosing a Pexels stock photo for a LinkedIn post.
Your job is to find an image that shows the EXACT SCENE the post is about — not a metaphor, not a generic tech photo.

POST TOPIC: {topic_text}
POST CONTEXT / INTENT: {context}

RECENTLY USED QUERIES (do NOT repeat visually — pick something distinct):
{past_block}

THINKING PROCESS — follow this every time:
1. What is the real-world SCENE this post describes? (e.g. someone booking an appointment by phone)
2. Who are the PEOPLE or OBJECTS in that scene? (e.g. receptionist, phone, calendar, robot)
3. What is the SETTING? (e.g. clinic, office, call center)
4. Write 3-4 words that would find a photo of that exact scene on Pexels.

RULES:
- Return ONLY 3-4 words. Nothing else. No explanation, no punctuation.
- Must be a real-world scene photo — not an abstract, not an illustration, not a generic "technology" shot.
- Be SPECIFIC. "robot answering phone" beats "AI technology". "doctor booking appointment" beats "healthcare AI".
- If the topic is a business use case: show the human scenario the product solves.
- If the topic is a technical insight: show the real-world consequence or metaphor (e.g. "engineer debugging server").
- Avoid: "artificial intelligence", "technology innovation", "digital transformation", "laptop coding", "circuit board".

SCENE-BASED EXAMPLES (this is the level of specificity we want):
  Topic: AI voice bot | Context: 24/7 appointment booking → "receptionist phone booking appointment"
  Topic: AI voice bot | Context: call center automation → "call center agent headset"
  Topic: RAG pipelines | Context: retrieval failures → "engineer searching documents frustrated"
  Topic: MLOps | Context: deployment failures → "server room engineer monitoring"
  Topic: LLM fine-tuning | Context: prompt beats fine-tune → "engineer whiteboard writing"
  Topic: Agentic AI | Context: autonomous decisions → "robot arm factory precision"
  Topic: Data privacy | Context: user data leaks → "locked door security office"

Your query (3-4 words, the exact scene):"""

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