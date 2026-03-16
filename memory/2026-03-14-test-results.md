# Citation Checker Test Results - 2026-03-14

## Test Brief
**File:** `/Users/ryanmcmenamin/Cases/650956/Documents/2025-03-10 Franklyn Daubert motion (Client Review) JD comments.docx`
**Processing time:** 3.46 seconds

## Results Summary
- **Total citations:** 10
- **✅ Verified:** 6 (60%) - Daubert (509 U.S. 579), Bank of Utah (369 F.2d 19), Amstar (615 F.2d 252), J&J Snack (220 F. Supp. 2d 358), Kleen Products (306 F.R.D. 585)
- **⚠️ Needs Review:** 3 - Westlaw WL citations (2024 WL 2208099 x2, 2022 WL 421135)
- **🔴 Potential Hallucination:** 1 - 79 Trademark Rep. 1 (journal, not in CourtListener)

## Westlaw Issue
**Root cause:** WL citations detected via regex `^\\d{4}\\s+WL\\s+\\d+$` and auto-flagged "Needs Review" without search.

**Impact:** 30% of citations unverified in this test.

## Files saved
- Full audit report available via CLI rerun