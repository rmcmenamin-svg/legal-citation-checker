#!/usr/bin/env python3
"""Generate test corpus documents and a brief that cites them.

Creates:
1. Source documents (the "corpus"):
   - Complaint (28 numbered paragraphs)
   - Exhibit A (contract excerpt)
   - Exhibit B (email chain)
   - Smith Deposition transcript (with page:line numbers)
   - Johnson Declaration (numbered paragraphs)

2. A brief that cites these documents — with a mix of:
   - Correct citations (should verify)
   - Wrong paragraph numbers (Compl. ¶ 34 but only 28 paras)
   - Wrong page:line references
   - Misquoted text
   - Exhibit that doesn't exist (Exhibit F)
"""

from pathlib import Path

try:
    from docx import Document  # type: ignore
except ImportError:
    raise SystemExit("python-docx required: pip install python-docx")


def _write_docx(paragraphs: list, path: Path) -> None:
    doc = Document()
    for line in paragraphs:
        doc.add_paragraph(line)
    doc.save(str(path))


def _write_text(text: str, path: Path) -> None:
    path.write_text(text, encoding="utf-8")


def generate_complaint(out_dir: Path) -> None:
    """Generate a 28-paragraph complaint."""
    paras = [
        "UNITED STATES DISTRICT COURT",
        "FOR THE EASTERN DISTRICT OF PENNSYLVANIA",
        "",
        "APEX SOFTWARE SOLUTIONS LLC, Plaintiff,",
        "v.",
        "KEYSTONE PHARMA GROUP LLC, Defendant.",
        "",
        "Case No. 2:25-cv-01789",
        "",
        "COMPLAINT",
        "",
    ]
    # 28 numbered paragraphs
    complaint_text = [
        "Plaintiff Apex Software Solutions LLC brings this action against Defendant Keystone Pharma Group LLC for breach of contract, fraud, and unjust enrichment.",
        "Plaintiff is a Delaware limited liability company with its principal place of business in Philadelphia, Pennsylvania.",
        "Defendant is a Delaware limited liability company with its principal place of business in Wilmington, Delaware.",
        "This Court has jurisdiction pursuant to 28 U.S.C. § 1332 because the parties are citizens of different states and the amount in controversy exceeds $75,000.",
        "Venue is proper in this district under 28 U.S.C. § 1391(b) because a substantial part of the events giving rise to the claim occurred in this district.",
        "On January 15, 2024, Plaintiff and Defendant entered into a Master Services Agreement whereby Defendant agreed to provide cloud infrastructure services for a period of three years.",
        "Under the MSA, Defendant guaranteed 99.99% uptime for all hosted services, as specified in the Service Level Agreement attached as Exhibit A.",
        "The monthly service fee under the MSA was $450,000, payable on the first business day of each month.",
        "Plaintiff timely paid all monthly service fees from January 2024 through August 2024, totaling $3,600,000.",
        "Beginning in March 2024, Defendant's services experienced significant and recurring outages that materially impacted Plaintiff's business operations.",
        "On March 12, 2024, Defendant's platform experienced a complete outage lasting 47 hours, during which Plaintiff's customers were unable to access critical healthcare applications.",
        "On April 3, 2024, a second major outage occurred lasting 28 hours, resulting in the loss of approximately 12,000 patient records.",
        "Between May and August 2024, an additional fifteen outages occurred, each lasting between 4 and 36 hours.",
        "The cumulative downtime from March through August 2024 exceeded 340 hours, far exceeding the 0.01% downtime permitted under the SLA.",
        "Plaintiff repeatedly notified Defendant of the service failures and demanded remediation, including through written correspondence on March 15, April 5, May 20, and July 1, 2024.",
        "Defendant acknowledged the outages but failed to implement adequate remedial measures.",
        "On June 15, 2024, Defendant's Chief Technology Officer, Robert Smith, stated in an email to Plaintiff that the outages were caused by Defendant's decision to migrate to cheaper server infrastructure without adequate testing.",
        "Defendant concealed the infrastructure migration from Plaintiff and did not disclose it until after the June 15 email.",
        "The infrastructure migration violated Section 4.2 of the MSA, which required Defendant to obtain Plaintiff's prior written consent before making material changes to the hosting environment.",
        "As a result of Defendant's service failures, Plaintiff lost seventeen major enterprise clients, representing approximately $12.7 million in annual recurring revenue.",
        "Plaintiff also incurred $2.3 million in emergency remediation costs, including the engagement of alternative cloud providers and data recovery services.",
        "Defendant's conduct constitutes a material breach of the Master Services Agreement.",
        "Defendant's concealment of the infrastructure migration and its false assurances of service reliability constitute fraud.",
        "Defendant has been unjustly enriched by retaining $3,600,000 in service fees while failing to provide the contracted services.",
        "Plaintiff has suffered damages in excess of $18,600,000.",
        "Plaintiff has performed all conditions precedent to bringing this action.",
        "All conditions precedent to Plaintiff's claims have been satisfied or waived.",
        "WHEREFORE, Plaintiff demands judgment against Defendant for compensatory damages, consequential damages, punitive damages, attorneys' fees, costs, and such other relief as the Court deems just and proper.",
    ]
    for i, text in enumerate(complaint_text, 1):
        paras.append(f"{i}. {text}")

    _write_docx(paras, out_dir / "Complaint.docx")
    print(f"  Complaint: {len(complaint_text)} paragraphs")


