"""Generate a fake LLM-authored legal brief with hallucinated citations.

Simulates what a lesser LLM (e.g. Mistral-7B, Llama-2-7B) typically produces
when asked to write a legal brief: a mix of real landmark cases and
plausible-sounding but fabricated citations.

The fabricated citations follow patterns LLMs commonly generate:
- Real reporter abbreviations with wrong volume/page numbers
- Real case names paired with wrong citations
- Completely invented case names with valid-looking citations
- Real cases with slightly wrong page numbers
"""

from pathlib import Path

try:
    from docx import Document  # type: ignore
except ImportError:
    raise SystemExit("python-docx required: pip install python-docx")

BRIEF_TEXT = [
    "IN THE UNITED STATES DISTRICT COURT",
    "FOR THE NORTHERN DISTRICT OF CALIFORNIA",
    "",
    "JOHN DOE, Plaintiff,",
    "v.",
    "TECHCORP INC., Defendant.",
    "",
    "Case No. 3:25-cv-01234",
    "",
    "MEMORANDUM OF LAW IN SUPPORT OF PLAINTIFF'S MOTION FOR SUMMARY JUDGMENT",
    "",
    "I. INTRODUCTION",
    "",
    (
        "Plaintiff John Doe brings this action under 42 U.S.C. § 1983 alleging that "
        "Defendant TechCorp Inc. violated his Fourth Amendment rights through warrantless "
        "surveillance of his digital communications. The Supreme Court has long recognized "
        "that the Fourth Amendment protects reasonable expectations of privacy. "
        "Katz v. United States, 389 U.S. 347 (1967)."
    ),
    "",
    "II. STATEMENT OF FACTS",
    "",
    (
        "From January 2024 through August 2024, Defendant conducted continuous monitoring "
        "of Plaintiff's electronic communications without obtaining a warrant or any form "
        "of judicial authorization. This surveillance included the collection of cell-site "
        "location information (CSLI), which the Supreme Court addressed in "
        "Carpenter v. United States, 585 U.S. 296 (2018)."
    ),
    "",
    (
        "The breadth of Defendant's surveillance program is unprecedented. As the Court "
        "noted in Thompson v. Digital Analytics Corp., 847 F.3d 1203 (9th Cir. 2021), "
        "private entities acting under color of state law are subject to the same "
        "constitutional constraints as government actors. See also Rodriguez v. DataMine "
        "Systems, 612 F. Supp. 3d 894 (N.D. Cal. 2023)."
    ),
    "",
    "III. ARGUMENT",
    "",
    "A. The Fourth Amendment Applies to Digital Surveillance by Private Actors",
    "",
    (
        "The Fourth Amendment's protections extend to digital communications and metadata. "
        "Riley v. California, 573 U.S. 373 (2014). In Riley, the Court unanimously held "
        "that police must obtain a warrant before searching a cell phone seized during an "
        "arrest, recognizing the vast quantity of personal information contained in modern "
        "digital devices."
    ),
    "",
    (
        "This principle was extended to historical cell-site location information in "
        "Carpenter v. United States, 585 U.S. 296 (2018), where Chief Justice Roberts "
        "wrote that individuals maintain a legitimate expectation of privacy in the "
        "record of their physical movements as captured through CSLI. The Court rejected "
        "the argument that the third-party doctrine of Smith v. Maryland, 442 U.S. 735 "
        "(1979) eliminated Fourth Amendment protections for such data."
    ),
    "",
    (
        "Courts have consistently applied these principles to private actors operating "
        "under state authority. In Henderson v. Clearview Analytics, 923 F.3d 1108 "
        "(7th Cir. 2022), the Seventh Circuit held that a private technology company "
        "performing surveillance at the direction of law enforcement was a state actor "
        "subject to Fourth Amendment constraints. Similarly, in Martinez v. Palantir "
        "Technologies, 198 F. Supp. 3d 1142 (C.D. Cal. 2022), the court found that "
        "a private contractor's data collection activities constituted state action "
        "where the contractor was 'inextricably intertwined' with government operations."
    ),
    "",
    "B. Defendant's Warrantless Surveillance Violates the Fourth Amendment",
    "",
    (
        "Warrantless searches are per se unreasonable under the Fourth Amendment, "
        "subject only to a few specifically established and well-delineated exceptions. "
        "Arizona v. Gant, 556 U.S. 332 (2009); Mincey v. Arizona, 437 U.S. 385 (1978). "
        "None of these exceptions apply here."
    ),
    "",
    (
        "The government cannot circumvent the warrant requirement by enlisting private "
        "parties to conduct surveillance on its behalf. As the Supreme Court held in "
        "Skinner v. Railway Labor Executives' Ass'n, 489 U.S. 602 (1989), when a "
        "private entity acts as an instrument or agent of the government, its actions "
        "are subject to Fourth Amendment scrutiny."
    ),
    "",
    (
        "The Ninth Circuit has specifically addressed this issue in the digital context. "
        "In Collins v. SafeTrack Inc., 891 F.3d 445 (9th Cir. 2023), the court held "
        "that a private company's systematic collection of geolocation data at the "
        "request of federal agents constituted an unlawful search. The court emphasized "
        "that 'the government may not do through private intermediaries what the "
        "Constitution forbids it from doing directly.' Id. at 458."
    ),
    "",
    (
        "Furthermore, in Patterson v. United States, 756 F.3d 1087 (9th Cir. 2019), "
        "the court applied strict scrutiny to government-directed private surveillance "
        "programs, finding that the government's interest in law enforcement did not "
        "outweigh the plaintiff's reasonable expectation of privacy in digital "
        "communications metadata."
    ),
    "",
    "C. Plaintiff Has Suffered Cognizable Injury",
    "",
    (
        "The violation of Fourth Amendment rights constitutes a cognizable injury "
        "sufficient to establish standing. See Spokeo, Inc. v. Robins, 578 U.S. 330 "
        "(2016). The Supreme Court has recognized that the unlawful collection of "
        "personal information, without more, can constitute an injury in fact. "
        "TransUnion LLC v. Ramirez, 594 U.S. 413 (2021)."
    ),
    "",
    (
        "Multiple circuits have found standing in digital surveillance cases. "
        "In Walker v. NSA Digital Programs, 834 F.3d 921 (D.C. Cir. 2020), the "
        "D.C. Circuit held that plaintiffs whose communications metadata was collected "
        "without a warrant had suffered a concrete and particularized injury. See also "
        "Chen v. Federal Bureau of Investigation, 743 F. Supp. 3d 201 (S.D.N.Y. 2022) "
        "(finding standing where plaintiff's digital footprint was systematically "
        "harvested by government contractors)."
    ),
    "",
    "IV. CONCLUSION",
    "",
    (
        "For the foregoing reasons, Plaintiff respectfully requests that this Court "
        "grant his Motion for Summary Judgment. The warrantless digital surveillance "
        "conducted by Defendant under the direction of government agents violated "
        "Plaintiff's Fourth Amendment rights as established by Carpenter, Riley, and "
        "their progeny. See also United States v. Jones, 565 U.S. 400 (2012) "
        "(recognizing Fourth Amendment implications of long-term GPS surveillance)."
    ),
    "",
    "Respectfully submitted,",
    "",
    "____________________________",
    "Attorney for Plaintiff",
]

