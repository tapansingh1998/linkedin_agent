"""
Agent 2 — Post Generation
Takes the topic dict from topic_agent (auto) or manual input from dashboard,
generates a LinkedIn post using Gemini with persona + system prompt injection.
Handles both thought leadership and marketing content automatically.
"""
import re
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL, USER_PERSONA, SYSTEM_PROMPT
from agents import image_agent

DUMMY_POST = """Most engineers think RAG is just "add a vector DB and call it a day."

It's not.

After building 6 RAG pipelines in production, here's what actually matters:

→ Chunk size kills more projects than model choice
→ Hybrid search (BM25 + dense) beats pure vector search in 80% of cases
→ Your retrieval eval is more important than your generation eval
→ Metadata filtering is the cheat code nobody talks about

The painful truth: most RAG failures are retrieval failures, not LLM failures.

We obsess over prompts and models while ignoring the boring infrastructure that actually determines quality.

Next time your RAG pipeline underperforms — before you swap the LLM, audit your chunking strategy.

What's been your biggest RAG surprise in production?

#RAG #LLM #AIEngineering #VectorSearch #AgenticAI"""


# ── Unicode bold converter ────────────────────────────────────────────────────

_BOLD_MAP = {}

def _build_bold_map():
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold   = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    for n, b in zip(normal, bold):
        _BOLD_MAP[n] = b

_build_bold_map()

def _to_unicode_bold(word: str) -> str:
    return "".join(_BOLD_MAP.get(c, c) for c in word)

def _apply_bold_tags(text: str) -> str:
    def replacer(match):
        return _to_unicode_bold(match.group(1))
    return re.sub(r'\[B\](.+?)\[/B\]', replacer, text)


# ── Post cleaner ──────────────────────────────────────────────────────────────

def _clean_post(text: str) -> str:
    text = _apply_bold_tags(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Post generator ────────────────────────────────────────────────────────────

def generate_post(topic: dict) -> str:
    if GEMINI_API_KEY == "DUMMY_GEMINI_API_KEY":
        print("[post_agent] Dummy mode — returning sample post")
        return DUMMY_POST

    topic_text   = topic.get("topic", "")
    details_text = topic.get("details", "")
    angle_text   = topic.get("angle", "")
    reasoning    = topic.get("reasoning", "")

    context_lines = []
    if details_text:
        context_lines.append(f"USER CONTEXT & INTENT: {details_text}")
    if angle_text:
        context_lines.append(f"SUGGESTED ANGLE: {angle_text}")
    if reasoning:
        context_lines.append(f"WHY THIS TOPIC: {reasoning}")
    context_block = "\n".join(context_lines)

    user_prompt = f"""
Write a LinkedIn post about the topic below.

TOPIC: {topic_text}

{context_block}

STRUCTURE — follow this exactly, no exceptions:
Line 1: [B]{topic_text}[/B]
Line 2: (blank line)
Line 3: Hook — short, punchy, 1 line
Line 4: (blank line)
Body: 2-3 short paragraphs, 1-2 lines each, blank line between each
(blank line)
Closing sharp question?
(blank line)
#hashtag1 #hashtag2 #hashtag3

FORMATTING RULES:
- The topic is ALWAYS the first line, fully bolded using [B]{topic_text}[/B]
- Use [B]word[/B] on 2-3 more important words in the body and question
- Bold = the words that carry the most weight, not random words
- Every paragraph max 2 lines, then blank line — never a wall of text
- No markdown, no asterisks, no bullet symbols like • or -
- Use → for lists only if needed, max 2-3 items

TONE RULES — non-negotiable:
- Write like an engineer sharing a real observation with a peer. Casual but smart.
- ZERO corporate buzzwords. Never use: paradigm shift, unprecedented, fundamentally,
  redefine, bottleneck, ecosystem, leverage, synergy, game-changer, holistic, scalable solutions.
- If marketing topic: surface it as a real problem + observation. Never sound like an ad.
- If thought leadership: share one sharp opinion and defend it briefly.

CONTENT RULES:
- One clear idea per post. Not a list of tips.
- Closing question must be specific and sharp — not "What do you think?"
- 3-4 hashtags on the last line only

ABOUT THE AUTHOR:
{USER_PERSONA}
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config={"system_instruction": SYSTEM_PROMPT},
    )
    post_text = _clean_post(response.text)
    print(f"[post_agent] Generated post ({len(post_text)} chars)")
    return post_text


def run(topic: dict) -> tuple[str, dict]:
    """
    Entry point — returns (post_text, image_data).
    Works for both auto (RSS) and manual (dashboard) topics.
    """
    print(f"[post_agent] Generating post for: {topic['topic']}")
    post_text = generate_post(topic)

    print(f"[post_agent] Fetching image for topic...")
    image_data = image_agent.run(topic)

    return post_text, image_data