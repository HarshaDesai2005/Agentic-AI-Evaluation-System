"""SQLite persistence with parameterized queries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    subject_name TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'unreviewed',
    paper_total_marks REAL,
    attempt_total_marks REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    category TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    extraction_status TEXT,
    is_scanned INTEGER DEFAULT 0,
    ocr_used INTEGER DEFAULT 0,
    extracted_preview TEXT,
    indexed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    generated_json TEXT NOT NULL,
    reviewed_json TEXT,
    status TEXT NOT NULL,
    faculty_comment TEXT DEFAULT '',
    approved INTEGER DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    category TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    chunk_count INTEGER DEFAULT 0,
    subject TEXT,
    stored_path TEXT,
    indexed_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def create_job(job_id: str, subject_name: str, subject_code: str) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id, subject_name, subject_code, status, approval_status, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', 'unreviewed', ?, ?)""",
            (job_id, subject_name, subject_code, _now(), _now()),
        )


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def insert_document(record: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, job_id, category, original_filename, stored_path, sha256,
                page_count, extraction_status, is_scanned, ocr_used,
                extracted_preview, indexed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"],
                record.get("job_id"),
                record["category"],
                record["original_filename"],
                record["stored_path"],
                record["sha256"],
                record.get("page_count", 0),
                record.get("extraction_status"),
                int(record.get("is_scanned", False)),
                int(record.get("ocr_used", False)),
                record.get("extracted_preview", ""),
                int(record.get("indexed", False)),
                _now(),
            ),
        )


def list_documents(job_id: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if job_id:
            rows = conn.execute(
                "SELECT * FROM documents WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def save_questions(job_id: str, questions: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM questions WHERE job_id = ?", (job_id,))
        for q in questions:
            conn.execute(
                "INSERT INTO questions (id, job_id, payload_json) VALUES (?, ?, ?)",
                (q["id"], job_id, json.dumps(q)),
            )


def load_questions(job_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM questions WHERE job_id = ?", (job_id,)
        ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]


def upsert_result(record: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO results
               (id, job_id, question_id, generated_json, reviewed_json, status,
                faculty_comment, approved, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 generated_json=excluded.generated_json,
                 reviewed_json=excluded.reviewed_json,
                 status=excluded.status,
                 faculty_comment=excluded.faculty_comment,
                 approved=excluded.approved,
                 error=excluded.error
            """,
            (
                record["id"],
                record["job_id"],
                record["question_id"],
                record["generated_json"],
                record.get("reviewed_json"),
                record["status"],
                record.get("faculty_comment", ""),
                int(record.get("approved", False)),
                record.get("error"),
            ),
        )


def list_results(job_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM results WHERE job_id = ?", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_result(result_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
        return dict(row) if row else None


def upsert_kb_document(record: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO kb_documents
               (id, filename, category, sha256, chunk_count, subject, stored_path, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sha256) DO UPDATE SET
                 chunk_count=excluded.chunk_count,
                 indexed_at=excluded.indexed_at
            """,
            (
                record["id"],
                record["filename"],
                record["category"],
                record["sha256"],
                record.get("chunk_count", 0),
                record.get("subject"),
                record.get("stored_path"),
                _now(),
            ),
        )


def list_kb_documents() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM kb_documents ORDER BY indexed_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_kb_by_hash(sha256: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM kb_documents WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return dict(row) if row else None


def delete_kb_document(doc_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM kb_documents WHERE id = ?", (doc_id,))


def clear_kb_documents() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM kb_documents")


init_db()
