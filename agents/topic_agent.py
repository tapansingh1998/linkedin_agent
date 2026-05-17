"""
Agent 1 — Topic Discovery
Fetches latest AI/tech news from free RSS feeds, then asks Gemini
to pick the most relevant trending topics for Tapan's persona.
"""
import httpx
import xml.etree.ElementTree as ET
from config import GEMINI_API_KEY, GEMINI_MODEL, USER_PERSONA
from google import genai

RSS_FEEDS = [
    "https://feeds.feedburner.com/oreilly/radar/atom",
    "https://rss.arxiv.org/rss/cs.AI",
    "https://www.artificialintelligence-news.com/feed/",
    "https://towardsdatascience.com/feed",
    "https://venturebeat.com/category/ai/feed/",
]

DUMMY_HEADLINES = [
    "Google releases Gemini 2.0 with improved reasoning capabilities",
    "OpenAI introduces o3 model beating human benchmarks on ARC-AGI",
    "LangGraph 0.3 ships with built-in human-in-the-loop support",
    "Mistral drops Mixtral 8x22B: a new open-source powerhouse",
    "Anthropic publishes research on constitutional AI scaling",
    "Meta's Llama 3.1 goes multimodal — what engineers need to know",
    "RAG vs Fine-tuning: new benchmarks settle the debate",
    "Agentic AI frameworks compared: LangGraph vs CrewAI vs AutoGen",
]


def _fetch_rss(url: str, timeout: int = 8) -> list[str]:
    """Pull headlines from a single RSS feed. Returns [] on any error."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        root = ET.fromstring(r.text)
        titles = []
        for item in root.iter("item"):
            t = item.find("title")
            if t is not None and t.text:
                titles.append(t.text.strip())
        # Also handle Atom feeds
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            t = entry.find("atom:title", ns)
            if t is not None and t.text:
                titles.append(t.text.strip())
        return titles[:10]
    except Exception:
        return []


def fetch_headlines() -> list[str]:
    """Aggregate headlines from all feeds. Falls back to dummy list."""
    all_headlines: list[str] = []
    for feed in RSS_FEEDS:
        all_headlines.extend(_fetch_rss(feed))

    if not all_headlines:
        print("[topic_agent] RSS fetch failed — using dummy headlines")
        return DUMMY_HEADLINES

    # Deduplicate and cap
    seen, unique = set(), []
    for h in all_headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:30]


def pick_best_topics(headlines: list[str], count: int = 5) -> list[dict]:
    """
    Ask Gemini to pick the best topics from the headlines
    that fit Tapan's persona. Returns a list of {topic, angle, reasoning}.
    """
    headlines_block = "\n".join(f"- {h}" for h in headlines)
    prompt = f"""
You are a content strategist for an AI/ML Engineer who posts on LinkedIn.

Your job: pick {count} headlines from the list below that are:
1. Strictly AI/ML focused — no generic tech, no business news
2. Trending and recent — nothing that feels old or already over-discussed
3. Different from each other — no two topics should be about the same theme
4. Opinionated — topics where an engineer can share a real counterpoint, lesson, or lived experience — NOT just summarise what happened

PERSONA:
{USER_PERSONA}

HEADLINES:
{headlines_block}

For each chosen topic, define:
- ANGLE: The specific contrarian or practical insight Tapan should take. Must be one sharp sentence — an opinion, not a description.
- REASONING: Why this topic is relevant RIGHT NOW for an AI/ML engineer audience. 1 sentence only.

Respond in this exact format (no extra text, no numbering variations):

TOPIC 1: <exact headline text>
ANGLE 1: <one sharp opinionated sentence on what angle to take>
REASONING 1: <one sentence on why this is timely and relevant>

TOPIC 2: <exact headline text>
ANGLE 2: <one sharp opinionated sentence on what angle to take>
REASONING 2: <one sentence on why this is timely and relevant>

Continue the same pattern through TOPIC {count}.
"""
    if GEMINI_API_KEY == "DUMMY_GEMINI_API_KEY":
        return [
            {
                "topic": headline,
                "angle": "Most engineers misunderstand this — here is what actually matters in production.",
                "reasoning": "This is actively being discussed in AI/ML circles right now.",
            }
            for headline in headlines[:count]
        ]

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = response.text.strip()

    topics = [
        {"topic": "", "angle": "", "reasoning": ""}
        for _ in range(count)
    ]
    for line in text.splitlines():
        for index in range(count):
            number = index + 1
            if line.startswith(f"TOPIC {number}:"):
                topics[index]["topic"] = line.replace(f"TOPIC {number}:", "").strip()
            elif line.startswith(f"ANGLE {number}:"):
                topics[index]["angle"] = line.replace(f"ANGLE {number}:", "").strip()
            elif line.startswith(f"REASONING {number}:"):
                topics[index]["reasoning"] = line.replace(f"REASONING {number}:", "").strip()

    parsed_topics = [topic for topic in topics if topic["topic"]]
    if parsed_topics:
        return parsed_topics[:count]

    # Fallback
    return [
        {
            "topic": headline,
            "angle": "Most engineers misunderstand this — here is what actually matters in production.",
            "reasoning": "This is actively being discussed in AI/ML circles right now.",
        }
        for headline in headlines[:count]
    ]


def pick_best_topic(headlines: list[str]) -> dict:
    """Backward-compatible single-topic picker."""
    return pick_best_topics(headlines, count=1)[0]


def run() -> list[dict]:
    """Full topic discovery pipeline. Returns five topic dicts."""
    print("[topic_agent] Fetching headlines...")
    headlines = fetch_headlines()
    print(f"[topic_agent] Got {len(headlines)} headlines")
    topics = pick_best_topics(headlines, count=5)
    print(f"[topic_agent] Chosen {len(topics)} topic options")
    return topics