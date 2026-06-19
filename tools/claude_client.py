"""
claude_client.py
────────────────
Thin wrapper around the Grok (xAI) API via OpenAI-compatible SDK.
Provides a single call() function used by all agents.
Handles retries, timeouts, and logging.
"""

import os
import logging
import time
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APIError

load_dotenv()
logger = logging.getLogger(__name__)

# Grok / xAI settings
GROK_BASE_URL = "https://api.x.ai/v1"
MODEL         = os.getenv("GROK_MODEL", "grok-3")
MAX_TOKENS    = 4096
MAX_RETRIES   = 3
RETRY_DELAY   = 2  # seconds


def _client() -> OpenAI:
    api_key = os.getenv("GROK_API_KEY", "")
    return OpenAI(api_key=api_key, base_url=GROK_BASE_URL)


def call(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0.2,
) -> str:
    """
    Call Grok and return the text response.

    Parameters
    ----------
    system_prompt : Agent identity and instructions
    user_prompt   : Data and task description
    max_tokens    : Maximum tokens in response
    temperature   : 0.0 = deterministic, higher = more creative

    Returns
    -------
    str: Grok's response text

    Raises
    ------
    RuntimeError if all retries fail
    """
    if not is_configured():
        raise RuntimeError(
            "GROK_API_KEY not set. Add it to your .env file or Streamlit secrets."
        )

    client = _client()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"Grok API call attempt {attempt}/{MAX_RETRIES}")
            start = time.time()

            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )

            elapsed = time.time() - start
            usage   = response.usage
            logger.info(
                f"Grok response: {usage.prompt_tokens} in / {usage.completion_tokens} out tokens | {elapsed:.1f}s"
            )

            return response.choices[0].message.content

        except RateLimitError:
            wait = RETRY_DELAY * attempt
            logger.warning(f"Rate limit hit. Waiting {wait}s before retry {attempt}.")
            time.sleep(wait)

        except APIError as e:
            logger.error(f"API error on attempt {attempt}: {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Grok API failed after {MAX_RETRIES} attempts: {e}")
            time.sleep(RETRY_DELAY)

    raise RuntimeError("Grok API call failed after all retries.")


def is_configured() -> bool:
    """Check if GROK_API_KEY is present without making a call."""
    key = os.getenv("GROK_API_KEY", "")
    return bool(key and key.startswith("gsk_"))
