"""Application configuration. All inference stays on localhost."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
INDEX_DIR = DATA_DIR / "indexes"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT_DIR / "outputs"))
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "app.db"))
MODEL_CACHE_DIR = DATA_DIR / "model_cache"
SAMPLE_DIR = DATA_DIR / "sample"

for _path in (DATA_DIR, UPLOAD_DIR, INDEX_DIR, OUTPUT_DIR, MODEL_CACHE_DIR):
    _path.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODEL_CACHE_DIR))
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR / "hf"))

APP_NAME = "Agentic AI-Based Scheme and Solutions Generator"
APP_SHORT_NAME = "EvalScheme Generator"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "768"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
TOP_K = int(os.getenv("TOP_K", "5"))
RETRIEVAL_MIN_SCORE = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.32"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "110"))

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
UPLOAD_FILE_TYPES = [
    "pdf",
    "docx",
    "png",
    "jpg",
    "jpeg",
    "tif",
    "tiff",
    "webp",
    "bmp",
]

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}
APP_USERNAME = os.getenv("APP_USERNAME", "faculty")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
JSON_RETRY_LIMIT = int(os.getenv("JSON_RETRY_LIMIT", "2"))

DEFAULT_BIND_ADDRESS = "127.0.0.1"
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
