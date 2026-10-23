"""Reproducible evaluation against held-out sample documents.

If Ollama is unavailable, this script still checks parsing, retrieval and
validation plumbing and records that live-model metrics were not measured.
It never fabricates an accuracy score.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from models.schemas import DocumentCategory, QuestionResult
from services.document_processor import extract_document
from services.embedding_service import EmbeddingService
from services.ollama_service import OllamaUnavailable, get_ollama
from services.question_parser import parse_question_paper
from services.retrieval_service import KnowledgeBase
from services.security_service import sha256_bytes
from services.workflow_orchestrator import process_question
from scripts.create_sample_docs import write_all


def _load(path: Path, category: DocumentCategory):
    return extract_document(path, path.name, category, sha256_bytes(path.read_bytes()))


def confusion(pairs: list[tuple[str, str]]) -> dict:
    labels = ["IN", "PARTIAL", "OUT", "UNCERTAIN"]
    matrix = {a: {b: 0 for b in labels} for a in labels}
    for gold, pred in pairs:
        matrix.setdefault(gold, {b: 0 for b in labels})
        matrix[gold][pred] = matrix[gold].get(pred, 0) + 1
    return matrix


def precision_recall(pairs: list[tuple[str, str]], positive: str) -> tuple[float, float]:
    tp = sum(1 for g, p in pairs if g == positive and p == positive)
    fp = sum(1 for g, p in pairs if g != positive and p == positive)
    fn = sum(1 for g, p in pairs if g == positive and p != positive)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return prec, rec


def main() -> None:
    paths = write_all()
    eval_dir = Path(paths["eval"])
    reference = json.loads((eval_dir / "reference.json").read_text(encoding="utf-8"))
    report: dict = {
        "live_model_used": False,
        "notes": [],
        "parsing": {},
        "retrieval": {},
        "generation": {},
    }

    paper_doc = _load(eval_dir / "question_paper.pdf", DocumentCategory.QUESTION_PAPER)
    syllabus = _load(eval_dir / "syllabus.docx", DocumentCategory.SYLLABUS)
    textbook = _load(eval_dir / "textbook.pdf", DocumentCategory.TEXTBOOK)
    paper = parse_question_paper(paper_doc, "Digital Logic Design", "CS301")
    report["parsing"] = {
        "questions_found": len(paper.questions),
        "expected": 3,
        "coverage_ok": len(paper.questions) >= 3,
        "printed_total": paper.printed_total_marks,
        "warnings": paper.parse_warnings,
    }

    embedder = EmbeddingService(allow_hash_fallback=True)
    try:
        embedder.load()
        if embedder.backend == "hash":
            report["notes"].append(
                "Sentence-Transformers model was not available; lexical/hash embeddings were used for retrieval checks."
            )
    except Exception as exc:  # noqa: BLE001
        report["notes"].append(f"Embedding load failed: {type(exc).__name__}")
        embedder = EmbeddingService(allow_hash_fallback=True)
        embedder.backend = "hash"

    kb = KnowledgeBase(index_dir=config.DATA_DIR / "eval_index", embedder=embedder)
    kb.add_document(syllabus, skip_if_unchanged=False, register_in_db=False)
    kb.add_document(textbook, skip_if_unchanged=False, register_in_db=False)
    hits = kb.search("full adder sum carry", min_score=0.0)
    report["retrieval"] = {
        "hit_count": len(hits),
        "top_filename": hits[0].chunk.filename if hits else None,
        "relevant_top": bool(hits) and (
            "adder" in hits[0].chunk.text.lower() or "boolean" in hits[0].chunk.text.lower()
        ),
    }

    ollama = get_ollama()
    health = ollama.health()
    report["ollama"] = {
        "reachable": health["reachable"],
        "model_present": health["model_present"],
        "message": health["message"].split("\n")[0],
    }
    if not health["model_present"]:
        report["notes"].append(
            "Live generation metrics were not measured because the configured Ollama model is unavailable."
        )
        report["notes"].append("No accuracy percentage is claimed.")
        _write(report)
        print(json.dumps(report, indent=2))
        return

    pairs = []
    marks_ok = 0
    evidence_ok = 0
    generated = 0
    try:
        ollama.ensure_ready()
        for q in paper.questions:
            if q.marks is None:
                continue
            q.marks_confirmed = True
            result: QuestionResult = process_question(
                "evaljob", q, paper, kb, ollama, syllabus_present=True
            )
            generated += 1
            pred = result.syllabus.status.value if result.syllabus else "UNCERTAIN"
            gold = "UNCERTAIN"
            for ref in reference["questions"]:
                if ref["contains"].lower() in q.text.lower():
                    gold = ref["expect_syllabus"]
                    if result.marks_match and result.marks == ref["marks"]:
                        marks_ok += 1
                    break
            pairs.append((gold, pred))
            if result.solution and any(e.verified for e in result.solution.evidence):
                evidence_ok += 1
        report["live_model_used"] = True
        report["generation"] = {
            "generated": generated,
            "syllabus_pairs": pairs,
            "confusion_matrix": confusion(pairs) if pairs else {},
            "IN_precision_recall": precision_recall(pairs, "IN") if pairs else None,
            "OUT_precision_recall": precision_recall(pairs, "OUT") if pairs else None,
            "marks_match_count": marks_ok,
            "outputs_with_verified_evidence": evidence_ok,
            "unresolved": generated - marks_ok,
        }
        report["notes"].append(
            "These figures are from a tiny synthetic set and are not an official accuracy claim."
        )
    except OllamaUnavailable as exc:
        report["notes"].append(str(exc).split("\n")[0])
    except Exception as exc:  # noqa: BLE001
        report["notes"].append(f"Live evaluation stopped: {type(exc).__name__}: {exc}")

    _write(report)
    print(json.dumps(report, indent=2))


def _write(report: dict) -> None:
    out = config.ROOT_DIR / "reports"
    out.mkdir(exist_ok=True)
    (out / "evaluation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
