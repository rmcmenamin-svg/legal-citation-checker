#!/usr/bin/env python3
"""Generate Round 2 LLM-style test briefs across different legal domains.

Each brief mixes real landmark citations with plausible-sounding fabricated
ones — simulating what lesser LLMs (Mistral-7B, Llama-2, early GPT-3.5)
typically hallucinate.
"""

from pathlib import Path

try:
    from docx import Document  # type: ignore
except ImportError:
    raise SystemExit("python-docx required: pip install python-docx")


# ── Brief 1: Employment Discrimination (Title VII) ─────────────────────

EMPLOYMENT_BRIEF = {
    "title": "MEMORANDUM IN SUPPORT OF PLAINTIFF'S TITLE VII CLAIM",
    "paragraphs": [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE SOUTHERN DISTRICT OF NEW YORK",
        "",
        "MARIA SANTOS, Plaintiff,",
        "v.",
        "GLOBALCHEM INDUSTRIES INC., Defendant.",
        "",
        "Case No. 1:25-cv-04567",
        "",
        "MEMORANDUM IN SUPPORT OF PLAINTIFF'S TITLE VII CLAIM",
        "",
        "I. INTRODUCTION",
        "",
        (
            "Plaintiff Maria Santos brings this action under Title VII of the Civil "
            "Rights Act of 1964, alleging that Defendant GlobalChem Industries Inc. "
            "subjected her to a hostile work environment based on her national origin "
            "and gender. The Supreme Court has long held that Title VII forbids not "
            "only economic or tangible discrimination, but also the creation of a "
            "hostile or abusive work environment. Meritor Savings Bank, FSB v. Vinson, "
            "477 U.S. 57 (1986)."
        ),
        "",
        "II. LEGAL STANDARD",
        "",
        (
            "To establish a hostile work environment claim, a plaintiff must show that "
            "the workplace was permeated with discriminatory intimidation, ridicule, "
            "and insult that was sufficiently severe or pervasive to alter the "
            "conditions of the victim's employment. Harris v. Forklift Systems, Inc., "
            "510 U.S. 17 (1993). The Court must consider the totality of the "
            "circumstances, including the frequency of the discriminatory conduct, "
            "its severity, and whether it unreasonably interferes with an employee's "
            "work performance."
        ),
        "",
        (
            "Under the burden-shifting framework of McDonnell Douglas Corp. v. Green, "
            "411 U.S. 792 (1973), once a plaintiff establishes a prima facie case, "
            "the burden shifts to the employer to articulate a legitimate, "
            "nondiscriminatory reason for its actions. If the employer meets this "
            "burden, the plaintiff must then demonstrate that the proffered reason "
            "was a pretext for discrimination."
        ),
        "",
        "III. ARGUMENT",
        "",
        "A. Plaintiff Establishes a Prima Facie Case of National Origin Discrimination",
        "",
        (
            "The Second Circuit has recognized that a pattern of derogatory comments "
            "about an employee's ethnicity, combined with adverse employment actions, "
            "can establish a hostile work environment claim. Littlejohn v. City of "
            "New York, 795 F.3d 297 (2d Cir. 2015). Here, Plaintiff was repeatedly "
            "subjected to derogatory remarks about her Latino heritage, including "
            "being told to 'go back where she came from' and being excluded from "
            "team meetings conducted exclusively in English despite the availability "
            "of bilingual alternatives."
        ),
        "",
        (
            "Courts have consistently held that such exclusionary conduct constitutes "
            "national origin discrimination. In Rivera v. Continental Airlines, "
            "867 F.3d 1034 (2d Cir. 2019), the Second Circuit found that systematic "
            "exclusion of Latino employees from professional development opportunities "
            "constituted actionable discrimination under Title VII. See also Chen v. "
            "Metropolitan Transit Authority, 538 F. Supp. 3d 445 (S.D.N.Y. 2022) "
            "(holding that language-based exclusion creates hostile work environment)."
        ),
        "",
        "B. Defendant's Conduct Was Severe and Pervasive",
        "",
        (
            "The Supreme Court has instructed that courts should examine the totality "
            "of the circumstances in evaluating hostile work environment claims. "
            "Oncale v. Sundowner Offshore Services, Inc., 523 U.S. 75 (1998). "
            "The conduct here spanned eighteen months and included both verbal "
            "harassment and tangible employment actions, including denial of "
            "promotions and assignment to less desirable shifts."
        ),
        "",
        (
            "In Burlington Northern & Santa Fe Railway Co. v. White, 548 U.S. 53 "
            "(2006), the Supreme Court held that the anti-retaliation provision of "
            "Title VII covers employer actions that would dissuade a reasonable "
            "worker from making a charge of discrimination. Here, Defendant's "
            "pattern of retaliatory conduct following Plaintiff's internal "
            "complaints clearly meets this standard."
        ),
        "",
        (
            "The Second Circuit has further recognized that intersectional "
            "discrimination — where an employee faces bias based on multiple "
            "protected characteristics — warrants heightened scrutiny. In Prescott v. "
            "Oakridge Technologies, 912 F.3d 678 (2d Cir. 2021), the court held "
            "that Latina women face 'unique and compounded' forms of workplace "
            "discrimination that must be evaluated holistically. See also Vasquez v. "
            "DataPlex Corp., 743 F. Supp. 3d 892 (S.D.N.Y. 2023) (applying "
            "intersectional analysis to Title VII claims)."
        ),
        "",
        "C. Defendant Cannot Establish the Faragher-Ellerth Affirmative Defense",
        "",
        (
            "Under Faragher v. City of Boca Raton, 524 U.S. 775 (1998), and "
            "Burlington Industries, Inc. v. Ellerth, 524 U.S. 742 (1998), an "
            "employer may raise an affirmative defense when no tangible employment "
            "action has been taken. However, this defense is unavailable here because "
            "Plaintiff suffered tangible employment actions including demotion and "
            "reduction in pay."
        ),
        "",
        (
            "Even if the defense were available, Defendant cannot satisfy either prong. "
            "The employer failed to exercise reasonable care to prevent and correct "
            "harassment, as evidenced by the absence of any meaningful investigation "
            "into Plaintiff's complaints. See Vance v. Ball State University, "
            "570 U.S. 421 (2013) (clarifying the definition of 'supervisor' for "
            "purposes of employer liability under Title VII)."
        ),
        "",
        "IV. CONCLUSION",
        "",
        (
            "For the foregoing reasons, Plaintiff has established a prima facie case "
            "of hostile work environment discrimination based on national origin and "
            "gender under Title VII. Defendant's proffered reasons for its actions "
            "are pretextual. See Texas Dept. of Community Affairs v. Burdine, "
            "450 U.S. 248 (1981)."
        ),
    ],
    "ground_truth": {
        "REAL": [
            ("477 U.S. 57", "Meritor Savings Bank v. Vinson"),
            ("510 U.S. 17", "Harris v. Forklift Systems"),
            ("411 U.S. 792", "McDonnell Douglas v. Green"),
            ("795 F.3d 297", "Littlejohn v. City of New York"),
            ("523 U.S. 75", "Oncale v. Sundowner Offshore"),
            ("548 U.S. 53", "Burlington Northern v. White"),
            ("524 U.S. 775", "Faragher v. City of Boca Raton"),
            ("524 U.S. 742", "Burlington Industries v. Ellerth"),
            ("570 U.S. 421", "Vance v. Ball State University"),
            ("450 U.S. 248", "Texas Dept. v. Burdine"),
        ],
        "FAKE": [
            ("867 F.3d 1034", "Rivera v. Continental Airlines"),
            ("538 F. Supp. 3d 445", "Chen v. Metropolitan Transit Authority"),
            ("912 F.3d 678", "Prescott v. Oakridge Technologies"),
            ("743 F. Supp. 3d 892", "Vasquez v. DataPlex Corp."),
        ],
    },
}


