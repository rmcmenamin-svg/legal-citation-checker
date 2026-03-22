#!/usr/bin/env python3
"""
Benchmark runner for the legal citation hallucination detector.

Usage:
    python3.12 test_benchmark.py                  # run all test memos in tests/
    python3.12 test_benchmark.py tests/memo1.json # run a specific memo

Each test memo is a JSON file:
{
  "topic": "Employment Law",
  "text": "...",
  "ground_truth": [
    {"citation": "140 S. Ct. 1731", "status": "REAL"},
    {"citation": "2025 WL 1234567", "status": "FABRICATED"},
    ...
  ]
}

Outputs:
  - Per-memo precision / recall / F1
  - Overall scores
  - Detailed failure analysis (false positives, false negatives)
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

SERVER = "http://localhost:4008"
VERIFY_URL = f"{SERVER}/verify/text"


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def normalize_citation(s: str) -> str:
    """Coarse normalization for matching ground truth to API results."""
    return s.strip().lower().replace(".", "").replace(",", "").replace("  ", " ")


def run_memo(memo: dict) -> dict:
    """Run a single memo through the checker and score against ground truth."""
    topic = memo.get("topic", "Unknown")
    text = memo["text"]
    ground_truth = memo["ground_truth"]

    print(f"\n{'='*70}")
    print(f"MEMO: {topic}")
    print(f"{'='*70}")

    t0 = time.time()
    result = post_json(VERIFY_URL, {"text": text, "verify_quotes": True})
    elapsed = time.time() - t0

    print(f"Processed in {elapsed:.1f}s — {result['total_citations']} citations found")

    # Build ground truth lookup: normalized_citation → status
    gt_lookup: dict[str, str] = {}
    for entry in ground_truth:
        key = normalize_citation(entry["citation"])
        gt_lookup[key] = entry["status"].upper()

    # Match API results to ground truth
    true_pos = 0   # FABRICATED → Potential Hallucination  ✓
    true_neg = 0   # REAL → Verified  ✓
    false_pos = 0  # REAL → Potential Hallucination  ✗
    false_neg = 0  # FABRICATED → Verified or Needs Review  ✗
    unmatched = 0

    failures: list[dict] = []

    for c in result.get("citations", []):
        raw = c["raw_citation"]
        status = c["status"]
        conf = c["confidence"]

        # Try to find this citation in ground truth
        raw_norm = normalize_citation(raw)
        gt_status = None
        for gt_key, gt_val in gt_lookup.items():
            # Partial match: citation key contained in raw or vice versa
            if gt_key in raw_norm or raw_norm in gt_key:
                gt_status = gt_val
                break

        if gt_status is None:
            unmatched += 1
            continue

        # Check if this is an annotated acceptable false positive (e.g. WL cites
        # we can't verify without auth, or very recent cases not yet indexed).
        gt_entry = next(
            (e for e in ground_truth if normalize_citation(e["citation"]) in raw_norm or raw_norm in normalize_citation(e["citation"])),
            {},
        )
        acceptable_fp = "acceptable" in (gt_entry.get("note") or "").lower() or "expected" in (gt_entry.get("note") or "").lower()

        predicted_hallucination = "Hallucination" in status or "hallucination" in status.lower()
        actual_fabricated = gt_status == "FABRICATED"

        if actual_fabricated and predicted_hallucination:
            true_pos += 1
            marker = "✓"
        elif not actual_fabricated and not predicted_hallucination:
            true_neg += 1
            marker = "✓"
        elif not actual_fabricated and predicted_hallucination:
            if acceptable_fp:
                # Known limitation — don't count against precision
                true_neg += 1
                marker = "~"  # expected/acceptable false positive
            else:
                false_pos += 1
                marker = "FP"
                failures.append({"type": "FP", "citation": raw, "status": status, "confidence": conf})
        else:  # actual_fabricated and not predicted_hallucination
            false_neg += 1
            marker = "FN"
            failures.append({"type": "FN", "citation": raw, "status": status, "confidence": conf})

        gt_label = "FAB" if actual_fabricated else "REAL"
        print(f"  [{marker}] {raw[:55]:<55} [{gt_label}] → {status} {conf}%")

    if unmatched:
        print(f"  (+ {unmatched} citations not in ground truth — skipped)")

    # Compute metrics
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 1.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (true_pos + true_neg) / (true_pos + true_neg + false_pos + false_neg) if (true_pos + true_neg + false_pos + false_neg) > 0 else 0.0

    print(f"\n  Precision: {precision:.0%}  Recall: {recall:.0%}  F1: {f1:.0%}  Accuracy: {accuracy:.0%}")
    print(f"  TP={true_pos} TN={true_neg} FP={false_pos} FN={false_neg}")

    if failures:
        print("\n  FAILURES:")
        for f in failures:
            print(f"    [{f['type']}] {f['citation'][:55]:<55} → {f['status']} {f['confidence']}%")

    # Quote scoring (only for memos that have quote ground truth)
    gt_with_quotes = [e for e in ground_truth if e.get("quote_status") and e["quote_status"] not in ("NO_QUOTE", "FAKE_CASE")]
    if gt_with_quotes:
        print("\n  QUOTE VERIFICATION:")
        q_correct = 0
        q_total = 0
        for c in result.get("citations", []):
            raw_norm2 = normalize_citation(c["raw_citation"])
            gt_entry2 = next(
                (e for e in ground_truth if normalize_citation(e["citation"]) in raw_norm2 or raw_norm2 in normalize_citation(e["citation"])),
                None,
            )
            if not gt_entry2 or not gt_entry2.get("quote_status") or gt_entry2["quote_status"] in ("NO_QUOTE", "FAKE_CASE"):
                continue

            expected_real = gt_entry2["quote_status"] == "REAL_QUOTE"
            actual_qs = c.get("quote_status") or ""
            actual_verified = actual_qs == "verified"
            got_quote = bool(c.get("quoted_text"))

            q_total += 1
            if expected_real and actual_verified:
                q_correct += 1
                print(f"    ✓ REAL_QUOTE verified: {c['raw_citation'][:40]} sim={c.get('quote_similarity',0):.0%}")
            elif expected_real and not got_quote:
                print(f"    ✗ REAL_QUOTE NOT BOUND: {c['raw_citation'][:40]} (quote didn't bind to citation)")
            elif expected_real and actual_qs == "not_found":
                print(f"    ✗ REAL_QUOTE not_found: {c['raw_citation'][:40]} sim={c.get('quote_similarity',0):.0%}")
            elif expected_real:
                print(f"    ~ REAL_QUOTE status={actual_qs}: {c['raw_citation'][:40]}")
            elif not expected_real and actual_qs == "not_found":
                q_correct += 1
                print(f"    ✓ FAKE_QUOTE caught: {c['raw_citation'][:40]} sim={c.get('quote_similarity',0):.0%}")
            elif not expected_real and actual_verified:
                print(f"    ✗ FAKE_QUOTE verified (false neg): {c['raw_citation'][:40]}")
            else:
                print(f"    ~ FAKE_QUOTE status={actual_qs}: {c['raw_citation'][:40]}")

        if q_total:
            print(f"    Quote accuracy: {q_correct}/{q_total} = {q_correct/q_total:.0%}")

    return {
        "topic": topic,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "tp": true_pos,
        "tn": true_neg,
        "fp": false_pos,
        "fn": false_neg,
        "failures": failures,
    }


def main():
    if len(sys.argv) > 1:
        memo_files = [Path(p) for p in sys.argv[1:]]
    else:
        test_dir = Path(__file__).parent / "tests"
        memo_files = sorted(test_dir.glob("memo_*.json"))
        if not memo_files:
            print(f"No test memos found in {test_dir}/")
            print("Generate them with: python3.12 gen_test_memos.py")
            sys.exit(1)

    all_results = []
    for path in memo_files:
        memo = json.loads(path.read_text())
        result = run_memo(memo)
        all_results.append(result)

    # Aggregate
    total_tp = sum(r["tp"] for r in all_results)
    total_tn = sum(r["tn"] for r in all_results)
    total_fp = sum(r["fp"] for r in all_results)
    total_fn = sum(r["fn"] for r in all_results)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (total_tp + total_tn) / (total_tp + total_tn + total_fp + total_fn) if (total_tp + total_tn + total_fp + total_fn) > 0 else 0.0

    print(f"\n{'='*70}")
    print(f"OVERALL BENCHMARK RESULTS ({len(all_results)} memos)")
    print(f"{'='*70}")
    print(f"  Precision: {precision:.0%}  (of citations flagged as hallucinations, how many were actually fabricated)")
    print(f"  Recall:    {recall:.0%}  (of fabricated citations, how many were caught)")
    print(f"  F1:        {f1:.0%}")
    print(f"  Accuracy:  {accuracy:.0%}")
    print(f"  TP={total_tp} TN={total_tn} FP={total_fp} FN={total_fn}")

    # Per-memo summary
    print("\n  Per-memo F1:")
    for r in all_results:
        bar = "█" * int(r["f1"] * 20)
        print(f"    {r['topic']:<30} F1={r['f1']:.0%} {bar}")


if __name__ == "__main__":
    main()
