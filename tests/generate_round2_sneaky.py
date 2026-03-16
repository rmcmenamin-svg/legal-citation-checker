#!/usr/bin/env python3
"""Generate a 'sneaky hallucination' brief — the hardest test case.

This simulates the most dangerous LLM hallucination pattern:
- Real case names paired with WRONG reporter/volume/page citations
- Real case names cited for propositions the actual case doesn't stand for
- Slightly wrong page numbers or reporter editions
- Real cases from wrong jurisdictions

These are extremely hard to catch because party-name searches will find
the real case, but the citation numbers won't match.
"""

from pathlib import Path

try:
    from docx import Document  # type: ignore
except ImportError:
    raise SystemExit("python-docx required: pip install python-docx")


SNEAKY_BRIEF = {
    "title": "MEMORANDUM IN SUPPORT OF MOTION TO DISMISS",
    "paragraphs": [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE EASTERN DISTRICT OF PENNSYLVANIA",
        "",
        "OMEGA HEALTHCARE INC., Plaintiff,",
        "v.",
        "KEYSTONE PHARMA GROUP LLC, Defendant.",
        "",
        "Case No. 2:25-cv-01789",
        "",
        "MEMORANDUM IN SUPPORT OF MOTION TO DISMISS",
        "",
        "I. INTRODUCTION",
        "",
        (
            "Defendant Keystone Pharma Group LLC moves to dismiss Plaintiff's "
            "Complaint for failure to state a claim upon which relief can be "
            "granted under Federal Rule of Civil Procedure 12(b)(6). To survive "
            "a motion to dismiss, a complaint must contain sufficient factual "
            "matter, accepted as true, to state a claim to relief that is "
            "plausible on its face. Ashcroft v. Iqbal, 556 U.S. 662 (2009)."
        ),
        "",
        "II. LEGAL STANDARD",
        "",
        (
            "The plausibility standard established in Bell Atlantic Corp. v. "
            "Twombly, 550 U.S. 544 (2007), requires more than a sheer possibility "
            "that a defendant has acted unlawfully. The Court must accept all "
            "well-pleaded factual allegations as true and draw all reasonable "
            "inferences in favor of the plaintiff. However, legal conclusions "
            "and threadbare recitals of elements are not entitled to the "
            "presumption of truth."
        ),
        "",
        "III. ARGUMENT",
        "",
        "A. Plaintiff Fails to State a Fraud Claim",
        "",
        (
            # SNEAKY: Real case name "Dura Pharmaceuticals" but WRONG citation.
            # Real cite is 544 U.S. 336, not 552 U.S. 148
            "To state a claim for securities fraud, a plaintiff must plead "
            "loss causation with specificity. Dura Pharmaceuticals, Inc. v. Broudo, "
            "552 U.S. 148 (2007). The complaint here alleges only that Plaintiff "
            "suffered losses after purchasing Defendant's securities, without "
            "establishing the requisite causal connection between the alleged "
            "misrepresentation and the economic loss."
        ),
        "",
        (
            # SNEAKY: Real case name "Tellabs" but WRONG citation.
            # Real cite is 551 U.S. 308, not 549 U.S. 457
            "Furthermore, the Private Securities Litigation Reform Act requires "
            "that the complaint state with particularity facts giving rise to a "
            "strong inference of scienter. Tellabs, Inc. v. Makor Issues & "
            "Rights, Ltd., 549 U.S. 457 (2006). Plaintiff's allegations of "
            "fraudulent intent are conclusory and fail to meet this heightened "
            "pleading standard."
        ),
        "",
        (
            # REAL citation, correctly cited
            "The Third Circuit has emphasized that 'vague and conclusory "
            "allegations of fraud' do not satisfy Rule 9(b)'s heightened pleading "
            "requirements. In re Burlington Coat Factory Securities Litigation, "
            "114 F.3d 1410 (3d Cir. 1997)."
        ),
        "",
        "B. Plaintiff's Negligent Misrepresentation Claim Is Deficient",
        "",
        (
            # SNEAKY: Real case "Gutter v. Bollman" but wrong court and cite
            # This is actually a Florida case, not 3d Circuit
            "A claim for negligent misrepresentation requires the plaintiff to "
            "demonstrate a duty to provide accurate information, breach of that "
            "duty, and resulting damages. Gutter v. Bollman, 763 F.3d 209 "
            "(3d Cir. 2018). Plaintiff has failed to allege any special "
            "relationship giving rise to a duty of care."
        ),
        "",
        (
            # REAL citation
            "The economic loss doctrine bars negligent misrepresentation claims "
            "where the alleged loss is purely economic. East River Steamship Corp. "
            "v. Transamerica Delaval Inc., 476 U.S. 858 (1986)."
        ),
        "",
        "C. Plaintiff's Breach of Fiduciary Duty Claim Fails",
        "",
        (
            # SNEAKY: Real case name "Meinhard v. Salmon" — a REAL classic
            # fiduciary duty case. Real cite is 164 N.E. 545 (N.Y. 1928).
            # LLM invents a federal reporter cite.
            "While fiduciary duties are well-established in corporate law, "
            "Meinhard v. Salmon, 249 F.2d 458 (2d Cir. 1928), they arise only "
            "in specific relationships. The arm's-length commercial transaction "
            "at issue here does not give rise to fiduciary obligations."
        ),
        "",
        (
            # SNEAKY: Real case "Brophy v. Cities Service Co." — a REAL Delaware
            # insider trading case. Real cite is 31 Del. Ch. 241, 70 A.2d 5 (1949).
            # LLM invents a modern federal cite.
            "Delaware courts have long recognized the duty of loyalty in corporate "
            "governance. Brophy v. Cities Service Co., 456 F.3d 823 (3d Cir. 2006). "
            "However, that duty runs from corporate officers and directors to "
            "shareholders — not between arm's-length contracting parties."
        ),
        "",
        (
            # REAL citation
            "The Supreme Court has confirmed that the duty of loyalty is a "
            "cornerstone of corporate governance. Burwell v. Hobby Lobby Stores, "
            "Inc., 573 U.S. 682 (2014)."
        ),
        "",
        "D. Plaintiff's Unjust Enrichment Claim Is Preempted",
        "",
        (
            # SNEAKY: Real case name "Kottler v. Deutsche Bank" — plausible
            # but entirely fabricated party + cite combination
            "Where an express contract governs the parties' relationship, an "
            "unjust enrichment claim cannot stand. Kottler v. Deutsche Bank AG, "
            "607 F.3d 356 (2d Cir. 2012). The MSA between the parties expressly "
            "covers the subject matter of Plaintiff's unjust enrichment claim."
        ),
        "",
        (
            # REAL citation
            "As the Supreme Court explained in Great-West Life & Annuity "
            "Insurance Co. v. Knudson, 534 U.S. 204 (2002), equitable relief "
            "is available only where legal remedies are inadequate."
        ),
        "",
        "IV. CONCLUSION",
        "",
        (
            "Plaintiff's Complaint fails to state any viable claim for relief "
            "and should be dismissed with prejudice under Rule 12(b)(6)."
        ),
    ],
    "ground_truth": {
        "REAL": [
            ("556 U.S. 662", "Ashcroft v. Iqbal"),
            ("550 U.S. 544", "Bell Atlantic v. Twombly"),
            ("114 F.3d 1410", "In re Burlington Coat Factory"),
            ("476 U.S. 858", "East River Steamship v. Transamerica"),
            ("573 U.S. 682", "Burwell v. Hobby Lobby"),
            ("534 U.S. 204", "Great-West Life v. Knudson"),
        ],
        "SNEAKY_WRONG_CITE": [
            # Real case name + wrong citation number
            ("552 U.S. 148", "Dura Pharmaceuticals v. Broudo",
             "Real cite is 544 U.S. 336"),
            ("549 U.S. 457", "Tellabs v. Makor Issues",
             "Real cite is 551 U.S. 308"),
            ("249 F.2d 458", "Meinhard v. Salmon",
             "Real cite is 164 N.E. 545 (N.Y. 1928)"),
            ("456 F.3d 823", "Brophy v. Cities Service",
             "Real cite is 31 Del. Ch. 241, 70 A.2d 5 (1949)"),
        ],
        "FAKE": [
            # Completely fabricated case + citation
            ("763 F.3d 209", "Gutter v. Bollman"),
            ("607 F.3d 356", "Kottler v. Deutsche Bank"),
        ],
    },
}


