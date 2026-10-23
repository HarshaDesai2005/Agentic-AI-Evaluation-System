from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel

from services.ollama_service import (
    OllamaService,
    OllamaUnavailable,
    extract_json_object,
)


class Tiny(BaseModel):
    answer: str


def test_extract_json_from_fences():
    raw = '```json\n{"answer": "ok"}\n```'
    assert extract_json_object(raw) == {"answer": "ok"}


def test_extract_json_embedded():
    raw = 'Sure.\n{"answer": "42", "extra": true}\nThanks'
    parsed = extract_json_object(raw)
    assert parsed["answer"] == "42"


def test_health_when_unreachable():
    svc = OllamaService(host="http://127.0.0.1:9")
    with patch("httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.side_effect = httpx.ConnectError("nope")
        client_cls.return_value = client
        info = svc.health()
    assert info["reachable"] is False
    assert "Ollama" in info["message"]


def test_generate_json_retries_then_errors():
    svc = OllamaService()
    with patch.object(svc, "ensure_ready", return_value={}), patch.object(
        svc, "generate", return_value="not json at all"
    ):
        with pytest.raises(RuntimeError, match="malformed"):
            svc.generate_json("prompt", Tiny, retries=1)


def test_unavailable_has_setup_text():
    err = OllamaUnavailable()
    assert "ollama pull" in str(err).lower()