# Track which citations are real vs fabricated
CITATION_KEY = {
    # REAL citations (should verify)
    "Katz v. United States, 389 U.S. 347 (1967)": "REAL",
    "Carpenter v. United States, 585 U.S. 296 (2018)": "REAL",
    "Riley v. California, 573 U.S. 373 (2014)": "REAL",
    "Smith v. Maryland, 442 U.S. 735 (1979)": "REAL",
    "Arizona v. Gant, 556 U.S. 332 (2009)": "REAL",
    "Mincey v. Arizona, 437 U.S. 385 (1978)": "REAL",
    "Skinner v. Railway Labor Executives' Ass'n, 489 U.S. 602 (1989)": "REAL",
    "Spokeo, Inc. v. Robins, 578 U.S. 330 (2016)": "REAL",
    "TransUnion LLC v. Ramirez, 594 U.S. 413 (2021)": "REAL",
    "United States v. Jones, 565 U.S. 400 (2012)": "REAL",
    # FABRICATED citations (should be flagged)
    "Thompson v. Digital Analytics Corp., 847 F.3d 1203 (9th Cir. 2021)": "FAKE",
    "Rodriguez v. DataMine Systems, 612 F. Supp. 3d 894 (N.D. Cal. 2023)": "FAKE",
    "Henderson v. Clearview Analytics, 923 F.3d 1108 (7th Cir. 2022)": "FAKE",
    "Martinez v. Palantir Technologies, 198 F. Supp. 3d 1142 (C.D. Cal. 2022)": "FAKE",
    "Collins v. SafeTrack Inc., 891 F.3d 445 (9th Cir. 2023)": "FAKE",
    "Patterson v. United States, 756 F.3d 1087 (9th Cir. 2019)": "FAKE",
    "Walker v. NSA Digital Programs, 834 F.3d 921 (D.C. Cir. 2020)": "FAKE",
    "Chen v. Federal Bureau of Investigation, 743 F. Supp. 3d 201 (S.D.N.Y. 2022)": "FAKE",
}


def generate(output_path: Path) -> None:
    doc = Document()

    for line in BRIEF_TEXT:
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

    real_count = sum(1 for v in CITATION_KEY.values() if v == "REAL")
    fake_count = sum(1 for v in CITATION_KEY.values() if v == "FAKE")
    print(f"Generated brief at: {output_path}")
    print(f"  {real_count} real citations (should verify)")
    print(f"  {fake_count} fabricated citations (should be flagged)")
    print(f"  + 1 statute (42 U.S.C. § 1983, should be filtered)")
    print()
    print("Citation key:")
    for cite, status in CITATION_KEY.items():
        marker = "✓" if status == "REAL" else "✗"
        print(f"  {marker} {cite}")


if __name__ == "__main__":
    out = Path(__file__).parent / "test_documents" / "llm_generated_brief.docx"
    out.parent.mkdir(exist_ok=True)
    generate(out)
