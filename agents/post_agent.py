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


def _clean_post(text: str) -> str:
    """
    Clean up Gemini output before sending anywhere:
    1. Strip markdown bold (**word**) — LinkedIn renders it as raw asterisks
    2. Strip markdown italic (*word*)
    3. Collapse 3+ blank lines into 2 (keep breathing room but not excess)
    4. Strip leading/trailing whitespace
    """
    # Remove **bold** and *italic* markdown
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def generate_post(topic: dict) -> str:
    """
    Generate a LinkedIn post for the given topic dict.

    Supports two modes:
      Auto (RSS)   — topic = {topic, angle, reasoning}
      Manual       — topic = {topic, details}

    Gemini detects intent (marketing vs thought leadership) from the content.
    """
    if GEMINI_API_KEY == "DUMMY_GEMINI_API_KEY":
        print("[post_agent] Dummy mode — returning sample post")
        return DUMMY_POST

    # Build context block — works for both auto and manual
    topic_text   = topic.get("topic", "")
    details_text = topic.get("details", "")    # manual input
    angle_text   = topic.get("angle", "")      # auto (RSS) input
    reasoning    = topic.get("reasoning", "")  # auto (RSS) input

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

CRITICAL FORMATTING RULES — non-negotiable:
- Plain text ONLY. No markdown. No asterisks. No bold. No bullet symbols like • or -.
- Every paragraph is 1-2 lines max, followed by a blank line.
- The post must have visible breathing room — never a wall of text.
- Use → for lists only if needed, and only 2-3 items max.

TONE RULES — non-negotiable:
- Write like an engineer sharing a real observation with a peer. Casual but smart.
- ZERO corporate buzzwords. Never use: paradigm shift, unprecedented, fundamentally,
  redefine, bottleneck, ecosystem, leverage, synergy, game-changer, holistic, scalable solutions.
- Say the simple version. "AI handles calls humans can't" not "AI redefines customer interaction paradigms".
- If this is a product/marketing topic: surface it as a real problem + real observation.
  Never sound like an ad. The reader should feel informed, not sold to.
- If this is a thought leadership topic: share one sharp opinion and defend it briefly.

CONTENT RULES:
- One clear idea per post. Not a list of tips.
- End with one specific, sharp question — not "What do you think?"
- 3-4 hashtags on the last line only.

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
    image_data keys: image_path, image_url, pexels_query, photographer, photo_id
    """
    print(f"[post_agent] Generating post for: {topic['topic']}")
    post_text = generate_post(topic)

    print(f"[post_agent] Fetching image for topic...")
    image_data = image_agent.run(topic)

    return post_text, image_data