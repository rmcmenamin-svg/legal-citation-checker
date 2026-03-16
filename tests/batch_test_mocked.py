#!/usr/bin/env python3
"""Batch test with mocked CourtListener API responses.

Since we can't reach external APIs from this environment, this test
patches _http_get_json to return realistic responses. This lets us
validate the full verification pipeline logic: extraction, fuzzy matching,
docket search, hallucination detection, and reporting.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from legal_citation_checker.pipeline import CitationChecker
from legal_citation_checker.models import CitationAudit

# ── Mock CourtListener database ────────────────────────────────────────
# Real cases that should be in CourtListener's database.
# Format: citation_key -> {"caseName": ..., "dateFiled": ..., "citations": [...]}

MOCK_OPINION_DB = {
    # Supreme Court landmarks
    "389 U.S. 347": {
        "caseName": "Katz v. United States",
        "dateFiled": "1967-12-18",
        "citation": ["389 U.S. 347"],
        "absolute_url": "/opinion/107564/katz-v-united-states/",
    },
    "585 U.S. 296": {
        "caseName": "Carpenter v. United States",
        "dateFiled": "2018-06-22",
        "citation": ["585 U.S. 296", "138 S. Ct. 2206"],
        "absolute_url": "/opinion/4512950/carpenter-v-united-states/",
    },
    "573 U.S. 373": {
        "caseName": "Riley v. California",
        "dateFiled": "2014-06-25",
        "citation": ["573 U.S. 373", "134 S. Ct. 2473"],
        "absolute_url": "/opinion/2648006/riley-v-california/",
    },
    "442 U.S. 735": {
        "caseName": "Smith v. Maryland",
        "dateFiled": "1979-06-20",
        "citation": ["442 U.S. 735"],
        "absolute_url": "/opinion/110091/smith-v-maryland/",
    },
    "556 U.S. 332": {
        "caseName": "Arizona v. Gant",
        "dateFiled": "2009-04-21",
        "citation": ["556 U.S. 332", "129 S. Ct. 1710"],
        "absolute_url": "/opinion/145861/arizona-v-gant/",
    },
    "437 U.S. 385": {
        "caseName": "Mincey v. Arizona",
        "dateFiled": "1978-06-21",
        "citation": ["437 U.S. 385"],
        "absolute_url": "/opinion/109846/mincey-v-arizona/",
    },
    "489 U.S. 602": {
        "caseName": "Skinner v. Railway Labor Executives' Assn.",
        "dateFiled": "1989-03-21",
        "citation": ["489 U.S. 602"],
        "absolute_url": "/opinion/112262/skinner-v-railway-labor-executives-assn/",
    },
    "578 U.S. 330": {
        "caseName": "Spokeo, Inc. v. Robins",
        "dateFiled": "2016-05-16",
        "citation": ["578 U.S. 330", "136 S. Ct. 1540"],
        "absolute_url": "/opinion/3210756/spokeo-inc-v-robins/",
    },
    "594 U.S. 413": {
        "caseName": "TransUnion LLC v. Ramirez",
        "dateFiled": "2021-06-25",
        "citation": ["594 U.S. 413", "141 S. Ct. 2190"],
        "absolute_url": "/opinion/4196490/transunion-llc-v-ramirez/",
    },
    "565 U.S. 400": {
        "caseName": "United States v. Jones",
        "dateFiled": "2012-01-23",
        "citation": ["565 U.S. 400", "132 S. Ct. 945"],
        "absolute_url": "/opinion/534543/united-states-v-jones/",
    },
    # Brown v. Board - real_brief.docx
    "347 U.S. 483": {
        "caseName": "Brown v. Board of Education of Topeka",
        "dateFiled": "1954-05-17",
        "citation": ["347 U.S. 483"],
        "absolute_url": "/opinion/105718/brown-v-board-of-education/",
    },
    "372 U.S. 335": {
        "caseName": "Gideon v. Wainwright",
        "dateFiled": "1963-03-18",
        "citation": ["372 U.S. 335"],
        "absolute_url": "/opinion/106541/gideon-v-wainwright/",
    },
    "466 U.S. 668": {
        "caseName": "Strickland v. Washington",
        "dateFiled": "1984-05-14",
        "citation": ["466 U.S. 668"],
        "absolute_url": "/opinion/111170/strickland-v-washington/",
    },
    "367 U.S. 643": {
        "caseName": "Mapp v. Ohio",
        "dateFiled": "1961-06-19",
        "citation": ["367 U.S. 643"],
        "absolute_url": "/opinion/106285/mapp-v-ohio/",
    },
    "232 U.S. 383": {
        "caseName": "Weeks v. United States",
        "dateFiled": "1914-02-24",
        "citation": ["232 U.S. 383"],
        "absolute_url": "/opinion/98087/weeks-v-united-states/",
    },
    # New York Times v. Sullivan - mixed_brief.docx
    "376 U.S. 254": {
        "caseName": "New York Times Co. v. Sullivan",
        "dateFiled": "1964-03-09",
        "citation": ["376 U.S. 254"],
        "absolute_url": "/opinion/106761/new-york-times-co-v-sullivan/",
    },
    "384 U.S. 436": {
        "caseName": "Miranda v. Arizona",
        "dateFiled": "1966-06-13",
        "citation": ["384 U.S. 436"],
        "absolute_url": "/opinion/107252/miranda-v-arizona/",
    },
    # Delaware cases
    "473 A.2d 805": {
        "caseName": "Aronson v. Lewis",
        "dateFiled": "1984-03-01",
        "citation": ["473 A.2d 805"],
        "absolute_url": "/opinion/1539847/aronson-v-lewis/",
    },
    "73 A.3d 697": {
        "caseName": "Kahn v. M&F Worldwide Corp.",
        "dateFiled": "2014-03-14",
        "citation": ["73 A.3d 697"],
        "absolute_url": "/opinion/2639310/kahn-v-mf-worldwide/",
    },
    "94 A.3d 956": {
        "caseName": "Corwin v. KKR Financial Holdings LLC",
        "dateFiled": "2015-10-02",
        "citation": ["94 A.3d 956"],
        "absolute_url": "/opinion/2998734/corwin-v-kkr-financial/",
    },
    # ── Round 2: Employment Discrimination ──
    "477 U.S. 57": {
        "caseName": "Meritor Savings Bank, FSB v. Vinson",
        "dateFiled": "1986-06-19",
        "citation": ["477 U.S. 57"],
        "absolute_url": "/opinion/111602/meritor-savings-bank-v-vinson/",
    },
    "510 U.S. 17": {
        "caseName": "Harris v. Forklift Systems, Inc.",
        "dateFiled": "1993-11-09",
        "citation": ["510 U.S. 17"],
        "absolute_url": "/opinion/112892/harris-v-forklift-systems/",
    },
    "411 U.S. 792": {
        "caseName": "McDonnell Douglas Corp. v. Green",
        "dateFiled": "1973-05-14",
        "citation": ["411 U.S. 792"],
        "absolute_url": "/opinion/108786/mcdonnell-douglas-v-green/",
    },
    "795 F.3d 297": {
        "caseName": "Littlejohn v. City of New York",
        "dateFiled": "2015-08-03",
        "citation": ["795 F.3d 297"],
        "absolute_url": "/opinion/3174894/littlejohn-v-city-of-new-york/",
    },
    "523 U.S. 75": {
        "caseName": "Oncale v. Sundowner Offshore Services, Inc.",
        "dateFiled": "1998-03-04",
        "citation": ["523 U.S. 75"],
        "absolute_url": "/opinion/118222/oncale-v-sundowner/",
    },
    "548 U.S. 53": {
        "caseName": "Burlington Northern & Santa Fe Railway Co. v. White",
        "dateFiled": "2006-06-22",
        "citation": ["548 U.S. 53"],
        "absolute_url": "/opinion/145652/burlington-northern-v-white/",
    },
    "524 U.S. 775": {
        "caseName": "Faragher v. City of Boca Raton",
        "dateFiled": "1998-06-26",
        "citation": ["524 U.S. 775"],
        "absolute_url": "/opinion/118273/faragher-v-city-of-boca-raton/",
    },
    "524 U.S. 742": {
        "caseName": "Burlington Industries, Inc. v. Ellerth",
        "dateFiled": "1998-06-26",
        "citation": ["524 U.S. 742"],
        "absolute_url": "/opinion/118272/burlington-industries-v-ellerth/",
    },
    "570 U.S. 421": {
        "caseName": "Vance v. Ball State University",
        "dateFiled": "2013-06-24",
        "citation": ["570 U.S. 421"],
        "absolute_url": "/opinion/1970981/vance-v-ball-state-university/",
    },
    "450 U.S. 248": {
        "caseName": "Texas Dept. of Community Affairs v. Burdine",
        "dateFiled": "1981-03-04",
        "citation": ["450 U.S. 248"],
        "absolute_url": "/opinion/110472/texas-dept-v-burdine/",
    },
    # ── Round 2: Contract Law ──
    "198 U.S. 45": {
        "caseName": "Lochner v. New York",
        "dateFiled": "1905-04-17",
        "citation": ["198 U.S. 45"],
        "absolute_url": "/opinion/96405/lochner-v-new-york/",
    },
    "512 F.3d 86": {
        "caseName": "Norfolk Southern Railway Co. v. Basell USA Inc.",
        "dateFiled": "2008-01-09",
        "citation": ["512 F.3d 86"],
        "absolute_url": "/opinion/198426/norfolk-southern-v-basell/",
    },
    "530 U.S. 604": {
        "caseName": "Mobil Oil Exploration & Producing Southeast, Inc. v. United States",
        "dateFiled": "2000-06-26",
        "citation": ["530 U.S. 604"],
        "absolute_url": "/opinion/118391/mobil-oil-v-united-states/",
    },
    "379 F.3d 24": {
        "caseName": "Lucent Technologies, Inc. v. Tatung Co.",
        "dateFiled": "2004-08-03",
        "citation": ["379 F.3d 24"],
        "absolute_url": "/opinion/178234/lucent-technologies-v-tatung/",
    },
    "346 F. Supp. 2d 628": {
        "caseName": "In re WorldCom, Inc. Securities Litigation",
        "dateFiled": "2004-11-18",
        "citation": ["346 F. Supp. 2d 628"],
        "absolute_url": "/opinion/228673/in-re-worldcom/",
    },
    "878 A.2d 434": {
        "caseName": "Dunlap v. State Farm Fire & Casualty Co.",
        "dateFiled": "2005-06-01",
        "citation": ["878 A.2d 434"],
        "absolute_url": "/opinion/2639311/dunlap-v-state-farm/",
    },
    # ── Round 2: First Amendment ──
    "408 U.S. 92": {
        "caseName": "Police Dept. of City of Chicago v. Mosley",
        "dateFiled": "1972-06-26",
        "citation": ["408 U.S. 92"],
        "absolute_url": "/opinion/108612/police-dept-v-mosley/",
    },
    "576 U.S. 155": {
        "caseName": "Reed v. Town of Gilbert",
        "dateFiled": "2015-06-18",
        "citation": ["576 U.S. 155"],
        "absolute_url": "/opinion/2931016/reed-v-town-of-gilbert/",
    },
    "408 U.S. 665": {
        "caseName": "Branzburg v. Hayes",
        "dateFiled": "1972-06-29",
        "citation": ["408 U.S. 665"],
        "absolute_url": "/opinion/108637/branzburg-v-hayes/",
    },
    "655 F.3d 78": {
        "caseName": "Glik v. Cunniffe",
        "dateFiled": "2011-08-26",
        "citation": ["655 F.3d 78"],
        "absolute_url": "/opinion/625839/glik-v-cunniffe/",
    },
    "573 U.S. 464": {
        "caseName": "McCullen v. Coakley",
        "dateFiled": "2014-06-26",
        "citation": ["573 U.S. 464"],
        "absolute_url": "/opinion/2648009/mccullen-v-coakley/",
    },
    "491 U.S. 781": {
        "caseName": "Ward v. Rock Against Racism",
        "dateFiled": "1989-06-22",
        "citation": ["491 U.S. 781"],
        "absolute_url": "/opinion/112338/ward-v-rock-against-racism/",
    },
    "283 U.S. 697": {
        "caseName": "Near v. Minnesota ex rel. Olson",
        "dateFiled": "1931-06-01",
        "citation": ["283 U.S. 697"],
        "absolute_url": "/opinion/101824/near-v-minnesota/",
    },
    "403 U.S. 713": {
        "caseName": "New York Times Co. v. United States",
        "dateFiled": "1971-06-30",
        "citation": ["403 U.S. 713"],
        "absolute_url": "/opinion/108369/new-york-times-v-united-states/",
    },
    "558 U.S. 310": {
        "caseName": "Citizens United v. Federal Election Commission",
        "dateFiled": "2010-01-21",
        "citation": ["558 U.S. 310"],
        "absolute_url": "/opinion/145741/citizens-united-v-fec/",
    },
    "512 U.S. 622": {
        "caseName": "Turner Broadcasting System, Inc. v. FCC",
        "dateFiled": "1994-06-27",
        "citation": ["512 U.S. 622"],
        "absolute_url": "/opinion/112932/turner-broadcasting-v-fcc/",
    },
    # ── Round 2: Immigration ──
    "533 U.S. 678": {
        "caseName": "Zadvydas v. Davis",
        "dateFiled": "2001-06-28",
        "citation": ["533 U.S. 678"],
        "absolute_url": "/opinion/118465/zadvydas-v-davis/",
    },
    "583 U.S. 281": {
        "caseName": "Jennings v. Rodriguez",
        "dateFiled": "2018-02-27",
        "citation": ["583 U.S. 281"],
        "absolute_url": "/opinion/4387734/jennings-v-rodriguez/",
    },
    "804 F.3d 1060": {
        "caseName": "Rodriguez v. Robbins",
        "dateFiled": "2015-10-28",
        "citation": ["804 F.3d 1060"],
        "absolute_url": "/opinion/3207012/rodriguez-v-robbins/",
    },
    "638 F.3d 1196": {
        "caseName": "Singh v. Holder",
        "dateFiled": "2011-04-12",
        "citation": ["638 F.3d 1196"],
        "absolute_url": "/opinion/601891/singh-v-holder/",
    },
    "543 U.S. 371": {
        "caseName": "Clark v. Martinez",
        "dateFiled": "2005-01-12",
        "citation": ["543 U.S. 371"],
        "absolute_url": "/opinion/137744/clark-v-martinez/",
    },
    "596 U.S. 573": {
        "caseName": "Johnson v. Arteaga-Martinez",
        "dateFiled": "2022-06-13",
        "citation": ["596 U.S. 573"],
        "absolute_url": "/opinion/4626873/johnson-v-arteaga-martinez/",
    },
    "538 U.S. 510": {
        "caseName": "Demore v. Kim",
        "dateFiled": "2003-04-29",
        "citation": ["538 U.S. 510"],
        "absolute_url": "/opinion/127910/demore-v-kim/",
    },
    "634 F.3d 1081": {
        "caseName": "Diouf v. Napolitano",
        "dateFiled": "2011-03-14",
        "citation": ["634 F.3d 1081"],
        "absolute_url": "/opinion/591182/diouf-v-napolitano/",
    },
    # ── Round 2: Sneaky Brief (real cases correctly cited) ──
    "556 U.S. 662": {
        "caseName": "Ashcroft v. Iqbal",
        "dateFiled": "2009-05-18",
        "citation": ["556 U.S. 662"],
        "absolute_url": "/opinion/145875/ashcroft-v-iqbal/",
    },
    "550 U.S. 544": {
        "caseName": "Bell Atlantic Corp. v. Twombly",
        "dateFiled": "2007-05-21",
        "citation": ["550 U.S. 544"],
        "absolute_url": "/opinion/145711/bell-atlantic-v-twombly/",
    },
    "114 F.3d 1410": {
        "caseName": "In re Burlington Coat Factory Securities Litigation",
        "dateFiled": "1997-06-11",
        "citation": ["114 F.3d 1410"],
        "absolute_url": "/opinion/745671/in-re-burlington-coat-factory/",
    },
    "476 U.S. 858": {
        "caseName": "East River Steamship Corp. v. Transamerica Delaval Inc.",
        "dateFiled": "1986-06-16",
        "citation": ["476 U.S. 858"],
        "absolute_url": "/opinion/111582/east-river-steamship-v-transamerica/",
    },
    "573 U.S. 682": {
        "caseName": "Burwell v. Hobby Lobby Stores, Inc.",
        "dateFiled": "2014-06-30",
        "citation": ["573 U.S. 682"],
        "absolute_url": "/opinion/2648010/burwell-v-hobby-lobby/",
    },
    "534 U.S. 204": {
        "caseName": "Great-West Life & Annuity Insurance Co. v. Knudson",
        "dateFiled": "2002-01-08",
        "citation": ["534 U.S. 204"],
        "absolute_url": "/opinion/118503/great-west-life-v-knudson/",
    },
    # Sneaky: The REAL Dura Pharmaceuticals at its correct cite
    "544 U.S. 336": {
        "caseName": "Dura Pharmaceuticals, Inc. v. Broudo",
        "dateFiled": "2005-04-19",
        "citation": ["544 U.S. 336"],
        "absolute_url": "/opinion/137800/dura-pharmaceuticals-v-broudo/",
    },
    # Sneaky: The REAL Tellabs at its correct cite
    "551 U.S. 308": {
        "caseName": "Tellabs, Inc. v. Makor Issues & Rights, Ltd.",
        "dateFiled": "2007-06-21",
        "citation": ["551 U.S. 308"],
        "absolute_url": "/opinion/145723/tellabs-v-makor-issues/",
    },
}

# Known fake citations (should NOT be in the database)
KNOWN_FAKES = {
    # LLM brief fakes
    "847 F.3d 1203", "612 F. Supp. 3d 894", "923 F.3d 1108",
    "198 F. Supp. 3d 1142", "891 F.3d 445", "756 F.3d 1087",
    "834 F.3d 921", "743 F. Supp. 3d 201",
    # FAKE brief fakes
    "123 Cal. App. 5th 456", "999 Cal. 888", "88 Cal. 5th 1111",
    "303 Cal. App. 5th 2222", "999 U.S. 123", "101 Cal. 4th 555",
    "456 F.3d 789",
    # hallucinated_brief fakes
    "892 F.3d 1147", "567 U.S. 234", "445 F.3d 891", "789 F. Supp. 3d 456",
    # mixed_brief fakes
    "834 F.3d 1289", "512 F. Supp. 3d 789",
    # Round 2: Employment discrimination fakes
    "867 F.3d 1034", "538 F. Supp. 3d 445", "912 F.3d 678", "743 F. Supp. 3d 892",
    # Round 2: Contract law fakes
    "934 F.3d 567", "678 F. Supp. 3d 234", "845 F.3d 1122", "567 F. Supp. 3d 891",
    # Round 2: First Amendment fakes
    "891 F.3d 567", "823 F.3d 445", "945 F.3d 789",
    # Round 2: Immigration fakes
    "956 F.3d 1108", "834 F. Supp. 3d 567",
    # Round 2: Sneaky brief — real case names with WRONG citation numbers
    "552 U.S. 148",   # Dura Pharmaceuticals (real is 544 U.S. 336)
    "549 U.S. 457",   # Tellabs (real is 551 U.S. 308)
    "249 F.2d 458",   # Meinhard v. Salmon (real is 164 N.E. 545)
    "456 F.3d 823",   # Brophy v. Cities Service (real is 70 A.2d 5)
    "763 F.3d 209",   # Gutter v. Bollman (fully fake)
    "607 F.3d 356",   # Kottler v. Deutsche Bank (fully fake)
}


def _normalize_cite_key(cite: str) -> str:
    """Normalize a citation string for lookup: strip periods, extra spaces."""
    return " ".join(cite.replace(".", " ").split())


def mock_http_get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
    """Simulate CourtListener search API responses."""
    params = params or {}
    search_type = params.get("type", "o")

    # Build request URL for logging
    req_url = url

    # Extract the citation or query being searched
    citation_param = params.get("citation", "")
    q_param = params.get("q", "")

    # --- Tier 1: Citation field or citation query ---
    if citation_param:
        for db_cite, record in MOCK_OPINION_DB.items():
            if _normalize_cite_key(citation_param) == _normalize_cite_key(db_cite):
                return ({"count": 1, "results": [record]}, req_url, None)
        return ({"count": 0, "results": []}, req_url, None)

    if "citation:" in q_param:
        # Extract citation from citation:"..." query
        import re
        m = re.search(r'citation:"([^"]+)"', q_param)
        if m:
            cite_text = m.group(1)
            for db_cite, record in MOCK_OPINION_DB.items():
                if _normalize_cite_key(cite_text) == _normalize_cite_key(db_cite):
                    return ({"count": 1, "results": [record]}, req_url, None)
        return ({"count": 0, "results": []}, req_url, None)

    # --- Tier 2 / 2b: Party name or case name search ---
    # case_name structured field
    case_name_param = params.get("case_name", "")
    if case_name_param:
        results = []
        cn_lower = case_name_param.lower()
        for db_cite, record in MOCK_OPINION_DB.items():
            rn = record["caseName"].lower()
            # Check if any significant word from the query matches
            query_words = [w for w in cn_lower.split() if len(w) > 2 and w not in ("the", "and", "inc")]
            if any(w in rn for w in query_words):
                results.append(record)
        return ({"count": len(results), "results": results[:10]}, req_url, None)

    # Free-text q= search (quoted party name)
    if q_param:
        import re
        # Extract quoted terms
        quoted = re.findall(r'"([^"]+)"', q_param)
        if not quoted:
            quoted = [q_param]

        results = []
        for db_cite, record in MOCK_OPINION_DB.items():
            rn = record["caseName"].lower()
            for term in quoted:
                term_lower = term.lower()
                term_words = [w for w in term_lower.split() if len(w) > 2 and w not in ("the", "and", "inc", "llc", "corp")]
                if any(w in rn for w in term_words):
                    if search_type == "d":
                        # Return as a docket result
                        docket_result = {
                            "caseName": record["caseName"],
                            "dateFiled": record["dateFiled"],
                            "docket_id": hash(record["caseName"]) % 100000,
                            "absolute_url": f"/docket/{hash(record['caseName']) % 100000}/",
                        }
                        results.append(docket_result)
                    else:
                        results.append(record)
                    break

        return ({"count": len(results), "results": results[:10]}, req_url, None)

    return ({"count": 0, "results": []}, req_url, None)


# ── Google Scholar mock (Tier 3) ──────────────────────────────────────
# We don't mock Google Scholar HTML parsing since it requires BeautifulSoup
# handling; the mock for Tier 1/2 is sufficient to test the core logic.


def run_mocked_test():
    """Run all test briefs with mocked API and report results."""
    root = Path(__file__).resolve().parent.parent

    # Collect briefs
    briefs = []
    llm_brief = root / "tests" / "test_documents" / "llm_generated_brief.docx"
    if llm_brief.exists():
        briefs.append(("llm", llm_brief))

    fake_dir = root / "test_briefs"
    if fake_dir.exists():
        for f in sorted(fake_dir.glob("FAKE-*.docx")):
            briefs.append(("fake", f))

    # Round 2 briefs
    round2_dir = root / "tests" / "test_documents" / "round2"
    if round2_dir.exists():
        for f in sorted(round2_dir.glob("*.docx")):
            if "sneaky" in f.name:
                briefs.append(("sneaky", f))
            elif "employment" in f.name or "contract" in f.name or "first_amendment" in f.name or "immigration" in f.name:
                briefs.append(("mixed", f))
            else:
                briefs.append(("unknown", f))

    del_brief = root / "delaware_derivative_brief.docx"
    if del_brief.exists():
        briefs.append(("real", del_brief))

    test_docs = root / "tests" / "test_documents"
    for f in sorted(test_docs.glob("*.docx")):
        if f.name == "llm_generated_brief.docx":
            continue
        if "hallucinated" in f.name:
            briefs.append(("fake", f))
        elif "mixed" in f.name:
            briefs.append(("mixed", f))
        elif "real" in f.name:
            briefs.append(("real", f))
        else:
            briefs.append(("unknown", f))

    print(f"{'='*75}")
    print(f"  LEGAL CITATION CHECKER — BATCH TEST (Mocked CourtListener API)")
    print(f"  {len(briefs)} briefs | {len(MOCK_OPINION_DB)} real cases in mock DB")
    print(f"  {len(KNOWN_FAKES)} known fake citations to catch")
    print(f"{'='*75}\n")

    # Patch the verifier's HTTP method
    checker = CitationChecker(verbose=False, request_timeout=10.0)

    all_results = []
    totals = {"verified": 0, "hallucination": 0, "needs_review": 0, "skipped": 0, "total": 0}
    true_pos = 0  # Real correctly verified
    true_neg = 0  # Fake correctly flagged
    false_pos = 0  # Fake incorrectly verified
    false_neg = 0  # Real incorrectly flagged as hallucination

    with patch.object(checker._verifier, '_http_get_json', side_effect=mock_http_get_json):
        for brief_type, path in briefs:
            print(f"{'─'*75}")
            print(f"  {path.name}  (expected: {brief_type})")
            print(f"{'─'*75}")

            start = time.time()
            try:
                report = checker.process_document(str(path))
            except Exception as e:
                print(f"  ERROR: {e}\n")
                continue
            elapsed = time.time() - start

            v_count = sum(1 for a in report.citations if "erified" in a.status)
            h_count = sum(1 for a in report.citations if "allucination" in a.status)
            r_count = sum(1 for a in report.citations if "eview" in a.status)
            s_count = len(report.citations) - v_count - h_count - r_count

            totals["verified"] += v_count
            totals["hallucination"] += h_count
            totals["needs_review"] += r_count
            totals["skipped"] += s_count
            totals["total"] += len(report.citations)

            print(f"  {len(report.citations)} citations | {elapsed:.2f}s")
            print(f"  Verified: {v_count} | Hallucination: {h_count} | Review: {r_count} | Skip: {s_count}\n")

            for audit in report.citations:
                raw = audit.raw_citation
                norm_key = _normalize_cite_key(raw)
                is_in_db = any(_normalize_cite_key(k) == norm_key for k in MOCK_OPINION_DB)
                is_known_fake = any(_normalize_cite_key(f) == norm_key for f in KNOWN_FAKES)

                if "erified" in audit.status:
                    icon = "✅"
                    if is_known_fake:
                        icon = "❌ FALSE POS"
                        false_pos += 1
                    elif is_in_db:
                        true_pos += 1
                elif "allucination" in audit.status:
                    icon = "🔴"
                    if is_in_db:
                        icon = "❌ FALSE NEG"
                        false_neg += 1
                    elif is_known_fake:
                        true_neg += 1
                elif "eview" in audit.status:
                    icon = "⚠️ "
                else:
                    icon = "⏭️ "

                evidence_short = audit.evidence[:60] if audit.evidence else ""
                print(f"    {icon}  [{audit.confidence:3d}%] {raw[:55]}")
                if evidence_short:
                    print(f"         {evidence_short}")

            print()

            all_results.append({
                "file": path.name,
                "type": brief_type,
                "time": round(elapsed, 2),
                "total": len(report.citations),
                "verified": v_count,
                "hallucination": h_count,
                "needs_review": r_count,
                "skipped": s_count,
                "citations": [
                    {
                        "raw": a.raw_citation,
                        "status": a.status,
                        "confidence": a.confidence,
                        "evidence": a.evidence[:200] if a.evidence else "",
                    }
                    for a in report.citations
                ],
            })

    # ── Summary ──
    t = totals
    total = max(t["total"], 1)
    print(f"\n{'='*75}")
    print(f"  SUMMARY")
    print(f"{'='*75}")
    print(f"  Briefs:          {len(all_results)}")
    print(f"  Total citations: {t['total']}")
    print(f"  Verified:        {t['verified']} ({100*t['verified']//total}%)")
    print(f"  Hallucinations:  {t['hallucination']} ({100*t['hallucination']//total}%)")
    print(f"  Needs Review:    {t['needs_review']} ({100*t['needs_review']//total}%)")
    print(f"  Skipped:         {t['skipped']} ({100*t['skipped']//total}%)")
    print()
    print(f"  ACCURACY (against ground truth):")
    print(f"    True positives  (real correctly verified):       {true_pos}")
    print(f"    True negatives  (fake correctly flagged):        {true_neg}")
    print(f"    False positives (fake incorrectly verified):     {false_pos}")
    print(f"    False negatives (real missed/flagged halluc.):   {false_neg}")
    precision = true_pos / max(true_pos + false_pos, 1)
    recall = true_pos / max(true_pos + false_neg, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.001)
    print(f"    Precision: {precision:.1%}  |  Recall: {recall:.1%}  |  F1: {f1:.1%}")

    # Save results
    out_path = root / "memory" / "batch-test-mocked-results.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved: {out_path}")


if __name__ == "__main__":
    run_mocked_test()
