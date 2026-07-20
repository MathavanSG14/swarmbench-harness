I work at the Treasury Board of Canada Secretariat and I'm preparing a compliance presentation for senior management next week. We publish open source repositories under our GitHub organisation at https://github.com/canada-ca and I need to know how well each of them is following the GC Digital Standards before I go into that meeting.

Start by going through our organisation page and listing every public repository we have. Then for every repository you find, go through each one on GitHub and pull together the following information into a spreadsheet. Some of this you can get quickly, some of it you'll need to actually read the files to figure out — I need it to be accurate, not estimated.

The five GC Digital Standards I'm measuring compliance against are:
1. Bilingual README — the README contains content in both English and French
2. Open licence — a licence file exists with an open licence (MIT, Apache, OGL-Canada, etc.)
3. Security policy — a SECURITY.md exists with real responsible disclosure instructions, not just a placeholder
4. Contributing guide — a CONTRIBUTING.md exists
5. Actively maintained — last commit was within the past 365 days

The other columns in the sheet are additional quality indicators to support the presentation — they don't count toward the formal compliance score.

Here are the columns I need in the sheet. Wherever a column below lists allowed values in parentheses, those are the ONLY values you may write for that column — do not invent your own wording or synonyms (for example, don't write "None", "Not specified", or "n/a" when the allowed set doesn't include them). If you cannot determine a value for any column, write exactly `Unknown` — this is the single standard way to mark missing information across every column in this sheet, with no exceptions.

- repo_name
- repo_url
- primary_language (the language GitHub reports as primary for the repo, or `Unknown`)
- readme_exists (Yes/No/Unknown)
- bilingual (Yes/No/Unknown — does the README have content in both English and French)
- readme_clarity (Poor/Fair/Good/Unknown — does it clearly explain what the project is, who it's for, and how to use it)
- licence (the short common licence name or SPDX id, e.g. "MIT" not "MIT License", or `Unknown` if there's no licence file or you can't determine it)
- security_policy (Present/Incomplete/Missing/Unknown — "incomplete" means the file exists but doesn't actually explain how to report a vulnerability. Check for SECURITY.md in the repo root, in .github/, AND in docs/ — GitHub recognises it in any of these three locations, so check all three before marking Missing)
- contributing_guide (Yes/No/Unknown)
- has_security_scanning_in_ci (Yes/No/No CI/Unknown — check the GitHub Actions workflows and see if any of them run a security scanner like CodeQL, npm audit, pip-audit, Snyk, or Trivy. Use "No CI" when the repo has no workflow files at all, OR when workflow files exist but the Actions tab shows zero runs ever (check this — a workflow file that has never actually executed, e.g. because Actions is disabled for the repo, is not real CI). Use "No" only when workflows exist AND have a real run history, but none of the runs include a security scanning step)
- has_tests_in_ci (Yes/No/No CI/Unknown — check the same workflow files for test steps like pytest, jest, npm test, go test. Same distinction as above: "No CI" covers both no workflow files at all AND workflow files that exist but have zero actual runs; "No" means workflows exist, have actually run, but don't include a test step)
- dependency_update_policy (Automated/Manual/None/Unknown — Dependabot or Renovate configured for the right ecosystem counts as Automated)
- issue_response_quality (Active/Stale/No Issues/Unknown — look at the 5 most recently updated open issues and check whether someone other than the original reporter — i.e. an actual maintainer, not the reporter replying to their own issue — has commented within the last 6 months, counting back from today's date, the date you are actually doing this audit)
- release_notes_quality (Detailed/Version-only/No Releases/Unknown — "Detailed" means the release description actually explains what changed, "Version-only" means it's just a tag/version number with no real description)
- last_commit_date (YYYY-MM-DD, the date of the most recent commit on the repository's default branch — not the "last pushed" timestamp, which can reflect a push to a different branch or tag and will be wrong — or `Unknown`)
- days_since_last_commit (integer, or `Unknown` — must be `Unknown` if and only if last_commit_date is also `Unknown`)
- maintained (Yes/No/Unknown — No if last commit was more than a year ago)
- open_issues_count (integer, or `Unknown` — count OPEN ISSUES ONLY, excluding open pull requests. GitHub's own repository-level open_issues_count field includes pull requests and will overcount; count actual issues instead)
- standards_met (count out of 5 — bilingual README, open licence present, security policy present, contributing guide exists, maintained within 365 days)
- compliance_status (Full/Partial/Non-compliant — Full means standards_met=5, Partial means standards_met is 2, 3, or 4, Non-compliant means standards_met is 0 or 1)
- gaps (list the specific standards this repo is failing)

Once the sheet is done I also need four charts for the presentation slides:

1. A pie chart showing the overall compliance split — how many repos are Full, Partial, and Non-compliant
2. A bar chart showing what percentage of repos pass each of the 5 GC Digital Standards — so I can see which standard is failing most across the org
3. A bar chart of the 10 worst-performing repos ranked by standards_met score
4. A histogram showing the distribution of days_since_last_commit — I want to show management how many repos have gone stale

Save the spreadsheet as /logs/agent/compliance_matrix.csv and the four charts as /logs/agent/chart_compliance_split.png, /logs/agent/chart_standards_pass_rate.png, /logs/agent/chart_worst_repos.png, and /logs/agent/chart_commit_staleness.png.

Also write a short briefing note to /logs/agent/output.json in this format:

```json
{
  "total_repos_audited": "<int>",
  "fully_compliant": "<int>",
  "partially_compliant": "<int>",
  "non_compliant": "<int>",
  "most_common_gap": "<str>",
  "highest_risk_repos": [
    { "repo_name": "<str>", "reason": "<str>" }
  ],
  "briefing_note": "<str — 2 to 3 paragraphs for senior management. Name specific high-risk repos. State the overall compliance rate. Recommend the top 3 actions before the Treasury Board presentation.>"
}
```

Do not fabricate any field. If you cannot access a repository page at all, record `Unknown` for every field of that repo and move on.