def generate_exhibit_a(out_dir: Path) -> None:
    """Generate Exhibit A — MSA excerpt with SLA terms."""
    paras = [
        "EXHIBIT A",
        "",
        "MASTER SERVICES AGREEMENT",
        "Effective Date: January 15, 2024",
        "",
        "SECTION 3. SERVICE LEVELS",
        "",
        "3.1 Uptime Guarantee. Provider shall maintain a monthly uptime percentage of at least 99.99% for all hosted services, measured as the total number of minutes in the applicable month minus the total number of minutes of Downtime, divided by the total number of minutes in the applicable month.",
        "",
        "3.2 Downtime Credits. For each full hour of Downtime in excess of the permitted downtime threshold, Provider shall credit Customer an amount equal to 2% of the monthly service fee, up to a maximum credit of 100% of the monthly service fee.",
        "",
        "3.3 Termination for Chronic Failure. If the monthly uptime percentage falls below 95% in any two consecutive months, or below 99% in any three months during a twelve-month period, Customer may terminate this Agreement immediately upon written notice.",
        "",
        "SECTION 4. INFRASTRUCTURE",
        "",
        "4.1 Hosting Environment. Provider shall host all Customer data and applications on enterprise-grade server infrastructure meeting or exceeding the specifications set forth in Schedule B.",
        "",
        "4.2 Material Changes. Provider shall not make any material changes to the hosting environment, including but not limited to migration to different server hardware or cloud infrastructure, without Customer's prior written consent.",
        "",
        "4.3 Security Standards. Provider shall maintain all security certifications listed in Schedule C and shall comply with HIPAA requirements at all times.",
        "",
        "SECTION 12. LIMITATION OF LIABILITY",
        "",
        "12.1 Cap. Except for breaches of Section 8 (Confidentiality) and Section 9 (Indemnification), neither party's aggregate liability under this Agreement shall exceed the total fees paid by Customer during the twelve-month period immediately preceding the claim.",
        "",
        "12.2 Exclusion of Consequential Damages. IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES.",
        "",
        "12.3 Exceptions. The limitations in this Section 12 shall not apply to: (a) breaches of Section 8; (b) Provider's indemnification obligations under Section 9; or (c) damages arising from Provider's gross negligence or willful misconduct.",
    ]
    _write_docx(paras, out_dir / "Exhibit_A.docx")
    print(f"  Exhibit A: MSA excerpt ({len(paras)} paragraphs)")


