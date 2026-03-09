# app/session.py
import json
import logging
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

SESSION_TTL = 1800
MAX_EXCHANGES = 5


def _session_key(email: str) -> str:
    return f"session:{email}"


async def get_history(redis: Redis, email: str) -> list[dict]:
    raw = await redis.get(_session_key(email))
    if not raw:
        return []
    return json.loads(raw)


async def append_to_history(redis: Redis, email: str, user_message: str, assistant_message: str):
    history = await get_history(redis, email)

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})

    max_messages = MAX_EXCHANGES * 2
    if len(history) > max_messages:
        history = history[-max_messages:]

    await redis.setex(_session_key(email), SESSION_TTL, json.dumps(history))
    logger.info(
        f"Session mise à jour pour {email} — {len(history) // 2} échange(s) en mémoire.")


async def clear_history(redis: Redis, email: str):
    await redis.delete(_session_key(email))
    logger.info(f"Session effacée pour {email}.")
