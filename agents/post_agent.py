"""
Agent 2 — Post Generation
Takes the topic dict from topic_agent and generates a LinkedIn post
using Gemini, with persona + system prompt injection.
"""
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL, USER_PERSONA, SYSTEM_PROMPT

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


def generate_post(topic: dict) -> str:
    """
    Generate a LinkedIn post for the given topic dict.
    topic = {topic, angle, reasoning}
    Returns post text string.
    """
    if GEMINI_API_KEY == "DUMMY_GEMINI_API_KEY":
        print("[post_agent] Dummy mode — returning sample post")
        return DUMMY_POST

    user_prompt = f"""
Write a LinkedIn post for this person about the topic below.

TOPIC: {topic['topic']}
ANGLE TO TAKE: {topic['angle']}
CONTEXT: {topic['reasoning']}

ABOUT THE AUTHOR:
{USER_PERSONA}
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config={"system_instruction": SYSTEM_PROMPT},
    )
    post_text = response.text.strip()
    print(f"[post_agent] Generated post ({len(post_text)} chars)")
    return post_text


def run(topic: dict) -> str:
    """Entry point — returns generated post text."""
    print(f"[post_agent] Generating post for: {topic['topic']}")
    return generate_post(topic)