# ── Brief 2: Contract Law / Breach of Contract ────────────────────────

CONTRACT_BRIEF = {
    "title": "MEMORANDUM IN SUPPORT OF MOTION FOR BREACH OF CONTRACT",
    "paragraphs": [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE DISTRICT OF DELAWARE",
        "",
        "APEX SOFTWARE SOLUTIONS LLC, Plaintiff,",
        "v.",
        "NEXGEN CLOUD SERVICES INC., Defendant.",
        "",
        "Case No. 1:25-cv-00891",
        "",
        "MEMORANDUM IN SUPPORT OF MOTION FOR BREACH OF CONTRACT",
        "",
        "I. INTRODUCTION",
        "",
        (
            "Plaintiff Apex Software Solutions LLC brings this breach of contract "
            "action arising from Defendant NexGen Cloud Services Inc.'s failure to "
            "perform under a Master Services Agreement dated January 15, 2024. Under "
            "well-established principles of contract law, a party who materially "
            "breaches a contract may not enforce it against the other party. "
            "Taylor v. Caldwell, 122 Eng. Rep. 309 (1863). In the United States, "
            "the Supreme Court has consistently upheld the sanctity of freely "
            "negotiated contracts. Lochner v. New York, 198 U.S. 45 (1905)."
        ),
        "",
        "II. STATEMENT OF FACTS",
        "",
        (
            "On January 15, 2024, the parties entered into a Master Services Agreement "
            "under which Defendant agreed to provide cloud infrastructure services "
            "for a period of three years at a fixed monthly rate of $450,000. "
            "Defendant guaranteed 99.99% uptime in accordance with the Service Level "
            "Agreement attached as Exhibit A. Between March and August 2024, "
            "Defendant's services experienced seventeen significant outages, "
            "resulting in cumulative downtime exceeding 340 hours."
        ),
        "",
        "III. ARGUMENT",
        "",
        "A. Defendant Materially Breached the Master Services Agreement",
        "",
        (
            "A material breach occurs when the breaching party fails to perform a "
            "duty that goes to the essence of the contract. Restatement (Second) of "
            "Contracts § 241 (1981). The Third Circuit has adopted a multi-factor "
            "test for determining materiality that considers, among other things, "
            "the extent to which the injured party will be deprived of the benefit "
            "which it reasonably expected. Norfolk Southern Railway Co. v. Basell USA "
            "Inc., 512 F.3d 86 (3d Cir. 2008)."
        ),
        "",
        (
            "Courts have consistently held that failure to meet guaranteed service "
            "levels in technology contracts constitutes material breach. In DataStream "
            "Corp. v. CloudFirst Holdings, 934 F.3d 567 (3d Cir. 2021), the Third "
            "Circuit held that repeated SLA violations totaling more than 100 hours "
            "of downtime over six months constituted a material breach as a matter of "
            "law. Similarly, in Pinnacle Systems v. Azure Networks, 678 F. Supp. 3d "
            "234 (D. Del. 2022), the court found material breach where the defendant's "
            "cloud platform experienced 'chronic and systemic' performance failures."
        ),
        "",
        "B. Plaintiff Is Entitled to Expectation Damages",
        "",
        (
            "The standard remedy for breach of contract is expectation damages — the "
            "amount necessary to put the injured party in the position it would have "
            "occupied had the contract been performed. Hawkins v. McGee, 84 N.H. 114 "
            "(1929). The Supreme Court affirmed this principle in Mobil Oil "
            "Exploration & Producing Southeast, Inc. v. United States, 530 U.S. 604 "
            "(2000), holding that the government was liable for billions in "
            "expectation damages when it breached offshore drilling contracts."
        ),
        "",
        (
            "The Third Circuit has recognized that lost profits are recoverable as "
            "expectation damages where they are established with reasonable certainty. "
            "Fera v. Village Plaza, Inc., 396 Mich. 639 (1976). Here, Plaintiff's "
            "expert has calculated lost profits of $12.7 million resulting from "
            "Defendant's service outages, based on documented revenue losses and "
            "customer attrition directly attributable to the downtime."
        ),
        "",
        (
            "Furthermore, in TechVenture LLC v. ServerPro Inc., 845 F.3d 1122 "
            "(3d Cir. 2020), the court upheld a lost profits award of $8.5 million "
            "in a cloud services breach case, finding that the plaintiff's damages "
            "methodology was sufficiently reliable under Daubert. See also Quantum "
            "Dynamics v. NetScale Solutions, 567 F. Supp. 3d 891 (D. Del. 2023) "
            "(awarding consequential damages for SLA breaches in managed services "
            "agreement)."
        ),
        "",
        "C. The Limitation of Liability Clause Is Unenforceable",
        "",
        (
            "Defendant will likely invoke the limitation of liability clause in "
            "Section 12.3 of the MSA, which caps damages at twelve months of service "
            "fees. However, such clauses are unenforceable where the breach is willful "
            "or grossly negligent. See Lucent Technologies, Inc. v. Tatung Co., "
            "379 F.3d 24 (2d Cir. 2004). The Third Circuit has similarly held that "
            "limitation of liability provisions do not shield a party from liability "
            "for its own material breach. In re WorldCom, Inc. Securities Litigation, "
            "346 F. Supp. 2d 628 (S.D.N.Y. 2004)."
        ),
        "",
        (
            "Moreover, Delaware law — which governs this agreement — recognizes that "
            "contractual limitations on liability are subject to scrutiny under the "
            "implied covenant of good faith and fair dealing. Dunlap v. State Farm "
            "Fire & Casualty Co., 878 A.2d 434 (Del. 2005)."
        ),
        "",
        "IV. CONCLUSION",
        "",
        (
            "Defendant materially breached the Master Services Agreement through "
            "chronic service failures. Plaintiff is entitled to full expectation "
            "damages including lost profits. The limitation of liability clause "
            "is unenforceable."
        ),
    ],
    "ground_truth": {
        "REAL": [
            ("198 U.S. 45", "Lochner v. New York"),
            ("512 F.3d 86", "Norfolk Southern Railway v. Basell USA"),
            ("530 U.S. 604", "Mobil Oil v. United States"),
            ("379 F.3d 24", "Lucent Technologies v. Tatung"),
            ("346 F. Supp. 2d 628", "In re WorldCom"),
            ("878 A.2d 434", "Dunlap v. State Farm"),
        ],
        "FAKE": [
            ("934 F.3d 567", "DataStream Corp. v. CloudFirst Holdings"),
            ("678 F. Supp. 3d 234", "Pinnacle Systems v. Azure Networks"),
            ("845 F.3d 1122", "TechVenture LLC v. ServerPro Inc."),
            ("567 F. Supp. 3d 891", "Quantum Dynamics v. NetScale Solutions"),
        ],
    },
}


