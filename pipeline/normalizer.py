# pipeline/normalizer.py

import httpx
from pathlib import Path
from datetime import datetime


class Normalizer:
    """
    Convierte texto crudo de Notion al formato task.md estándar.
    Usa Gemini Flash como LLM converter (no consume tokens de Claude).
    """
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model   = model
        self._system = (Path("config/prompts/converter.md")).read_text(encoding="utf-8")

    def convert(
        self,
        raw_text:   str,
        page_id:    str,
        page_url:   str,
        page_title: str,
    ) -> str:
        """
        Llama a Gemini Flash y devuelve el task.md normalizado.
        """
        user_content = (
            f"page_id: {page_id}\n"
            f"page_url: {page_url}\n"
            f"page_title: {page_title}\n"
            f"fecha_ingesta: {datetime.utcnow().isoformat()}\n\n"
            f"---\n\n{raw_text}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": self._system}]},
            "contents": [{
                "role": "user",
                "parts": [{"text": user_content}],
            }],
            "generationConfig": {
                "temperature": 0.1,   # baja temperatura para output determinístico
                "maxOutputTokens": 2048,
            },
        }
        url = self.GEMINI_URL.format(model=self.model)
        with httpx.Client() as client:
            resp = client.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
