"""Export faculty-approved examples only. Never dump raw AI drafts as training data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.export_service import export_training_dataset
from services.workflow_orchestrator import load_scheme


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("-o", "--output", default="outputs/training_dataset.json")
    args = parser.parse_args()
    payload = load_scheme(args.job_id)
    if not payload:
        raise SystemExit("Job not found.")
    rows = export_training_dataset(payload["scheme"], only_approved=True)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} approved example(s) to {path}")


if __name__ == "__main__":
    main()
