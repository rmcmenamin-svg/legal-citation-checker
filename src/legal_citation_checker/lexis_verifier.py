"""
Lexis+ deep citation verification via agent-browser.

For each case-law citation in a brief:
  1. Opens Lexis+ Protégé AI (session-first, falls back to error)
  2. Asks for the verbatim case text at the cited page
  3. Screenshots the full Protégé response
  4. Computes similarity between the response and any quoted text
  5. Returns verdict + screenshot (base64 PNG) + extracted text

Always screenshots regardless of whether a quote is present — the attorney
gets a visual record of what Lexis says the cited page actually contains.
"""

from __future__ import annotations

import base64
import difflib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

LEXIS_SESSION = Path.home() / ".agent-browser" / "lexis-session.json"
LEXIS_URL = "https://plus.lexis.com/aiassistant"


@dataclass
class LexisVerificationResult:
    citation: str
    case_name: str
    pincite: Optional[str]
    quoted_text: Optional[str]
    screenshot_b64: Optional[str]   # base64 PNG of Protégé response
    extracted_text: Optional[str]   # text from the response page (truncated)
    verdict: str                    # Verified | Misquoted | Retrieved | Error | Session Error
    similarity: float               # 0.0–1.0 (meaningful only when quoted_text present)
    message: str
    index: int = 0


# ── Agent-browser subprocess helpers ──────────────────────────────────────────

def _cmd(*args, timeout: int = 90) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["agent-browser"] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except FileNotFoundError:
        return 1, "agent-browser not installed"


def _find_ref(snapshot: str, *patterns: str) -> Optional[str]:
    """Find the first @eN ref in snapshot whose line matches any pattern."""
    for line in snapshot.splitlines():
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE):
                m = re.match(r"\s*(@e\d+)", line)
                if m:
                    return m.group(1)
    return None


def _screenshot_b64(path: str) -> Optional[str]:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode()
    except Exception:
        return None


# ── Text similarity ────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize text for comparison: collapse whitespace, strip CA line numbers."""
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\n\s*\d{1,2}\s+", " ", text)  # strip embedded line numbers
    return " ".join(text.lower().split())