def generate_docx(brief: dict, output_path: Path) -> None:
    doc = Document()
    for line in brief["paragraphs"]:
        if line == "":
            doc.add_paragraph("")
        elif line.isupper() or line.startswith("Case No."):
            p = doc.add_paragraph(line)
            p.alignment = 1
        elif line.startswith(("A.", "B.", "C.", "D.", "I.", "II.", "III.", "IV.")):
            doc.add_heading(line, level=2)
        else:
            doc.add_paragraph(line)
    doc.save(str(output_path))


def main():
    out_dir = Path(__file__).resolve().parent / "test_documents" / "round2"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "sneaky_hallucination_brief.docx"
    generate_docx(SNEAKY_BRIEF, out_path)

    gt = SNEAKY_BRIEF["ground_truth"]
    real_count = len(gt["REAL"])
    sneaky_count = len(gt["SNEAKY_WRONG_CITE"])
    fake_count = len(gt["FAKE"])

    print(f"Generated: {out_path.name}")
    print(f"  {real_count} real + {sneaky_count} sneaky (wrong cite) + {fake_count} fully fake\n")

    print("REAL citations (should verify):")
    for cite, name in gt["REAL"]:
        print(f"  ✓ {cite} — {name}")

    print("\nSNEAKY citations (real case name, WRONG citation number):")
    for cite, name, note in gt["SNEAKY_WRONG_CITE"]:
        print(f"  ⚠ {cite} — {name}")
        print(f"    NOTE: {note}")

    print("\nFULLY FAKE citations (should be flagged):")
    for cite, name in gt["FAKE"]:
        print(f"  ✗ {cite} — {name}")


if __name__ == "__main__":
    main()
