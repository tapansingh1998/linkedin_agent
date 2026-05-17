"""
Agent 2 — Post Generation
Takes the topic dict from topic_agent and generates a LinkedIn post
using Gemini, with persona + system prompt injection.
"""
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL, USER_PERSONA, SYSTEM_PROMPT

DUMMY_POST = """**RAG** is lying to you.

Not the idea — the implementation.

Most teams swap the LLM when results are bad.
The real problem? **Chunking strategy.**

Bad chunks → bad retrieval → bad answers.
The model never had a chance.

Before you touch the prompt or the model — audit your chunks.
Overlap, size, structure. That's where quality lives.

Are you fixing the model — or the wrong problem?

#RAG #LLMEngineering #AIEngineering #MLOps"""


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
Write a LinkedIn post for Tapan Singh using the topic and angle below.

TOPIC: {topic['topic']}
ANGLE: {topic['angle']}
CONTEXT: {topic['reasoning']}

AUTHOR PROFILE:
{USER_PERSONA}

Remember:
- Hook is 3-5 words, bold the key word
- Total post is 80-120 words max
- Bold 1-2 key phrases in the body
- End with one sharp specific question
- 3-4 hashtags at the bottom
- Write ONLY the post, nothing else
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