def generate_exhibit_b(out_dir: Path) -> None:
    """Generate Exhibit B — email chain."""
    paras = [
        "EXHIBIT B",
        "",
        "Email Chain: Infrastructure Issues",
        "",
        "FROM: Robert Smith <rsmith@keystonepharma.com>",
        "TO: Sarah Chen <schen@apexsoftware.com>",
        "DATE: June 15, 2024",
        "SUBJECT: RE: Ongoing Service Outages",
        "",
        "Sarah,",
        "",
        "I want to be transparent with you about what's been happening. The root cause of the recent outages is that we migrated our hosting infrastructure to a more cost-effective platform in February. The migration was intended to reduce our operating costs by approximately 40%, but the new infrastructure has proven to be less reliable than anticipated.",
        "",
        "We should have disclosed this change to you before proceeding, and I apologize for that oversight. We are currently evaluating options to either stabilize the current platform or migrate back to the original infrastructure.",
        "",
        "I'll have a detailed remediation plan to you by end of week.",
        "",
        "Best regards,",
        "Robert Smith",
        "CTO, Keystone Pharma Group",
        "",
        "---",
        "",
        "FROM: Sarah Chen <schen@apexsoftware.com>",
        "TO: Robert Smith <rsmith@keystonepharma.com>",
        "DATE: June 14, 2024",
        "SUBJECT: RE: Ongoing Service Outages",
        "",
        "Robert,",
        "",
        "We are extremely concerned about the continued service disruptions. Our clients are threatening to terminate their contracts with us, and we have already lost three major accounts this month alone. We need a clear explanation of what is causing these problems and a concrete plan to resolve them immediately.",
        "",
        "Sarah Chen",
        "VP Operations, Apex Software Solutions",
    ]
    _write_docx(paras, out_dir / "Exhibit_B.docx")
    print(f"  Exhibit B: Email chain")


