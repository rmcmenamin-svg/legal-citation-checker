"""Tier 5 escalation: Westlaw KeyCite and Lexis Shepardize.

Used only when all other verification tiers fail to reach a conclusion.
Alternates between Westlaw and Lexis to keep both sessions warm without
burning searches. Capped at MAX_ESCALATIONS_PER_RUN per pipeline run.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote_plus

logger = logging.getLogger("legal_citation_checker")

# Hard cap — won't escalate more than this per run
MAX_ESCALATIONS_PER_RUN = 5

# Session state files
_WESTLAW_SESSION = Path.home() / ".agent-browser" / "westlaw-session.json"
_LEXIS_SESSION   = Path.home() / ".agent-browser" / "lexis-session.json"

# Named session for Lexis — isolates it from other agents sharing the default daemon
_LEXIS_SESSION_NAME = "lexis-checker"

# Module-level state — persists within a single server/process lifetime
_escalation_count = 0   # total escalations this run
_next_service = "lexis"  # default to Lexis; Westlaw requires frequent MFA re-auth


def _restart_with_state(state: Path, timeout: int = 10) -> None:
    """Close any running daemon and reopen with the given state file."""
    # Close silently — ignore errors if no daemon is running
    subprocess.run("agent-browser close", shell=True, capture_output=True, timeout=timeout)
    # Small delay to ensure the daemon process exits cleanly
    import time
    time.sleep(1)


def _ab(args: str, state: Optional[Path] = None, session: Optional[str] = None, timeout: int = 20) -> Tuple[int, str]:
    """Run a single agent-browser command, return (returncode, output)."""
    state_flag = f"--state {state}" if state else ""
    session_flag = f"--session {session}" if session else ""
    cmd = f"agent-browser {session_flag} {state_flag} {args}"
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except Exception as exc:
        return 1, str(exc)


def _snapshot(state: Optional[Path] = None, session: Optional[str] = None) -> str:
    """Return the current page accessibility snapshot."""
    _, out = _ab("snapshot", state=state, session=session, timeout=25)
    return out


def _session_valid(snapshot_text: str, service: str) -> bool:
    """Check whether the snapshot indicates an active logged-in session.

    Uses negative detection (no login form visible) rather than positive
    detection (specific UI element), because we land on citation/content pages
    where search bars or specific UI chrome may not appear in the snapshot.
    """
    snap_lower = snapshot_text.lower()
    if service == "westlaw":
        # Logged out: Westlaw or Thomson Reuters login forms
        logged_out = (
            "sign in to westlaw" in snap_lower
            or "signon.thomsonreuters.com" in snap_lower
            or ('textbox "username"' in snap_lower and 'button "sign in"' in snap_lower)
            or ('textbox "email"' in snap_lower and 'button "sign in"' in snap_lower)
        )
        return not logged_out
    else:  # lexis
        # Logged out: Lexis sign-in page
        logged_out = (
            "sign in" in snap_lower and 'textbox "id"' in snap_lower
            or "signin.lexisnexis.com" in snap_lower
        )
        return not logged_out


def westlaw_keycite(citation_text: str) -> Tuple[str, str, Optional[str]]:
    """KeyCite a citation on Westlaw.

    Returns (status, evidence, source_url) where status is one of:
      'verified'      — case found, no negative treatment
      'caution'       — case found, yellow flag (some negative treatment)
      'negative'      — case found, red flag (overruled/reversed)
      'not_found'     — Westlaw does not have this citation
      'error'         — session/browser error
    """
    if not _WESTLAW_SESSION.exists():
        return ("error", "No Westlaw session file found.", None)

    # Restart default daemon with Westlaw session so --state cookies are loaded.
    # Westlaw uses the default session (no named session) since it's rarely used.
    _restart_with_state(_WESTLAW_SESSION)

    # Navigate directly to the citation
    cite_url = f"https://1.next.westlaw.com/Link/Document/FullText?cite={quote_plus(citation_text)}"
    rc, _ = _ab(f'open "{cite_url}"', state=_WESTLAW_SESSION, timeout=30)
    _ab("wait 4000", timeout=10)

    snapshot = _snapshot(state=_WESTLAW_SESSION)

    # Session check
    if not _session_valid(snapshot, "westlaw"):
        logger.debug("Westlaw session appears expired — skipping escalation")
        return ("error", "Westlaw session expired. Re-authenticate and retry.", None)

    # Parse KeyCite flag
    snap_lower = snapshot.lower()

    if "red flag" in snap_lower or "red keycite" in snap_lower:
        flag = "negative"
        evidence = f"Westlaw KeyCite RED FLAG — case has serious negative treatment (overruled or reversed)."
    elif "yellow flag" in snap_lower or "yellow keycite" in snap_lower:
        flag = "caution"
        evidence = f"Westlaw KeyCite YELLOW FLAG — case has some negative treatment (distinguished or criticized)."
    elif "blue flag" in snap_lower:
        flag = "verified"
        evidence = "Westlaw KeyCite BLUE FLAG — case found, citing references only, no negative treatment."
    elif "no negative treatment" in snap_lower or "keycite" in snap_lower:
        flag = "verified"
        evidence = "Westlaw KeyCite — case found, no negative treatment."
    elif "no document found" in snap_lower or "no results" in snap_lower or "0 results" in snap_lower:
        flag = "not_found"
        evidence = "Westlaw KeyCite — citation not found in Westlaw database."
    else:
        # If the page loaded something but we can't parse the flag,
        # check if it at least looks like a case page
        if any(w in snap_lower for w in ("opinion", "court of appeals", "supreme court", "district court", "cal.", "f.2d", "f.3d", "f.4th", "u.s.")):
            flag = "verified"
            evidence = "Westlaw — case page found (KeyCite flag status unclear from snapshot)."
        else:
            flag = "error"
            evidence = "Westlaw — could not parse result page."

    # Save session
    _ab("state save ~/.agent-browser/westlaw-session.json", timeout=10)

    return (flag, evidence, cite_url)


def lexis_shepardize(citation_text: str) -> Tuple[str, str, Optional[str]]:
    """Search for a citation on Lexis+ using the Protégé search bar.

    Submits the citation text directly (not as an AI question) so Lexis
    searches its database and returns real documents.  If the citation is
    fabricated Protégé responds with "could not be confirmed" and flags
    it as an "unlinked citation" — both reliably detectable strings.

    Returns (status, evidence, source_url).
    """
    if not _LEXIS_SESSION.exists():
        return ("error", "No Lexis session file found.", None)

    # Use a named session to isolate from other agents using the default daemon.
    # Load cookies from the saved state file on first open.
    _ab(
        'open "https://plus.lexis.com/firsttime/"',
        state=_LEXIS_SESSION,
        session=_LEXIS_SESSION_NAME,
        timeout=30,
    )
    _ab("wait 5000", session=_LEXIS_SESSION_NAME, timeout=10)

    snapshot = _snapshot(session=_LEXIS_SESSION_NAME)

    if not _session_valid(snapshot, "lexis"):
        logger.debug("Lexis session appears expired — skipping escalation")
        return ("error", "Lexis session expired. Re-authenticate and retry.", None)

    # Find the bottom "Ask a legal question" textbox (the search bar, not the
    # conversation history input at the top).  Use _find_ref_last to get the
    # last matching textbox on the page.
    textbox_ref = (
        _find_ref_last(snapshot, r'textbox.*ask a legal question')
        or _find_ref_last(snapshot, r'textbox.*enter conversation terms')
        or _find_ref_last(snapshot, r'textbox')
    )

    if not textbox_ref:
        return ("error", "Could not find Lexis search textbox in snapshot.", None)

    # Click to focus then type via keyboard — fill() alone doesn't enable Submit.
    _ab(f"click {textbox_ref}", session=_LEXIS_SESSION_NAME, timeout=10)
    _ab(f'keyboard type "{citation_text}"', session=_LEXIS_SESSION_NAME, timeout=10)
    _ab("wait 500", session=_LEXIS_SESSION_NAME, timeout=5)

    # Re-snapshot to get the now-enabled Submit button ref.
    snapshot2 = _snapshot(session=_LEXIS_SESSION_NAME)
    submit_ref = _find_ref(snapshot2, r'button.*submit')

    if submit_ref:
        _ab(f"click {submit_ref}", session=_LEXIS_SESSION_NAME, timeout=10)
    else:
        _ab("press Enter", session=_LEXIS_SESSION_NAME, timeout=10)

    # Wait for Protégé to complete its response.
    _ab("wait 12000", session=_LEXIS_SESSION_NAME, timeout=18)

    result_snapshot = _snapshot(session=_LEXIS_SESSION_NAME)
    snap_lower = result_snapshot.lower()

    # Primary not-found signals (reliable — Protégé uses these when it cannot
    # locate the citation in the Lexis database).
    if (
        "could not be confirmed" in snap_lower
        or "unlinked citation" in snap_lower
        or "could not be verified in our database" in snap_lower
        or "not found" in snap_lower
        or "could not locate" in snap_lower
        or "no results" in snap_lower
    ):
        flag = "not_found"
        evidence = "Lexis — citation could not be confirmed in Lexis database (unlinked citation)."
    elif "red stop" in snap_lower or "overruled" in snap_lower:
        flag = "verified"
        evidence = "Lexis — case found; Shepard's RED STOP SIGN (negative treatment — overruled or reversed)."
    elif "yellow triangle" in snap_lower or "distinguished" in snap_lower:
        flag = "verified"
        evidence = "Lexis — case found; Shepard's YELLOW TRIANGLE (distinguished or criticized)."
    elif "green diamond" in snap_lower or "positive treatment" in snap_lower:
        flag = "verified"
        evidence = "Lexis — case found; Shepard's GREEN DIAMOND (positive treatment, still good law)."
    elif "blue circle" in snap_lower or "citing references" in snap_lower:
        flag = "verified"
        evidence = "Lexis — case found; Shepard's BLUE CIRCLE (no negative treatment)."
    elif any(w in snap_lower for w in ("good law", "still valid", "affirmed", "the court held", "opinion", "response completed")):
        flag = "verified"
        evidence = "Lexis Protégé — citation found and discussed as valid authority."
    else:
        flag = "error"
        evidence = "Lexis — could not parse result from Protégé response."

    # Refresh saved session so cookies stay warm.
    _ab(f"state save {_LEXIS_SESSION}", session=_LEXIS_SESSION_NAME, timeout=10)

    return (flag, evidence, "https://plus.lexis.com/firsttime/")


def _find_ref(snapshot: str, pattern: str) -> Optional[str]:
    """Find the first element ref matching a pattern in a snapshot.

    Snapshot format uses [ref=eN] brackets; commands use @eN syntax.
    """
    lines = snapshot.splitlines()
    pat = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        if pat.search(line):
            ref_match = re.search(r"\[ref=(e\d+)\]", line)
            if ref_match:
                return f"@{ref_match.group(1)}"
    return None


def _find_ref_last(snapshot: str, pattern: str) -> Optional[str]:
    """Find the LAST element ref matching a pattern in a snapshot.

    Used to find the bottom search textbox rather than the first one
    (conversation history input) on the Lexis Protégé page.
    """
    lines = snapshot.splitlines()
    pat = re.compile(pattern, re.IGNORECASE)
    result = None
    for line in lines:
        if pat.search(line):
            ref_match = re.search(r"\[ref=(e\d+)\]", line)
            if ref_match:
                result = f"@{ref_match.group(1)}"
    return result


def escalate_citation(citation_text: str) -> Tuple[str, str, Optional[str], str]:
    """Escalate a single citation to Westlaw or Lexis.

    Alternates services and enforces MAX_ESCALATIONS_PER_RUN.

    Returns (status, evidence, source_url, service_used).
    status values: 'verified', 'caution', 'negative', 'not_found', 'error', 'skipped'
    """
    global _escalation_count, _next_service

    if _escalation_count >= MAX_ESCALATIONS_PER_RUN:
        return (
            "skipped",
            f"Escalation cap reached ({MAX_ESCALATIONS_PER_RUN} per run). Verify manually.",
            None,
            "none",
        )

    service = _next_service
    _escalation_count += 1
    _next_service = "lexis" if service == "westlaw" else "westlaw"

    logger.debug("Escalating '%s' to %s (escalation %d/%d)", citation_text, service, _escalation_count, MAX_ESCALATIONS_PER_RUN)

    if service == "westlaw":
        status, evidence, url = westlaw_keycite(citation_text)
    else:
        status, evidence, url = lexis_shepardize(citation_text)

    return (status, evidence, url, service)


def reset_escalation_counter() -> None:
    """Reset counter at the start of a new document run."""
    global _escalation_count
    _escalation_count = 0
