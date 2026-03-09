# app/router.py
import os
import logging
import httpx
from dotenv import load_dotenv
from app.models import CVResult, User

load_dotenv()

logger = logging.getLogger(__name__)

LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")

DEPARTMENT_PROMPTS = {
    "RH": "Tu es un assistant RH. Tu aides à analyser des CVs et profils de candidats. Cite toujours les noms de fichiers des CVs pertinents dans ta réponse.",
    "FINANCE": "Tu es un assistant Finance. Tu aides à analyser des documents financiers et rapports.",
    "default": "Tu es un assistant interne Altiora. Réponds en te basant uniquement sur les documents fournis. Si aucun document ne correspond, dis-le clairement.",
}


def get_system_prompt(user: User) -> str:
    base_prompt = DEPARTMENT_PROMPTS.get(
        user.department, DEPARTMENT_PROMPTS["default"])
    return f"{base_prompt}\nRéponds toujours en français. Ne te base que sur les documents fournis, sans inventer d'informations."


def build_context(results: list[CVResult]) -> str:
    context_parts = []
    for r in results:
        context_parts.append(
            f"--- Document: {r.filename} (classification: {r.classification}, modifié par: {r.modified_by}) ---\n{r.text}"
        )
    return "\n\n".join(context_parts)


async def call_litellm(
    query: str,
    results: list[CVResult],
    user: User,
    history: list[dict],      # ← le 4ème paramètre
) -> str:
    context = build_context(results)

    user_message = f"""Question : {query}

Documents disponibles :
{context}"""

    messages = []
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {"messages": messages}

    logger.info(
        f"Appel LiteLLM — user: {user.email}, historique: {len(history) // 2} échange(s)")

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        response = await http_client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        logger.info(f"Réponse LiteLLM reçue pour {user.email}.")
        return answer