def generate_smith_deposition(out_dir: Path) -> None:
    """Generate Smith Deposition transcript with page:line format."""
    # Standard deposition format: page headers + numbered lines (1-25 per page)
    pages = {
        42: [
            "Q. Mr. Smith, what is your role at Keystone Pharma Group?",
            "A. I am the Chief Technology Officer. I have held that",
            "position since March 2022.",
            "Q. And in that capacity, you are responsible for the",
            "company's technology infrastructure?",
            "A. Yes, that's correct. I oversee all technology",
            "operations, including server infrastructure, software",
            "development, and cybersecurity.",
            "Q. Mr. Smith, are you familiar with the Master Services",
            "Agreement between Keystone and Apex Software Solutions?",
            "A. Yes, I am. I was involved in negotiating the technical",
            "specifications of that agreement.",
            "Q. And you're aware that the MSA included a 99.99%",
            "uptime guarantee?",
            "A. Yes.",
            "Q. Did Keystone meet that uptime guarantee?",
            "A. No. We experienced several significant outages between",
            "March and August 2024.",
            "Q. What caused those outages?",
            "A. The primary cause was our migration to a new hosting",
            "platform in February 2024.",
            "Q. Whose decision was it to migrate to the new platform?",
            "A. It was a joint decision between myself and the CFO,",
            "Michael Torres. We were looking to reduce operating",
            "costs.",
        ],
        43: [
            "Q. Did you inform Apex Software about the migration",
            "before it occurred?",
            "A. No, we did not.",
            "Q. Why not?",
            "A. Honestly, we didn't think it would cause any",
            "significant issues. The new platform had good reviews",
            "and we believed the transition would be seamless.",
            "Q. But it wasn't seamless, was it?",
            "A. No, it was not. We started experiencing stability",
            "issues almost immediately after the migration.",
            "Q. When you say 'almost immediately,' what do you mean?",
            "A. Within the first two weeks. The first major outage",
            "occurred on March 12th.",
            "Q. And you still didn't inform Apex at that point?",
            "A. We reported the outage itself but did not disclose",
            "that it was related to the infrastructure change.",
            "Q. You concealed the cause from your client?",
            "A. I wouldn't characterize it as concealment. We were",
            "still diagnosing the root cause at that time.",
            "Q. But by June, you knew the cause, correct?",
            "A. Yes, by June we had confirmed that the migration was",
            "the primary factor.",
            "Q. And that's when you sent the email to Sarah Chen?",
            "A. Yes, the June 15th email. I wanted to be transparent",
            "about what had happened.",
        ],
        45: [
            "Q. Mr. Smith, approximately how many hours of total",
            "downtime did Keystone's platform experience between",
            "March and August 2024?",
            "A. Our internal logs show approximately 340 hours of",
            "cumulative downtime across all incidents.",
            "Q. 340 hours. That's over fourteen days of downtime in",
            "a six-month period?",
            "A. Yes, that's correct.",
            "Q. And the SLA permitted how much downtime per month?",
            "A. The SLA guaranteed 99.99% uptime, which translates",
            "to approximately 4.3 minutes of permitted downtime per",
            "month.",
            "Q. So 340 hours versus roughly 26 minutes of permitted",
            "downtime over six months?",
            "A. When you put it that way, yes, that's a significant",
            "deviation from the SLA.",
            "Q. Did Keystone issue any service credits to Apex as",
            "required by Section 3.2 of the MSA?",
            "A. I believe we issued some credits, but I'm not sure",
            "of the exact amount.",
            "Q. Would it surprise you to learn that no credits were",
            "ever issued?",
            "A. I — I would need to check our records on that.",
            "Q. Let's move on to the financial impact.",
            "A. Okay.",
        ],
    }

    lines = []
    lines.append("DEPOSITION OF ROBERT SMITH")
    lines.append("June 20, 2024")
    lines.append("")

    for page_num in sorted(pages.keys()):
        lines.append(f"Page {page_num}")
        for line_num, text in enumerate(pages[page_num], 1):
            lines.append(f" {line_num:2d} {text}")
        lines.append("")

    _write_text("\n".join(lines), out_dir / "Smith_Deposition.txt")
    print(f"  Smith Deposition: {len(pages)} pages, ~25 lines each")


def generate_johnson_declaration(out_dir: Path) -> None:
    """Generate Johnson Declaration with numbered paragraphs."""
    paras = [
        "DECLARATION OF MICHAEL JOHNSON",
        "",
        "I, Michael Johnson, declare under penalty of perjury as follows:",
        "",
        "1. I am the Chief Financial Officer of Apex Software Solutions LLC. I have held this position since 2019 and am responsible for the company's financial operations and reporting.",
        "",
        "2. I have personal knowledge of the financial impact of Keystone Pharma Group's service failures on Apex Software Solutions.",
        "",
        "3. Between March and August 2024, Apex lost seventeen major enterprise clients as a direct result of the service outages caused by Keystone's platform failures.",
        "",
        "4. The seventeen lost clients represented approximately $12.7 million in annual recurring revenue.",
        "",
        "5. The largest single client loss was MedTech Partners, which terminated its contract on May 30, 2024, citing repeated service disruptions. MedTech's contract was worth $3.2 million annually.",
        "",
        "6. In addition to lost revenue, Apex incurred $2.3 million in emergency remediation costs, including engaging alternative cloud providers and retaining a data recovery firm.",
        "",
        "7. Apex also spent approximately $450,000 on customer retention efforts, including service credits and dedicated support resources for clients affected by the outages.",
        "",
        "8. The total financial impact on Apex exceeds $15.4 million when accounting for lost revenue, remediation costs, and retention expenses.",
        "",
        "9. Prior to the service disruptions, Apex had a client retention rate of 96%. Following the outages, the retention rate dropped to 78%.",
        "",
        "10. I have reviewed the invoices and financial records supporting these figures, which are attached as Exhibits C and D.",
        "",
        "I declare under penalty of perjury that the foregoing is true and correct.",
        "",
        "Dated: August 15, 2024",
        "",
        "Michael Johnson",
        "CFO, Apex Software Solutions LLC",
    ]
    _write_docx(paras, out_dir / "Johnson_Declaration.docx")
    print(f"  Johnson Declaration: 10 paragraphs")