# ── Brief 3: First Amendment / Free Speech ────────────────────────────

FIRST_AMENDMENT_BRIEF = {
    "title": "BRIEF IN SUPPORT OF PRELIMINARY INJUNCTION",
    "paragraphs": [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE MIDDLE DISTRICT OF TENNESSEE",
        "",
        "FREEDOM NEWS NETWORK INC., Plaintiff,",
        "v.",
        "CITY OF NASHVILLE, Defendant.",
        "",
        "Case No. 3:25-cv-00234",
        "",
        "BRIEF IN SUPPORT OF PRELIMINARY INJUNCTION",
        "",
        "I. INTRODUCTION",
        "",
        (
            "Plaintiff Freedom News Network Inc. seeks a preliminary injunction "
            "against the City of Nashville's Ordinance 2024-87, which imposes "
            "content-based restrictions on news gathering activities in public spaces. "
            "The First Amendment, applicable to the states through the Fourteenth "
            "Amendment, prohibits government restrictions on speech based on content. "
            "Police Dept. of Chicago v. Mosley, 408 U.S. 92 (1972)."
        ),
        "",
        "II. LEGAL STANDARD",
        "",
        (
            "Content-based restrictions on speech are presumptively unconstitutional "
            "and subject to strict scrutiny. Reed v. Town of Gilbert, 576 U.S. 155 "
            "(2015). Under strict scrutiny, the government must demonstrate that the "
            "restriction is narrowly tailored to serve a compelling governmental "
            "interest. The Supreme Court has emphasized that this is the most "
            "demanding test known to constitutional law."
        ),
        "",
        "III. ARGUMENT",
        "",
        "A. The Ordinance Is a Content-Based Restriction on Protected Speech",
        "",
        (
            "Ordinance 2024-87 restricts news gathering based on the subject matter "
            "of the reporting, prohibiting coverage of certain law enforcement "
            "activities within 100 feet. The Supreme Court has squarely held that "
            "the press has a First Amendment right to gather news. Branzburg v. "
            "Hayes, 408 U.S. 665 (1972). While Branzburg involved the question of "
            "reporter's privilege, its recognition of press freedom extends to news "
            "gathering activities generally."
        ),
        "",
        (
            "The Sixth Circuit has repeatedly struck down similar restrictions on "
            "press access. In Glik v. Cunniffe, 655 F.3d 78 (1st Cir. 2011), the "
            "First Circuit established that the right to film police officers in the "
            "course of their duties in a public space is a clearly established First "
            "Amendment right. The Sixth Circuit followed this reasoning in Davidson "
            "v. Metropolitan Nashville Police Dept., 891 F.3d 567 (6th Cir. 2020), "
            "holding that a Nashville ordinance restricting media access to protest "
            "zones violated the First Amendment."
        ),
        "",
        "B. The Ordinance Fails Strict Scrutiny",
        "",
        (
            "Even assuming the City has a compelling interest in officer safety, the "
            "Ordinance is not narrowly tailored. The Supreme Court has consistently "
            "required that content-based speech restrictions be the least restrictive "
            "means available. McCullen v. Coakley, 573 U.S. 464 (2014). In McCullen, "
            "the Court struck down a Massachusetts buffer zone statute even though "
            "it served legitimate interests in public safety and access to "
            "reproductive health clinics."
        ),
        "",
        (
            "Here, less restrictive alternatives exist, including time, place, and "
            "manner restrictions that do not discriminate based on the content of "
            "the reporting. See Ward v. Rock Against Racism, 491 U.S. 781 (1989) "
            "(content-neutral time, place, and manner restrictions need only be "
            "narrowly tailored to serve a significant governmental interest). The "
            "Sixth Circuit applied this framework in Press Freedom Coalition v. "
            "City of Memphis, 823 F.3d 445 (6th Cir. 2022), striking down a "
            "similar 150-foot buffer zone for media near active crime scenes."
        ),
        "",
        "C. Prior Restraint Analysis",
        "",
        (
            "To the extent the Ordinance operates as a prior restraint on speech, "
            "it bears a heavy presumption against its constitutional validity. "
            "Near v. Minnesota, 283 U.S. 697 (1931). The Supreme Court reaffirmed "
            "this principle in New York Times Co. v. United States, 403 U.S. 713 "
            "(1971), the Pentagon Papers case, holding that the government carries "
            "a 'heavy burden of showing justification for the imposition of such a "
            "restraint.'"
        ),
        "",
        (
            "More recently, in Citizens United v. Federal Election Commission, "
            "558 U.S. 310 (2010), the Court emphasized that the First Amendment "
            "stands against attempts to disfavor certain subjects or viewpoints. "
            "See also Turner Broadcasting System, Inc. v. FCC, 512 U.S. 622 (1994) "
            "(applying intermediate scrutiny to content-neutral regulations of "
            "cable television but noting that content-based regulations require "
            "strict scrutiny)."
        ),
        "",
        (
            "In the digital age, courts have recognized that these principles apply "
            "with full force to online journalism and citizen reporting. In Digital "
            "Press Alliance v. State of Tennessee, 945 F.3d 789 (6th Cir. 2023), "
            "the Sixth Circuit extended full First Amendment protection to online-only "
            "news outlets, rejecting the state's argument that only traditional media "
            "organizations qualify for press freedom protections."
        ),
        "",
        "IV. CONCLUSION",
        "",
        (
            "The City's Ordinance is a content-based restriction on protected speech "
            "that fails strict scrutiny. Plaintiff is likely to succeed on the merits "
            "and is entitled to a preliminary injunction."
        ),
    ],
    "ground_truth": {
        "REAL": [
            ("408 U.S. 92", "Police Dept. of Chicago v. Mosley"),
            ("576 U.S. 155", "Reed v. Town of Gilbert"),
            ("408 U.S. 665", "Branzburg v. Hayes"),
            ("655 F.3d 78", "Glik v. Cunniffe"),
            ("573 U.S. 464", "McCullen v. Coakley"),
            ("491 U.S. 781", "Ward v. Rock Against Racism"),
            ("283 U.S. 697", "Near v. Minnesota"),
            ("403 U.S. 713", "New York Times Co. v. United States"),
            ("558 U.S. 310", "Citizens United v. FEC"),
            ("512 U.S. 622", "Turner Broadcasting v. FCC"),
        ],
        "FAKE": [
            ("891 F.3d 567", "Davidson v. Metropolitan Nashville Police Dept."),
            ("823 F.3d 445", "Press Freedom Coalition v. City of Memphis"),
            ("945 F.3d 789", "Digital Press Alliance v. State of Tennessee"),
        ],
    },
}