def _similarity(needle: str, haystack: str) -> float:
    n, h = _normalize(needle), _normalize(haystack)
    if n in h:
        return 1.0
    # Core match (strip surrounding punctuation/quotes)
    core = re.sub(r'^["\'\s]+|["\'\s.,;:!?]+$', '', n)
    if core and len(core) >= 5 and core in h:
        return 0.95
    # Sliding window fuzzy match over haystack
    if not n or not h:
        return 0.0
    nl = len(n)
    best = 0.0
    step = max(1, nl // 4)
    for i in range(0, max(1, len(h) - nl + 1), step):
        window = h[i: i + nl + 20]
        ratio = difflib.SequenceMatcher(None, n, window).ratio()
        if ratio > best:
            best = ratio
    return best


# ── LexisVerifier ──────────────────────────────────────────────────────────────

class LexisVerifier:
    """One verifier instance per batch — reuses the same browser session."""

    def __init__(self):
        self._session_ok: Optional[bool] = None

    # ── Session ────────────────────────────────────────────────────────────────

    def _load_session(self) -> bool:
        if not LEXIS_SESSION.exists():
            return False
        code, _ = _cmd("--state", str(LEXIS_SESSION), "open", LEXIS_URL, timeout=30)
        if code != 0:
            return False
        _cmd("wait", "5000")
        _, snap = _cmd("snapshot")
        return "Ask a legal question" in snap

    def _ensure_session(self) -> bool:
        if self._session_ok is True:
            return True
        self._session_ok = self._load_session()
        return bool(self._session_ok)

    # ── Protégé AI interaction ─────────────────────────────────────────────────

    def _new_conversation(self):
        """Click 'New conversation' so each citation starts fresh."""
        _, snap = _cmd("snapshot", "-i")
        ref = _find_ref(snap, r"new conversation")
        if ref:
            _cmd("click", ref)
            _cmd("wait", "1500")

    def _submit_query(self, query: str) -> tuple[Optional[str], Optional[str]]:
        """Submit query to Protégé; wait for response; return (screenshot_b64, page_text)."""
        _, snap = _cmd("snapshot", "-i")
        textbox = _find_ref(snap, r"ask a legal question", r"textbox")
        if not textbox:
            return None, None

        _cmd("fill", textbox, query)
        _cmd("wait", "500")

        # Submit — press Enter if no visible submit button
        submit = _find_ref(snap, r'button.*submit|submit.*button')
        if submit:
            _cmd("click", submit)
        else:
            _cmd("press", "Enter")

        # Poll until "Generating" banner disappears (up to ~80 s)
        for _ in range(10):
            _cmd("wait", "8000")
            _, snap = _cmd("snapshot")
            if "Generating" not in snap:
                break

        _cmd("scroll", "up", "3000")
        _cmd("wait", "500")

        # Screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmppath = f.name
        _cmd("screenshot", "--full", tmppath)
        shot = _screenshot_b64(tmppath)
        try:
            Path(tmppath).unlink()
        except Exception:
            pass

        _, page_text = _cmd("get", "text", "body")
        return shot, page_text or None

    # ── Public verify ─────────────────────────────────────────────────────────

    def verify(
        self,
        citation_text: str,
        case_name: str,
        pincite: Optional[str],
        quoted_text: Optional[str],
        index: int = 0,
    ) -> LexisVerificationResult:
        base = dict(
            citation=citation_text,
            case_name=case_name,
            pincite=pincite,
            quoted_text=quoted_text,
            index=index,
        )

        if not self._ensure_session():
            return LexisVerificationResult(
                **base,
                screenshot_b64=None,
                extracted_text=None,
                verdict="Session Error",
                similarity=0.0,
                message=(
                    "Lexis+ session unavailable. "
                    "Run: agent-browser --state ~/.agent-browser/lexis-session.json "
                    "open https://plus.lexis.com and log in, then save the session."
                ),
            )

        self._new_conversation()

        # Build query
        page_clause = f"page {pincite} of" if pincite else "the relevant section of"
        if quoted_text:
            query = (
                f'Find the case {case_name} ({citation_text}). '
                f'Go to {page_clause} the opinion. '
                f'Verify whether this exact text appears and quote the verbatim passage: '
                f'"{quoted_text}"'
            )
        else:
            query = (
                f'Find the case {case_name} ({citation_text}). '
                f'Show me the verbatim text from {page_clause} the opinion.'
            )

        shot, page_text = self._submit_query(query)

        if not page_text:
            return LexisVerificationResult(
                **base,
                screenshot_b64=shot,
                extracted_text=None,
                verdict="Error",
                similarity=0.0,
                message="No text response received from Lexis+",
            )

        if quoted_text:
            sim = _similarity(quoted_text, page_text)
            if sim >= 0.90:
                verdict, msg = "Verified", f"Quoted text confirmed in Lexis+ ({sim:.0%} match)"
            elif sim >= 0.70:
                verdict, msg = "Verified", f"Quoted text found with minor variation ({sim:.0%} match)"
            else:
                verdict, msg = "Misquoted", f"Quoted text not found in Lexis+ response (similarity: {sim:.0%})"
        else:
            sim = 0.0
            verdict, msg = "Retrieved", "Case page retrieved from Lexis+"

        return LexisVerificationResult(
            **base,
            screenshot_b64=shot,
            extracted_text=page_text[:3000],
            verdict=verdict,
            similarity=sim,
            message=msg,
        )


# ── Batch entry point ─────────────────────────────────────────────────────────

def verify_batch(
    citations: List[dict],
    on_progress: Optional[Callable[[int, int, dict], None]] = None,
) -> List[dict]:
    """
    Verify a batch of case-law citations against Lexis+.

    Each dict must have:
      citation_text  — raw citation string
      case_name      — "Plaintiff v. Defendant" (may be empty string)
      pincite        — page within opinion, or None
      quoted_text    — quoted passage from brief, or None
      index          — original citation index (for UI correlation)

    Calls on_progress(done, total, result_dict) after each citation.
    Returns list of result dicts matching LexisVerificationResult fields.
    """
    verifier = LexisVerifier()
    results = []

    for i, cite in enumerate(citations):
        result = verifier.verify(
            citation_text=cite.get("citation_text", ""),
            case_name=cite.get("case_name", ""),
            pincite=cite.get("pincite"),
            quoted_text=cite.get("quoted_text"),
            index=cite.get("index", i),
        )
        rd = {
            "citation_text": result.citation,
            "case_name": result.case_name,
            "pincite": result.pincite,
            "quoted_text": result.quoted_text,
            "screenshot_b64": result.screenshot_b64,
            "extracted_text": result.extracted_text,
            "verdict": result.verdict,
            "similarity": result.similarity,
            "message": result.message,
            "index": result.index,
        }
        results.append(rd)
        if on_progress:
            on_progress(i + 1, len(citations), rd)

    return results