def generate_brief_with_record_citations(out_dir: Path) -> None:
    """Generate a brief that cites the corpus documents.

    Mix of correct and incorrect citations for testing.
    """
    paras = [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE EASTERN DISTRICT OF PENNSYLVANIA",
        "",
        "APEX SOFTWARE SOLUTIONS LLC, Plaintiff,",
        "v.",
        "KEYSTONE PHARMA GROUP LLC, Defendant.",
        "",
        "Case No. 2:25-cv-01789",
        "",
        "MEMORANDUM IN SUPPORT OF MOTION FOR SUMMARY JUDGMENT",
        "",
        "I. INTRODUCTION",
        "",
        # CORRECT: Complaint ¶ 6 exists and matches
        (
            "This action arises from Defendant's catastrophic breach of a Master "
            "Services Agreement. On January 15, 2024, the parties entered into the "
            "MSA under which Defendant guaranteed 99.99% uptime for cloud "
            "infrastructure services. Compl. ¶ 6. Defendant's services experienced "
            "over 340 hours of downtime in just six months — a massive failure by "
            "any standard."
        ),
        "",
        "II. UNDISPUTED FACTS",
        "",
        # CORRECT: Exhibit A at a valid page, quote matches
        (
            'The MSA required Defendant to maintain "a monthly uptime percentage '
            'of at least 99.99% for all hosted services." Ex. A at 3. This '
            "guarantee was a material term of the agreement and a key inducement "
            "for Plaintiff to enter into the contract."
        ),
        "",
        # CORRECT: Exhibit A at valid page, discussing Section 4.2
        (
            "Crucially, the MSA prohibited Defendant from making material changes "
            "to the hosting infrastructure without Plaintiff's prior written consent. "
            "Ex. A at 4. Despite this requirement, Defendant secretly migrated to a "
            "cheaper hosting platform in February 2024."
        ),
        "",
        # CORRECT: Smith deposition, correct page:line
        (
            "Defendant's own CTO admitted that the migration was the primary cause "
            'of the outages: "The primary cause was our migration to a new hosting '
            'platform in February 2024." Smith Dep. 42:20-21. The migration was '
            "undertaken to reduce operating costs without regard for service quality."
        ),
        "",
        # WRONG PAGE:LINE - Smith said this on page 43, not page 42
        (
            "Mr. Smith further admitted that Defendant did not inform Plaintiff "
            'about the migration: "No, we did not." Smith Dep. 42:3. This '
            "concealment constitutes a clear breach of Section 4.2 of the MSA."
        ),
        "",
        # CORRECT: Smith Dep. 45:4-5
        (
            "The scope of the failure is staggering. Defendant's internal logs "
            'confirm "approximately 340 hours of cumulative downtime across all '
            'incidents." Smith Dep. 45:4-5.'
        ),
        "",
        # WRONG PARAGRAPH: Complaint only has 28 paragraphs, citing ¶ 34
        (
            "Plaintiff has suffered total damages exceeding $18.6 million. "
            "Compl. ¶ 34. These damages include lost revenue from seventeen "
            "enterprise clients and $2.3 million in emergency remediation costs."
        ),
        "",
        # CORRECT: Johnson Declaration ¶ 4
        (
            "Plaintiff's CFO has confirmed that the lost clients represented "
            '"approximately $12.7 million in annual recurring revenue." '
            "Johnson Decl. ¶ 4."
        ),
        "",
        # WRONG PARAGRAPH: Johnson Declaration has 10 paragraphs, citing ¶ 15
        (
            "The total financial impact on Plaintiff exceeds $20 million when "
            "accounting for all categories of damages. Johnson Decl. ¶ 15."
        ),
        "",
        # MISQUOTE: Exhibit B has different text
        (
            "In his June 15 email, Defendant's CTO explicitly acknowledged the "
            'root cause: "We made a strategic decision to migrate our infrastructure '
            'to save approximately 40% in operating costs, fully knowing that it '
            'might affect service reliability." Ex. B at 6.'
        ),
        "",
        # DOCUMENT NOT FOUND: No Exhibit F in corpus
        (
            "Financial records confirm that Defendant retained all $3.6 million "
            "in service fees without providing any service credits. Ex. F at 2."
        ),
        "",
        # CORRECT: Exhibit B reference
        (
            'Defendant\'s VP of Operations wrote: "Our clients are threatening '
            'to terminate their contracts with us." Ex. B at 5.'
        ),
        "",
        # WRONG: Smith Dep. page 50 doesn't exist (only pages 42, 43, 45)
        (
            "Mr. Smith testified that Defendant's board was fully aware of the "
            "risks. Smith Dep. 50:12-15."
        ),
        "",
        # CORRECT: Johnson Decl. ¶ 8
        (
            "The total financial impact on Apex exceeds $15.4 million. "
            "Johnson Decl. ¶ 8."
        ),
        "",
        # CORRECT: Compl. ¶ 17
        (
            "Defendant's CTO admitted in the June 15 email that the outages were "
            '"caused by Defendant\'s decision to migrate to cheaper server '
            'infrastructure without adequate testing." Compl. ¶ 17.'
        ),
        "",
        "III. CONCLUSION",
        "",
        (
            "The undisputed record evidence establishes Defendant's breach of "
            "the MSA and fraud. Plaintiff is entitled to summary judgment on "
            "all claims."
        ),
    ]

    _write_docx(paras, out_dir / "summary_judgment_brief.docx")
    print(f"  Brief: generated with record citations")


