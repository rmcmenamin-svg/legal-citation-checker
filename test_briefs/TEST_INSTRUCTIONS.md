/Users/ryanmcmenamin/.openclaw/workspace/fake_citation_test_briefs/TEST_INSTRUCTIONS.md
# Fake Citation Test Briefs

## Purpose
Test citation checker's ability to detect completely fabricated (hallucinated) citations.

## Files
- **FAKE-Deckers-Test-Brief.docx**: 10 fake citations
- **FAKE-Wang-Test-Brief.docx**: 10 fake citations
- **FAKE-Xu-Test-Brief.docx**: 10 fake citations
- **FAKE-Tapestry-Test-Brief.docx**: 10 fake citations

## Fake Citations Included
1. `Smith v. Jones, 123 Cal.App.5th 456 (2024)`
2. `Doe v. Roe, 77 Cal.App.6th 777 (2024)`
3. `In re Fake Estate, 999 Cal. 888 (2024)`
4. `Plaintiff v. Defendant, 88 Cal.5th 1111 (2024)`
5. `Baker v. Cook, 303 Cal.App.5th 2222 (2024)`
6. `Citizen v. Government, 999 U.S. 123 (2024)`
7. `Test v. Example, 101 Cal.4th 555 (2024)`
8. `Corporation v. Individual, 456 F.3d 789 (2024)`
9. `State v. Citizen, 789 Cal.App.7th 333 (2024)`
10. `Company v. Competitor, 222 Cal.App.8th 444 (2024)`

## Expected Results
1. Citation checker should EXTRACT all fake citations
2. Citation checker should FLAG them as hallucinations (not found in legal databases)
3. Report should show 100% fake citation rate for these test files

## Testing Command
```bash
python3 citation_checker.py --input fake_citation_test_briefs/ --output fake_citation_report.json
```

## Validation
A correct citation checker should report:
- Total citations found: 10 per brief
- Fake citations detected: 10 per brief  
- Real citations found: 0 per brief
- Hallucination rate: 100%
