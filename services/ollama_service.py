"""Local Ollama client. No cloud fallbacks."""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

import config
from services.logging_config import logger

SETUP_INSTRUCTIONS = """
Ollama is required for local generation and is not currently available.

Windows setup:
1. Install Ollama from https://ollama.com/download
2. Ensure the Ollama service is running (it usually starts after install).
3. Open PowerShell and pull a CPU-friendly model:
     ollama pull llama3.2:3b
4. Confirm the model is listed:
     ollama list
5. Restart this application.

This app never sends documents to a paid or cloud LLM API.
""".strip()

JSON_HINT = (
    "Return ONLY valid JSON matching the requested schema. "
    "Do not include markdown fences or commentary."
)


class OllamaUnavailable(RuntimeError):
    def __init__(self, message: str = SETUP_INSTRUCTIONS) -> None:
        super().__init__(message)


class OllamaService:
    def __init__(
        self,
        host: str = config.OLLAMA_HOST,
        model: str = config.OLLAMA_MODEL,
        timeout: float = config.OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "host": self.host,
            "configured_model": self.model,
            "reachable": False,
            "model_present": False,
            "models": [],
            "message": SETUP_INSTRUCTIONS,
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.host}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return info
        models = [m.get("name", "") for m in payload.get("models", [])]
        info["reachable"] = True
        info["models"] = models
        info["model_present"] = any(
            name == self.model or name.startswith(self.model + ":") or self.model.startswith(name)
            for name in models
        ) or self.model in models
        if not models:
            info["message"] = "Ollama is running but no models are installed.\n" + SETUP_INSTRUCTIONS
        elif not info["model_present"]:
            info["message"] = (
                f"Ollama is running, but '{self.model}' is not installed.\n"
                f"Installed: {', '.join(models) or '(none)'}\n"
                f"Run: ollama pull {self.model}"
            )
        else:
            info["message"] = f"Ollama ready with {self.model} (local only)."
        return info

    def ensure_ready(self) -> dict[str, Any]:
        info = self.health()
        if not info["reachable"] or not info["model_present"]:
            raise OllamaUnavailable(info["message"])
        return info

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.ensure_ready()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config.OLLAMA_TEMPERATURE,
                "num_ctx": config.OLLAMA_NUM_CTX,
                "num_predict": config.OLLAMA_NUM_PREDICT,
            },
        }
        if system:
            payload["system"] = system
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.host}/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama timed out after {self.timeout}s. Try a smaller model or shorter prompt."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed: {type(exc).__name__}") from exc
        text = data.get("response") or ""
        return text.strip()

    def generate_json(
        self,
        prompt: str,
        schema: Type[BaseModel],
        system: str | None = None,
        retries: int = config.JSON_RETRY_LIMIT,
    ) -> BaseModel:
        last_error = "unknown"
        request = prompt + "\n\n" + JSON_HINT
        extra_system = (system or "") + (
            "\nYou are a careful academic assistant. Never invent citations, "
            "page numbers, or quotations that were not supplied."
        )
        for attempt in range(retries + 1):
            raw = self.generate(request, system=extra_system)
            parsed = extract_json_object(raw)
            if parsed is None:
                last_error = "Model did not return JSON."
                request = (
                    prompt
                    + "\n\nYour previous reply was not valid JSON. Reply with a single JSON object only."
                )
                continue
            try:
                return schema.model_validate(parsed)
            except ValidationError as exc:
                last_error = str(exc.errors()[0].get("msg", "schema error"))
                request = (
                    prompt
                    + "\n\nThe JSON did not match the schema: "
                    + last_error
                    + ". Return corrected JSON only."
                )
        logger.info("JSON generation failed after retries")
        raise RuntimeError(
            f"The local model returned malformed output after retries ({last_error})."
        )


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = cleaned[start : end + 1]
    try:
        value = json.loads(snippet)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


_service: Optional[OllamaService] = None


def get_ollama() -> OllamaService:
    global _service
    if _service is None:
        _service = OllamaService()
    return _service