def main():
    out_dir = Path(__file__).resolve().parent / "test_documents" / "corpus"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Generating corpus documents:")
    generate_complaint(out_dir)
    generate_exhibit_a(out_dir)
    generate_exhibit_b(out_dir)
    generate_smith_deposition(out_dir)
    generate_johnson_declaration(out_dir)
    print()

    print("Generating brief with record citations:")
    generate_brief_with_record_citations(out_dir)
    print()

    print("Ground truth for record citations in brief:")
    print("  CORRECT citations:")
    print("    ✓ Compl. ¶ 6 — exists (28 paras)")
    print("    ✓ Ex. A at 3 — exists, quote matches")
    print("    ✓ Ex. A at 4 — exists")
    print("    ✓ Smith Dep. 42:20-21 — correct page:line, quote matches")
    print("    ✓ Smith Dep. 45:4-5 — correct page:line, quote matches")
    print("    ✓ Johnson Decl. ¶ 4 — exists, quote matches")
    print("    ✓ Johnson Decl. ¶ 8 — exists")
    print("    ✓ Compl. ¶ 17 — exists")
    print("    ✓ Ex. B at 5 — exists")
    print()
    print("  WRONG citations:")
    print("    ✗ Smith Dep. 42:3 — wrong page (actually p.43 line 3)")
    print("    ✗ Compl. ¶ 34 — only 28 paragraphs")
    print("    ✗ Johnson Decl. ¶ 15 — only 10 paragraphs")
    print("    ✗ Ex. B at 6 — misquoted text")
    print("    ✗ Ex. F at 2 — no Exhibit F in corpus")
    print("    ✗ Smith Dep. 50:12-15 — page 50 doesn't exist")


if __name__ == "__main__":
    main()