# ── Brief 4: Immigration / Due Process ────────────────────────────────

IMMIGRATION_BRIEF = {
    "title": "PETITION FOR WRIT OF HABEAS CORPUS",
    "paragraphs": [
        "IN THE UNITED STATES DISTRICT COURT",
        "FOR THE CENTRAL DISTRICT OF CALIFORNIA",
        "",
        "AHMED AL-RASHIDI, Petitioner,",
        "v.",
        "DIRECTOR, ICE FIELD OFFICE, LOS ANGELES, Respondent.",
        "",
        "Case No. 2:25-cv-03456",
        "",
        "PETITION FOR WRIT OF HABEAS CORPUS",
        "",
        "I. INTRODUCTION",
        "",
        (
            "Petitioner Ahmed Al-Rashidi, a lawful permanent resident of the United "
            "States, has been detained by Immigration and Customs Enforcement for "
            "over fourteen months without a bond hearing. The Supreme Court has held "
            "that the Due Process Clause applies to all persons within the United "
            "States, including aliens, whether their presence is lawful, unlawful, "
            "temporary, or permanent. Zadvydas v. Davis, 533 U.S. 678 (2001)."
        ),
        "",
        "II. ARGUMENT",
        "",
        "A. Prolonged Detention Without a Bond Hearing Violates Due Process",
        "",
        (
            "In Zadvydas, the Supreme Court held that the government may not detain "
            "an alien indefinitely beyond the removal period. The Court established "
            "a presumptive six-month limit on post-removal-order detention. This "
            "principle was extended to pre-removal detention in Jennings v. "
            "Rodriguez, 583 U.S. 281 (2018), where the Court addressed the scope "
            "of mandatory detention under 8 U.S.C. § 1226(c)."
        ),
        "",
        (
            "The Ninth Circuit has consistently required bond hearings for immigrants "
            "detained for prolonged periods. In Rodriguez v. Robbins, 804 F.3d 1060 "
            "(9th Cir. 2015), the court held that detained immigrants are entitled "
            "to bond hearings every six months. Although the Supreme Court reversed "
            "on statutory grounds in Jennings, the Ninth Circuit has continued to "
            "require bond hearings on constitutional due process grounds."
        ),
        "",
        (
            "More recently, in Singh v. Holder, 638 F.3d 1196 (9th Cir. 2011), "
            "the Ninth Circuit held that due process requires an individualized "
            "bond hearing before an immigration judge after prolonged mandatory "
            "detention. The court emphasized that the government bears the burden "
            "of proving by clear and convincing evidence that continued detention "
            "is justified."
        ),
        "",
        "B. Petitioner's Detention Is Not Authorized by Statute",
        "",
        (
            "The statutory framework for immigration detention is found in "
            "8 U.S.C. §§ 1226 and 1231. The Supreme Court has construed these "
            "provisions narrowly to avoid serious constitutional concerns. "
            "See Clark v. Martinez, 543 U.S. 371 (2005) (applying Zadvydas's "
            "limitation to inadmissible aliens detained under § 1231(a)(6))."
        ),
        "",
        (
            "In Johnson v. Arteaga-Martinez, 596 U.S. 573 (2022), the Supreme "
            "Court held that § 1231(a)(6) does not require the government to "
            "provide bond hearings after six months of detention. However, the "
            "Court expressly left open whether the Due Process Clause independently "
            "requires such hearings, which is the basis of Petitioner's claim."
        ),
        "",
        (
            "The Ninth Circuit has addressed this gap in its post-Johnson "
            "jurisprudence. In Hernandez v. Garland, 956 F.3d 1108 (9th Cir. 2023), "
            "the court held that even after Johnson, the Due Process Clause requires "
            "bond hearings for lawful permanent residents detained for more than "
            "six months. See also Martinez-Lopez v. ICE Director, 834 F. Supp. 3d "
            "567 (C.D. Cal. 2023) (granting habeas relief to LPR detained fourteen "
            "months without bond hearing)."
        ),
        "",
        "C. The Government Cannot Justify Continued Detention",
        "",
        (
            "Even under the government's most favorable reading of the statute, "
            "Petitioner's fourteen-month detention without a hearing is unreasonable. "
            "The Supreme Court recognized in Demore v. Kim, 538 U.S. 510 (2003), "
            "that mandatory detention under § 1226(c) is constitutionally permissible "
            "only for the 'brief period' necessary to complete removal proceedings. "
            "Fourteen months far exceeds any reasonable interpretation of 'brief.'"
        ),
        "",
        (
            "The Ninth Circuit has established that when detention extends beyond "
            "what is reasonably necessary, due process requires a hearing. "
            "Diouf v. Napolitano, 634 F.3d 1081 (9th Cir. 2011). Here, Petitioner "
            "has been detained for over a year with no end in sight, as his removal "
            "proceedings remain pending before the BIA."
        ),
        "",
        "IV. CONCLUSION",
        "",
        (
            "Petitioner respectfully requests that this Court grant the writ of "
            "habeas corpus, order an immediate bond hearing before an immigration "
            "judge, or order Petitioner's release from custody."
        ),
    ],
    "ground_truth": {
        "REAL": [
            ("533 U.S. 678", "Zadvydas v. Davis"),
            ("583 U.S. 281", "Jennings v. Rodriguez"),
            ("804 F.3d 1060", "Rodriguez v. Robbins"),
            ("638 F.3d 1196", "Singh v. Holder"),
            ("543 U.S. 371", "Clark v. Martinez"),
            ("596 U.S. 573", "Johnson v. Arteaga-Martinez"),
            ("538 U.S. 510", "Demore v. Kim"),
            ("634 F.3d 1081", "Diouf v. Napolitano"),
        ],
        "FAKE": [
            ("956 F.3d 1108", "Hernandez v. Garland"),
            ("834 F. Supp. 3d 567", "Martinez-Lopez v. ICE Director"),
        ],
    },
}


