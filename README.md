# Agentic AI-Based Scheme and Solutions Generator for Engineering Question Papers

Local desktop application that builds an evaluation scheme (solutions, step-wise marks, syllabus compliance and evidence) from a question paper, official syllabus, textbooks and notes. Inference uses **Ollama on this machine**. Uploaded documents are **not** sent to a paid or cloud LLM API.

This is a student project for a 16 GB RAM, CPU-only PC. It is **not** institutionally certified, production-hardened, or examination-board compliant.

## What it does

- Uploads PDF, DOCX, photos (PNG/JPG/TIF/WEBP/BMP), and photo-converted PDFs
- Extracts text (PyMuPDF / python-docx) with page numbers; local Tesseract OCR for photos and scanned/photo PDFs
- Parses questions such as `Q1(a)`, `Part A`, and internal `OR` choices
- **Does not invent printed marks**; you confirm missing or conflicting marks
- Builds a local RAG index (Sentence Transformers + FAISS if installed, otherwise NumPy cosine search)
- Runs a coordinated workflow: question analysis → syllabus label (IN / PARTIAL / OUT / UNCERTAIN) → solution → mark allocation → Python validation
- Faculty review: edit, comment, approve per question; whole-scheme approval only after validation
- Exports labelled DOCX, PDF and CSV (`DRAFT` vs `FACULTY-APPROVED`)
- Keeps original generated JSON and a separate reviewed copy

## Requirements

- Windows 10/11
- Python 3.11 (3.12 may work; 3.13 is untested for some wheels)
- [Ollama](https://ollama.com/download) for generation
- Required for photos / photo-PDFs: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- ~3–6 GB disk for a 3B model plus the MiniLM embedding model

Default local model: **`llama3.2:3b`** (instruction-tuned, CPU-feasible). Alternatives you can set in `.env`: `phi3:mini`, `qwen2.5:3b`.

## Windows install and run

In PowerShell, from this folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\create_sample_docs.py
```

If PowerShell blocks the venv script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Install Ollama, then:

```powershell
ollama pull llama3.2:3b
ollama list
```

For photos and camera-scan PDFs, install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki), then either add it to PATH or set:

```
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

in `.env`. On **New Evaluation**, keep OCR enabled and upload JPG/PNG pages (one photo per page) or a photo-PDF.

Start the UI **on localhost only**. Use the project virtual environment (not system Python):

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Or double-click `run.bat`. If you run `streamlit` from a global Python 3.13 install you will get errors such as `No module named 'docx'`.

Open http://127.0.0.1:8501

Copy `.env.example` to `.env` to change the model name, upload size or enable optional local username/password (`AUTH_ENABLED=true`).

## Tests and evaluation

```powershell
python -m pytest
python scripts\evaluate.py
```

`scripts\evaluate.py` compares the **held-out** set in `data/sample/eval/` with `data/sample/eval/reference.json`. The UI demo files in `data/sample/demo/` are separate. If Ollama is not running, the script still checks parsing/retrieval and **does not invent an accuracy number**.

## Demo walkthrough (synthetic CS301 papers)

1. Confirm Ollama is ready on the Dashboard.
2. New Evaluation → subject `Digital Logic Design`, code `CS301`.
3. Upload from `data\sample\demo\`:
   - `question_paper.pdf` as question paper
   - `syllabus.docx` as syllabus
   - `textbook.pdf` as textbook
   - `notes.docx` as study material
   - optional `previous_scheme.docx`
4. Extract, inspect text, confirm marks, start the workflow (several minutes on CPU).
5. Evaluation Results: read solutions, marking tables, syllabus labels and source pages.
6. Faculty Review: edit if needed, approve each question, then approve the scheme.
7. Export DOCX/PDF/CSV. Files go to `outputs\<job_id>\` and keep a DRAFT banner until approved.

Expected synthetic behaviour (for your own checking, not a published score): Q3 (quantum annealing) should not be confidently IN; Q1 De Morgan / binary conversion / adder / SRAM should be coverable from the syllabus.

## Privacy and security (honest limits)

Implemented:

- Local Ollama only; no cloud LLM fallback
- Streamlit bound to `127.0.0.1` by default; Streamlit usage stats disabled
- Uploads stored under `data/uploads/` with sanitized names; original files are not overwritten
- File type/size checks; PDF/DOCX signatures
- Parameterized SQLite
- Logs are truncated and do not write full papers or full answers
- Prompts wrap retrieved text as untrusted and tell the model to ignore embedded instructions
- Exports omit filesystem paths and secrets
- Optional basic password if `AUTH_ENABLED=true`

Not claimed:

- Production security, FERPA/GDPR certification, multi-tenant isolation, or exam-board approval
- Protection if you expose the port to the LAN/internet
- Guaranteed resistance to prompt injection from uploaded PDFs
- Deterministic model output

Treat real question papers as confidential. Do not commit them. `.gitignore` excludes uploads, indexes, databases, outputs and `.env`.

## Architecture

| Area | Module |
| --- | --- |
| UI | `app.py`, `ui/` |
| Ingestion | `services/document_processor.py` |
| Parsing | `services/question_parser.py` |
| RAG | `services/embedding_service.py`, `services/retrieval_service.py` |
| LLM | `services/ollama_service.py` |
| Agents | `agents/` (analysis, syllabus, solution, marks, validation) |
| Orchestration | `services/workflow_orchestrator.py` |
| Export | `services/export_service.py` |
| DB | `database/db.py` (SQLite) |

Fine-tuning, LoRA and training are **out of scope**. Faculty-approved rows can later be exported with:

```powershell
python scripts\export_training_dataset.py <job_id> -o outputs\training_dataset.json
```

Only **approved** items are written. Do not dump raw model drafts into a training set. A later fine-tuning phase would need human quality labels, de-duplication, versioning and a separate training environment — still local if you choose.

## Configuration defaults

| Setting | Default |
| --- | --- |
| Model | `llama3.2:3b` |
| Context / predict | 2048 / 768 |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (first run downloads into `data/model_cache`) |
| Top-k / min score | 5 / 0.32 |
| Max upload | 25 MB |

FAISS is optional. If `faiss-cpu` has no wheel for your Python, the app uses a NumPy inner-product index and says so on the Knowledge Base page.

## Limitations

- CPU 3B models make mistakes on derivations and can miss marks splits; validation will flag arithmetic, not technical correctness
- Citations are taken from retrieved chunks; the UI/validators reject invented quotes when they are not substrings of retrieved text, but the model can still be wrong
- Photos and scanned/photo PDFs need Tesseract; without it the app reports the problem instead of inventing text
- Diagrams are described in text, not drawn
- First embedding-model download needs network access; later runs are local
- One evaluation job at a time is recommended on 16 GB RAM

## Project layout

See the repository root: `app.py`, `agents/`, `services/`, `models/`, `database/`, `ui/`, `tests/`, `scripts/`, `data/sample/`, `outputs/`.
