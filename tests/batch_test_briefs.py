#!/usr/bin/env python3
"""Batch test: run citation checker against all available test briefs.

Generates a summary report showing detection accuracy for each brief.
"""

import json
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from legal_citation_checker.pipeline import CitationChecker

# Known ground truth for the LLM-generated brief
LLM_BRIEF_TRUTH = {
    "REAL": [
        "389 U.S. 347",   # Katz v. United States
        "585 U.S. 296",   # Carpenter v. United States
        "573 U.S. 373",   # Riley v. California
        "442 U.S. 735",   # Smith v. Maryland
        "556 U.S. 332",   # Arizona v. Gant
        "437 U.S. 385",   # Mincey v. Arizona
        "489 U.S. 602",   # Skinner v. Railway Labor Executives
        "578 U.S. 330",   # Spokeo v. Robins
        "594 U.S. 413",   # TransUnion v. Ramirez
        "565 U.S. 400",   # United States v. Jones
    ],
    "FAKE": [
        "847 F.3d 1203",  # Thompson v. Digital Analytics
        "612 F. Supp. 3d 894",  # Rodriguez v. DataMine
        "923 F.3d 1108",  # Henderson v. Clearview
        "198 F. Supp. 3d 1142",  # Martinez v. Palantir
        "891 F.3d 445",   # Collins v. SafeTrack
        "756 F.3d 1087",  # Patterson v. United States
        "834 F.3d 921",   # Walker v. NSA
        "743 F. Supp. 3d 201",  # Chen v. FBI
    ],
}

# The FAKE briefs should be 100% fabricated
FAKE_BRIEF_CITATIONS = [
    "123 Cal.App.5th 456",
    "77 Cal.App.6th 777",
    "999 Cal. 888",
    "88 Cal.5th 1111",
    "303 Cal.App.5th 2222",
    "999 U.S. 123",
    "101 Cal.4th 555",
    "456 F.3d 789",
    "789 Cal.App.7th 333",
    "222 Cal.App.8th 444",
]


def run_brief(checker: CitationChecker, path: Path) -> dict:
    """Run checker on a single brief and return results."""
    start = time.time()
    report = checker.process_document(str(path))
    elapsed = time.time() - start

    results = {
        "file": path.name,
        "time_seconds": round(elapsed, 2),
        "total_citations": len(report.citations),
        "verified": [],
        "hallucinations": [],
        "needs_review": [],
        "skipped": [],
    }

    for audit in report.citations:
        entry = {
            "raw": audit.raw_citation[:80],
            "normalized": audit.normalized_citation or "",
        }
        entry["confidence"] = audit.confidence
        entry["source"] = audit.source
        entry["evidence"] = audit.evidence[:100] if audit.evidence else ""

        status = audit.status
        if status == "verified":
            results["verified"].append(entry)
        elif status == "hallucination":
            results["hallucinations"].append(entry)
        elif status == "needs_review":
            results["needs_review"].append(entry)
        else:
            results["skipped"].append(entry)

    return results


def print_brief_results(results: dict, ground_truth: str = None):
    """Pretty-print results for one brief."""
    name = results["file"]
    total = results["total_citations"]
    v = len(results["verified"])
    h = len(results["hallucinations"])
    nr = len(results["needs_review"])
    sk = len(results["skipped"])

    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"  Time: {results['time_seconds']}s | Citations: {total}")
    print(f"  Verified: {v} | Hallucination: {h} | Needs Review: {nr} | Skipped: {sk}")
    print(f"{'='*70}")

    if results["verified"]:
        print(f"\n  VERIFIED ({v}):")
        for c in results["verified"]:
            print(f"    ✅ {c['raw']}")
            if c.get("evidence"):
                print(f"       Evidence: {c['evidence']}")

    if results["hallucinations"]:
        print(f"\n  POTENTIAL HALLUCINATIONS ({h}):")
        for c in results["hallucinations"]:
            conf = c.get("confidence", "?")
            print(f"    🔴 {c['raw']}  (confidence: {conf}%)")

    if results["needs_review"]:
        print(f"\n  NEEDS REVIEW ({nr}):")
        for c in results["needs_review"]:
            print(f"    ⚠️  {c['raw']}")
            if c.get("evidence"):
                print(f"       Reason: {c['evidence']}")

    if results["skipped"]:
        print(f"\n  SKIPPED ({sk}):")
        for c in results["skipped"]:
            print(f"    ⏭️  {c['raw']}")