ALL_BRIEFS = {
    "employment_discrimination_brief.docx": EMPLOYMENT_BRIEF,
    "contract_breach_brief.docx": CONTRACT_BRIEF,
    "first_amendment_brief.docx": FIRST_AMENDMENT_BRIEF,
    "immigration_habeas_brief.docx": IMMIGRATION_BRIEF,
}


def generate_docx(brief: dict, output_path: Path) -> None:
    """Generate a .docx file from a brief definition."""
    doc = Document()

    for line in brief["paragraphs"]:
        if line == "":
            doc.add_paragraph("")
        elif line.isupper() or line.startswith("Case No."):
            p = doc.add_paragraph(line)
            p.alignment = 1  # Center
        elif line.startswith(("A.", "B.", "C.", "I.", "II.", "III.", "IV.")):
            doc.add_heading(line, level=2)
        else:
            doc.add_paragraph(line)

    doc.save(str(output_path))


def main():
    out_dir = Path(__file__).resolve().parent / "test_documents" / "round2"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_real = 0
    total_fake = 0

    for filename, brief in ALL_BRIEFS.items():
        out_path = out_dir / filename
        generate_docx(brief, out_path)

        real_count = len(brief["ground_truth"]["REAL"])
        fake_count = len(brief["ground_truth"]["FAKE"])
        total_real += real_count
        total_fake += fake_count

        print(f"Generated: {filename}")
        print(f"  {real_count} real + {fake_count} fake citations")
        print(f"  Real:")
        for cite, name in brief["ground_truth"]["REAL"]:
            print(f"    ✓ {cite} — {name}")
        print(f"  Fake:")
        for cite, name in brief["ground_truth"]["FAKE"]:
            print(f"    ✗ {cite} — {name}")
        print()

    print(f"Total: {total_real} real + {total_fake} fake = {total_real + total_fake} citations across {len(ALL_BRIEFS)} briefs")


if __name__ == "__main__":
    main()
