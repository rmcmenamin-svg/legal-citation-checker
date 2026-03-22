#!/usr/bin/env python3
"""
Citation Checker — FastAPI server wrapping the real pipeline.
Port 4008.

Endpoints:
  POST /verify/text        — raw pasted text
  POST /verify/file        — DOCX / DOC / PDF upload
  POST /verify/corpus      — brief + corpus docs (record citation check)
  GET  /ui or /            — web UI
"""
import os
import sys
import shutil
import tempfile
import time
import uuid
import json as _json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent / "src"))

from legal_citation_checker.pipeline import CitationChecker
from legal_citation_checker.report import AuditReport
from legal_citation_checker.formatter import CitationFormatter

app = FastAPI(title="Citation Checker", version="3.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Load keys from ~/.openclaw/.env into os.environ at startup
def _load_openclaw_env() -> None:
    env_path = Path.home() / ".openclaw" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

_load_openclaw_env()

def _load_env_token() -> str:
    return os.environ.get("CL_TOKEN", "")

_CL_TOKEN = _load_env_token()

def _make_checker(verify_quotes: bool = False, cl_api_token: str = "") -> CitationChecker:
    return CitationChecker(
        verbose=False,
        max_workers=6,
        verify_quotes=verify_quotes,
        cl_api_token=cl_api_token or None,
    )

# Default checkers — built after _CL_TOKEN is resolved below at startup
_checker_fast: CitationChecker = None  # type: ignore
_checker_full: CitationChecker = None  # type: ignore

_sessions: dict = {}       # session_id -> {tmp_dir, brief_path, corpus_dir}

@app.on_event("startup")
async def _build_checkers():
    global _checker_fast, _checker_full, _CL_TOKEN
    _CL_TOKEN = _load_env_token()
    _checker_fast = CitationChecker(verbose=False, max_workers=6, verify_quotes=False, cl_api_token=_CL_TOKEN or None)
    _checker_full = CitationChecker(verbose=False, max_workers=6, verify_quotes=True,  cl_api_token=_CL_TOKEN or None)


# ── Whitespace normalization for .doc conversions ────────────────────────────

_NBSP_CHARS = str.maketrans({
    "\u00a0": " ",   # non-breaking space
    "\u202f": " ",   # narrow no-break space
    "\u2009": " ",   # thin space
    "\u2007": " ",   # figure space
    "\ufeff": "",    # BOM
    "\u00ad": "",    # soft hyphen
})

def _normalize_ws(text: str) -> str:
    return text.translate(_NBSP_CHARS)


# ── soffice .doc conversion ─────────────────────────────────────────────────

def _convert_doc_to_docx(doc_path: str) -> str:
    import subprocess
    out_dir = tempfile.mkdtemp()
    result = subprocess.run(
        ["soffice", "--headless", "--convert-to", "docx", "--outdir", out_dir, doc_path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"soffice conversion failed: {result.stderr.strip()}")
    converted = Path(out_dir) / f"{Path(doc_path).stem}.docx"
    if not converted.exists():
        raise RuntimeError(f"soffice did not produce expected output: {converted}")
    return str(converted)


# ── Text → temp DOCX (so process_document gets full pipeline) ───────────────

def _text_to_docx(text: str) -> str:
    """Write plain text to a temp .docx so process_document can run the full pipeline."""
    import docx as _docx
    doc = _docx.Document()
    for para in text.split("\n"):
        doc.add_paragraph(para)
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(tmp.name)
    return tmp.name


# ── Report serialization ─────────────────────────────────────────────────────

def _report_to_dict(report: AuditReport) -> dict:
    d = report.to_dict()
    d.update(d.pop("summary", {}))
    return d


def _record_results_to_list(record_results) -> list:
    out = []
    for rc, rv in record_results:
        out.append({
            "document_label": rc.document_label,
            "document_type": rc.document_type,
            "page_ref": rc.page_ref,
            "line_ref": rc.line_ref,
            "paragraph_ref": rc.paragraph_ref,
            "quoted_text": rc.quoted_text,
            "context": rc.context,
            "raw_text": rc.raw_text,
            "status": rv.status,
            "confidence": rv.confidence,
            "evidence": rv.evidence,
            "matched_document": rv.matched_document,
            "matched_text": rv.matched_text,
            "suggested_location": rv.suggested_location,
            "quote_similarity": rv.quote_similarity,
        })
    return out


# ── Endpoints ────────────────────────────────────────────────────────────────

class TextRequest(BaseModel):
    text: str
    verify_quotes: bool = False
    cl_api_token: str = ""
    formatter_style: str = "auto"  # "auto", "bluebook", "csm"


def _apply_formatter_style(checker: CitationChecker, style: str):
    if style and style != "auto":
        checker._formatter = CitationFormatter(style=style)


@app.post("/verify/text")
async def verify_text(req: TextRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "text is required")
    checker = _make_checker(req.verify_quotes, req.cl_api_token) if req.cl_api_token else (
        _checker_full if req.verify_quotes else _checker_fast
    )
    _apply_formatter_style(checker, req.formatter_style)
    tmp = None
    try:
        tmp = _text_to_docx(text)
        report = checker.process_document(Path(tmp))
        d = _report_to_dict(report)
        d["_raw"] = {
            "markdown": report.to_string("markdown"),
            "json": report.to_string("json"),
        }
        return d
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


@app.post("/verify/file")
async def verify_file(
    file: UploadFile = File(...),
    verify_quotes: bool = Form(False),
    cl_api_token: str = Form(""),
    formatter_style: str = Form("auto"),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".doc", ".docx", ".pdf"):
        raise HTTPException(400, "Only .doc, .docx, and .pdf files are supported")

    checker = _make_checker(verify_quotes, cl_api_token) if cl_api_token else (
        _checker_full if verify_quotes else _checker_fast
    )
    _apply_formatter_style(checker, formatter_style)
    converted_path = None

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        process_path = tmp_path
        if suffix == ".doc":
            converted_path = _convert_doc_to_docx(tmp_path)
            from legal_citation_checker.extractors import extract_docx_text
            raw = extract_docx_text(Path(converted_path))
            clean_text = _normalize_ws(raw.full_text)
            clean_docx = _text_to_docx(clean_text)
            if converted_path and os.path.exists(converted_path):
                os.unlink(converted_path)
            converted_path = clean_docx
            process_path = converted_path

        report = checker.process_document(Path(process_path))
        d = _report_to_dict(report)
        d["_raw"] = {
            "markdown": report.to_string("markdown"),
            "json": report.to_string("json"),
        }
        return d
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp_path)
        if converted_path and os.path.exists(converted_path):
            os.unlink(converted_path)


@app.post("/verify/corpus")
async def verify_corpus(
    brief: UploadFile = File(...),
    corpus_files: list[UploadFile] = File(...),
    include_caselaw: bool = Form(True),
):
    """Verify record citations in a brief against a set of corpus documents."""
    brief_suffix = Path(brief.filename).suffix.lower()
    if brief_suffix not in (".doc", ".docx", ".pdf"):
        raise HTTPException(400, "Brief must be .doc, .docx, or .pdf")

    tmp_dir = tempfile.mkdtemp()
    brief_path = None
    converted_brief = None

    try:
        # Save brief
        brief_path = os.path.join(tmp_dir, "brief" + brief_suffix)
        with open(brief_path, "wb") as f:
            f.write(await brief.read())

        # Convert .doc brief if needed
        if brief_suffix == ".doc":
            converted_brief = _convert_doc_to_docx(brief_path)
            brief_path = converted_brief

        # Save corpus files
        corpus_dir = os.path.join(tmp_dir, "corpus")
        os.makedirs(corpus_dir)
        for cf in corpus_files:
            cf_suffix = Path(cf.filename).suffix.lower()
            safe_name = cf.filename.replace("/", "_").replace("\\", "_")
            dest = os.path.join(corpus_dir, safe_name)
            with open(dest, "wb") as f:
                f.write(await cf.read())
            # Convert .doc corpus files
            if cf_suffix == ".doc":
                converted = _convert_doc_to_docx(dest)
                os.rename(converted, dest.replace(".doc", ".docx"))
                os.unlink(dest)

        result = _checker_fast.process_with_corpus(
            brief_path=Path(brief_path),
            corpus_dir=Path(corpus_dir),
            include_caselaw=include_caselaw,
        )

        caselaw = result.get("caselaw_report")
        return {
            "brief": brief.filename,
            "corpus_documents": result["corpus_documents"],
            "processing_seconds": round(result["processing_seconds"], 2),
            "record_summary": result["record_summary"],
            "record_citations": _record_results_to_list(result["record_results"]),
            "floating_quotes": result["floating_quotes"],
            "binding_summary": result["binding_summary"],
            "caselaw_report": _report_to_dict(caselaw) if caselaw else None,
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/corpus/prepare")
async def corpus_prepare(
    brief: UploadFile = File(...),
    corpus_files: list[UploadFile] = File(...),
):
    """Phase 1: Save files, index corpus, extract record citations from brief.

    Returns session_id, logs, documents info, and citation groups so the UI
    can show a confirmation step before running the full verification.
    """
    brief_suffix = Path(brief.filename).suffix.lower()
    if brief_suffix not in (".doc", ".docx", ".pdf"):
        raise HTTPException(400, "Brief must be .doc, .docx, or .pdf")

    tmp_dir = tempfile.mkdtemp()
    logs = []

    try:
        # Save brief
        brief_path = os.path.join(tmp_dir, "brief" + brief_suffix)
        with open(brief_path, "wb") as f:
            f.write(await brief.read())

        # Convert .doc brief if needed
        if brief_suffix == ".doc":
            converted_brief = _convert_doc_to_docx(brief_path)
            brief_path = converted_brief
            logs.append(f"Converted brief {brief.filename} to .docx")

        # Save corpus files
        corpus_dir = os.path.join(tmp_dir, "corpus")
        os.makedirs(corpus_dir)
        for cf in corpus_files:
            cf_suffix = Path(cf.filename).suffix.lower()
            safe_name = cf.filename.replace("/", "_").replace("\\", "_")
            dest = os.path.join(corpus_dir, safe_name)
            with open(dest, "wb") as f:
                f.write(await cf.read())
            # Convert .doc corpus files
            if cf_suffix == ".doc":
                converted = _convert_doc_to_docx(dest)
                new_dest = dest[:-4] + ".docx"
                os.rename(converted, new_dest)
                os.unlink(dest)
                logs.append(f"Converted {cf.filename} to .docx")

        # Index each corpus file and collect document metadata
        from legal_citation_checker.corpus_index import _ingest_document
        documents = []
        for fname in os.listdir(corpus_dir):
            fpath = Path(corpus_dir) / fname
            if not fpath.is_file():
                continue
            try:
                doc = _ingest_document(fpath)
                documents.append({
                    "filename": fname,
                    "detected_label": doc.label,
                    "detected_type": doc.document_type,
                    "page_count": doc.page_count,
                })
                logs.append(f"Indexed {fname}: label={doc.label!r}, type={doc.document_type}, pages={doc.page_count}")
            except Exception as exc:
                logs.append(f"Warning: could not index {fname}: {exc}")

        # Extract record citations from the brief
        from legal_citation_checker.extractors import extract_pdf_text, extract_docx_text
        from legal_citation_checker.record_extractor import extract_record_citations

        brief_p = Path(brief_path)
        if brief_p.suffix.lower() == ".pdf":
            brief_doc_text = extract_pdf_text(brief_p)
        else:
            brief_doc_text = extract_docx_text(brief_p)

        char_count = len(brief_doc_text.full_text.strip())
        logs.append(f"Brief text extracted: {char_count} characters across {len(brief_doc_text.paragraphs)} pages/paragraphs")
        if char_count < 200:
            logs.append("WARNING: Very little text extracted from brief — file may be scanned/image-based. Check that OCR is running.")

        record_cites = extract_record_citations(brief_doc_text)
        logs.append(f"Extracted {len(record_cites)} record citation(s) from brief")

        # Collect unique document labels referenced in the brief
        unique_labels: dict = {}  # document_label -> [raw_text examples]
        for rc in record_cites:
            label = rc.document_label or "Unknown"
            raw = rc.raw_text or ""
            if label not in unique_labels:
                unique_labels[label] = []
            if raw and raw not in unique_labels[label]:
                unique_labels[label].append(raw)

        logs.append(f"Found {len(unique_labels)} unique document reference(s) in brief")

        # Store session
        session_id = str(uuid.uuid4())
        _sessions[session_id] = {
            "tmp_dir": tmp_dir,
            "brief_path": brief_path,
            "corpus_dir": corpus_dir,
        }

        return {
            "session_id": session_id,
            "logs": logs,
            "documents": documents,
            "citation_labels": {k: v[:6] for k, v in sorted(unique_labels.items())},
        }

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


@app.post("/corpus/run")
async def corpus_run(
    session_id: str = Form(...),
    label_map: str = Form("{}"),
    include_caselaw: bool = Form(True),
    verify_quotes: bool = Form(False),
):
    """Phase 2: Run full corpus verification using a confirmed label map."""
    session = _sessions.pop(session_id, None)
    if session is None:
        raise HTTPException(404, "Session not found or already used")

    tmp_dir = session["tmp_dir"]
    brief_path = session["brief_path"]
    corpus_dir = session["corpus_dir"]

    try:
        # Parse label map
        try:
            parsed_label_map: dict = _json.loads(label_map)
        except Exception:
            parsed_label_map = {}

        # Create labeled_dir: copy each file using its assigned citation label as filename.
        # parsed_label_map is {citation_label -> original_filename}
        import re as _re
        labeled_dir = os.path.join(tmp_dir, "labeled")
        os.makedirs(labeled_dir)

        assigned_files: set = set()
        for citation_label, fname in parsed_label_map.items():
            if not fname or fname == "__none__":
                continue
            src = os.path.join(corpus_dir, fname)
            if not os.path.isfile(src):
                continue
            suffix = Path(fname).suffix
            safe_label = _re.sub(r'[/\\:*?"<>|]', "_", citation_label).strip() or Path(fname).stem
            dest = os.path.join(labeled_dir, safe_label + suffix)
            shutil.copy2(src, dest)
            assigned_files.add(fname)

        result = _checker_full.process_with_corpus(
            brief_path=Path(brief_path),
            corpus_dir=Path(labeled_dir),
            include_caselaw=include_caselaw,
        )

        caselaw = result.get("caselaw_report")
        return {
            "brief": Path(brief_path).name,
            "corpus_documents": result["corpus_documents"],
            "processing_seconds": round(result["processing_seconds"], 2),
            "record_summary": result["record_summary"],
            "record_citations": _record_results_to_list(result["record_results"]),
            "floating_quotes": result["floating_quotes"],
            "binding_summary": result["binding_summary"],
            "caselaw_report": _report_to_dict(caselaw) if caselaw else None,
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)



@app.get("/config")
async def config():
    """Return server-side defaults for the UI."""
    return {
        "cl_token": _CL_TOKEN,
        "verify_quotes_default": True,
    }

@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.2.0"}


_UI_PATH = Path(__file__).parent / "ui.html"

@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def ui():
    return _UI_PATH.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4008, reload=False)