def evaluate_llm_brief(results: dict):
    """Compare LLM brief results against ground truth."""
    print(f"\n{'─'*70}")
    print("  GROUND TRUTH EVALUATION (LLM-generated brief)")
    print(f"{'─'*70}")

    verified_raws = [c["raw"] for c in results["verified"]]
    hallu_raws = [c["raw"] for c in results["hallucinations"]]
    review_raws = [c["raw"] for c in results["needs_review"]]

    # Check real citations
    real_found = 0
    real_missed = 0
    for cite in LLM_BRIEF_TRUTH["REAL"]:
        matched = any(cite in r for r in verified_raws)
        status = "✅ Correctly verified" if matched else "❌ MISSED (false negative)"
        if matched:
            real_found += 1
        else:
            real_missed += 1
        print(f"    REAL  {cite}: {status}")

    # Check fake citations
    fake_caught = 0
    fake_missed = 0
    for cite in LLM_BRIEF_TRUTH["FAKE"]:
        caught = any(cite in r for r in hallu_raws)
        flagged = any(cite in r for r in review_raws)
        if caught:
            status = "✅ Correctly flagged as hallucination"
            fake_caught += 1
        elif flagged:
            status = "⚠️  Flagged needs review (acceptable)"
            fake_caught += 1
        else:
            false_verified = any(cite in r for r in verified_raws)
            if false_verified:
                status = "❌ FALSE POSITIVE - verified a fake citation!"
                fake_missed += 1
            else:
                status = "❓ Not found in results"
                fake_missed += 1
        print(f"    FAKE  {cite}: {status}")

    total_real = len(LLM_BRIEF_TRUTH["REAL"])
    total_fake = len(LLM_BRIEF_TRUTH["FAKE"])
    print(f"\n  ACCURACY:")
    print(f"    Real citations correctly verified: {real_found}/{total_real} ({100*real_found//total_real}%)")
    print(f"    Fake citations caught:             {fake_caught}/{total_fake} ({100*fake_caught//total_fake}%)")
    if fake_missed:
        print(f"    ⚠️  {fake_missed} fake citation(s) slipped through!")
    if real_missed:
        print(f"    ⚠️  {real_missed} real citation(s) not verified (coverage gap)")


def main():
    checker = CitationChecker(verbose=False, request_timeout=10.0)

    # Collect all test briefs
    root = Path(__file__).resolve().parent.parent
    briefs = []

    # LLM-generated brief
    llm_brief = root / "tests" / "test_documents" / "llm_generated_brief.docx"
    if llm_brief.exists():
        briefs.append(("llm", llm_brief))

    # FAKE briefs
    fake_dir = root / "test_briefs"
    if fake_dir.exists():
        for f in sorted(fake_dir.glob("FAKE-*.docx")):
            briefs.append(("fake", f))

    # Delaware brief
    del_brief = root / "delaware_derivative_brief.docx"
    if del_brief.exists():
        briefs.append(("unknown", del_brief))

    # Other test docs
    test_docs = root / "tests" / "test_documents"
    for f in sorted(test_docs.glob("*.docx")):
        if f.name != "llm_generated_brief.docx":
            briefs.append(("test", f))

    print(f"Found {len(briefs)} test briefs to process.\n")

    all_results = []
    total_verified = 0
    total_hallu = 0
    total_review = 0
    total_skipped = 0
    total_citations = 0
    total_time = 0

    for brief_type, path in briefs:
        print(f"Processing: {path.name} ...", flush=True)
        try:
            results = run_brief(checker, path)
            all_results.append((brief_type, results))
            print_brief_results(results)

            if brief_type == "llm":
                evaluate_llm_brief(results)

            total_verified += len(results["verified"])
            total_hallu += len(results["hallucinations"])
            total_review += len(results["needs_review"])
            total_skipped += len(results["skipped"])
            total_citations += results["total_citations"]
            total_time += results["time_seconds"]
        except Exception as e:
            print(f"  ERROR processing {path.name}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n{'='*70}")
    print(f"  BATCH SUMMARY")
    print(f"{'='*70}")
    print(f"  Briefs processed:    {len(all_results)}")
    print(f"  Total time:          {total_time:.1f}s")
    print(f"  Total citations:     {total_citations}")
    print(f"  Verified:            {total_verified} ({100*total_verified//max(total_citations,1)}%)")
    print(f"  Hallucinations:      {total_hallu} ({100*total_hallu//max(total_citations,1)}%)")
    print(f"  Needs Review:        {total_review} ({100*total_review//max(total_citations,1)}%)")
    print(f"  Skipped:             {total_skipped} ({100*total_skipped//max(total_citations,1)}%)")

    # Save JSON results
    out_path = root / "memory" / "batch-test-full-results.json"
    out_path.parent.mkdir(exist_ok=True)
    json_data = []
    for brief_type, r in all_results:
        r["type"] = brief_type
        json_data.append(r)
    with open(out_path, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"\n  Full results saved to: {out_path}")


if __name__ == "__main__":
    main()
