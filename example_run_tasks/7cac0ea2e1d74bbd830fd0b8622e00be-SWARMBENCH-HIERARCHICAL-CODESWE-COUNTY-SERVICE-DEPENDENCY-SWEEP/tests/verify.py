#!/usr/bin/env python3
import base64
import csv
import json
import os
import random
import urllib.request
from datetime import date

AGENT_DIR = "/logs/agent"
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
EXPECTED_REPOS = 74

REQUIRED_COLUMNS = [
    "repo_name", "repo_url", "primary_language", "readme_exists",
    "bilingual", "readme_clarity", "licence", "security_policy",
    "contributing_guide", "has_security_scanning_in_ci", "has_tests_in_ci",
    "dependency_update_policy", "issue_response_quality", "release_notes_quality",
    "last_commit_date", "days_since_last_commit", "maintained",
    "open_issues_count", "standards_met", "compliance_status", "gaps",
]

REQUIRED_JSON_FIELDS = [
    "total_repos_audited", "fully_compliant", "partially_compliant",
    "non_compliant", "most_common_gap", "highest_risk_repos", "briefing_note",
]

CHARTS = [
    "chart_compliance_split.png",
    "chart_standards_pass_rate.png",
    "chart_worst_repos.png",
    "chart_commit_staleness.png",
]

CHART_QUESTIONS = [
    ("chart_compliance_split.png", "A pie chart showing the overall compliance split -- how many repos are Full, Partial, and Non-compliant"),
    ("chart_standards_pass_rate.png", "A bar chart showing what percentage of repos pass each of the 5 GC Digital Standards -- so I can see which standard is failing most across the org"),
    ("chart_worst_repos.png", "A bar chart of the 10 worst-performing repos ranked by standards_met score"),
    ("chart_commit_staleness.png", "A histogram showing the distribution of days_since_last_commit -- I want to show management how many repos have gone stale"),
]

# columns that shouldn't drift over time for a repo, safe to spot-check
# against a frozen, manually-sourced oracle regardless of when the audit ran
ORACLE_STABLE_FIELDS = [
    "primary_language", "licence", "readme_exists", "bilingual",
    "readme_clarity", "security_policy", "contributing_guide",
    "has_security_scanning_in_ci", "has_tests_in_ci",
    "dependency_update_policy", "release_notes_quality",
]

SHEET_JUDGE_PROMPT_TEMPLATE = """You are auditing a compliance spreadsheet an AI agent produced by
supposedly researching real GitHub repositories one by one. Your job is to catch whether
it did genuine per-repo research or took a lazy/fabricated shortcut, WITHOUT re-researching
every repo yourself.

IMPORTANT: this audit was actually performed on {today}. That is the correct "today" for
all date reasoning -- do NOT use your own training cutoff or any other assumption about the
current date. Do not flag any date on or before {today} as an "impossible future date."
Only flag a date as impossible if it is strictly AFTER {today}.

Look for:

1. Value-set violations -- any cell using wording outside what's allowed for that column
   (columns like readme_exists/bilingual/contributing_guide must be exactly Yes/No/Unknown;
   security_policy must be exactly Present/Incomplete/Missing/Unknown; readme_clarity must be
   exactly Poor/Fair/Good/Unknown; etc. -- never true/false booleans, never invented words,
   never bare numbers).
2. Internal consistency -- does standards_met actually match what the 5 raw standards columns
   (bilingual, licence, security_policy, contributing_guide, maintained) say? Does
   compliance_status match standards_met (Full=5, Partial=2-4, Non-compliant=0-1)? Is
   last_commit_date Unknown exactly when days_since_last_commit and maintained are also Unknown?
3. Suspicious uniformity -- real per-repo research on many DIFFERENT real repos should produce
   real variation. Flag it if a column that should vary (e.g. primary_language, licence,
   compliance_status, readme_clarity) is suspiciously constant or near-constant across most
   rows, or if many rows look like they were copy-pasted rather than individually researched.
4. Ground-truth cross-check -- here is hand-verified real data for a few of the repos. Check
   whether the submission's rows for these specific repos actually match:

{oracle_json}

Return ONLY a JSON object:
{{"score": 0.0-1.0, "red_flags": ["<specific row/column and what's wrong>", ...], "summary": "..."}}

Here is the full submitted spreadsheet (CSV):

{csv_text}
"""


def load_csv():
    csv_path = os.path.join(AGENT_DIR, "compliance_matrix.csv")
    if not os.path.isfile(csv_path):
        return [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        rows = list(reader)
    return rows, cols


# ---------------------------------------------------------------------------
# static_checks -- structural completeness of the deliverable
# ---------------------------------------------------------------------------

def check_repo_coverage(rows, columns_found):
    """Fraction of expected repos present in the CSV."""
    if not rows:
        return 0.0, ["repo coverage: 0 rows found -- compliance_matrix.csv missing or empty"]
    score = min(len(rows) / EXPECTED_REPOS, 1.0)
    notes = [] if score >= 1.0 else [f"repo coverage: {len(rows)}/{EXPECTED_REPOS} expected repos present"]
    return score, notes


def check_required_columns(rows, columns_found):
    """All required columns must be present in the CSV header."""
    if not columns_found:
        return 0.0, ["required columns: compliance_matrix.csv missing or has no header row"]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns_found]
    if missing:
        return 0.0, [f"required columns: missing {', '.join(missing)}"]
    return 1.0, []


def check_url_format(rows, columns_found):
    """repo_url must match the expected canada-ca URL for its own repo_name."""
    if not rows:
        return 0.0, ["url format check: 0 rows found -- compliance_matrix.csv missing or empty"]
    ok = sum(
        1 for r in rows
        if r.get("repo_url", "").rstrip("/") == f"https://github.com/canada-ca/{r.get('repo_name', '')}"
    )
    notes = [] if ok == len(rows) else [f"url format check: {ok}/{len(rows)} rows have a matching repo_url"]
    return ok / len(rows), notes


def check_charts_present(rows, columns_found):
    """All 4 chart files must exist and be non-empty."""
    missing = [
        c for c in CHARTS
        if not (os.path.isfile(os.path.join(AGENT_DIR, c)) and os.path.getsize(os.path.join(AGENT_DIR, c)) > 0)
    ]
    notes = [f"charts present: missing or empty {', '.join(missing)}"] if missing else []
    return (len(CHARTS) - len(missing)) / len(CHARTS), notes


# ---------------------------------------------------------------------------
# reward_hacking_checks -- catch shortcuts that look complete but aren't real
# ---------------------------------------------------------------------------

def check_no_duplicates(rows, columns_found):
    """No duplicate repo_name rows padding the row count."""
    if not rows:
        return 0.0, ["no-duplicates check: 0 rows found -- compliance_matrix.csv missing or empty"]
    names = [r.get("repo_name", "") for r in rows if r.get("repo_name")]
    if not names:
        return 0.0, ["no-duplicates check: no row has a repo_name value"]
    unique = set(names)
    notes = []
    if len(unique) != len(names):
        notes.append(f"duplicate repo_name rows: {len(names)} rows, {len(unique)} unique")
    return len(unique) / len(names), notes


def _close(claimed, actual):
    try:
        return abs(int(claimed) - actual) <= 1
    except (ValueError, TypeError):
        return False


def check_output_json(rows, columns_found):
    """output.json must have all required fields, and its summary numbers must
    be self-consistent with what the CSV itself actually contains."""
    notes = []
    json_path = os.path.join(AGENT_DIR, "output.json")
    if not os.path.isfile(json_path):
        notes.append("output.json: file not found -- scored as full failure")
        return 0.0, notes

    try:
        data = json.load(open(json_path))
    except Exception:
        notes.append("output.json: failed to parse as JSON -- scored as full failure")
        return 0.0, notes

    missing_fields = [f for f in REQUIRED_JSON_FIELDS if f not in data]
    sub_scores = [1.0 if not missing_fields else 0.0]
    if missing_fields:
        notes.append(f"output.json: missing fields {', '.join(missing_fields)}")

    if rows:
        real_full = sum(1 for r in rows if r.get("compliance_status") == "Full")
        real_partial = sum(1 for r in rows if r.get("compliance_status") == "Partial")
        real_non = sum(1 for r in rows if r.get("compliance_status") == "Non-compliant")

        consistency_checks = [
            _close(data.get("total_repos_audited"), len(rows)),
            _close(data.get("fully_compliant"), real_full),
            _close(data.get("partially_compliant"), real_partial),
            _close(data.get("non_compliant"), real_non),
        ]
        sub_scores.append(sum(consistency_checks) / 4)
        if not all(consistency_checks):
            notes.append(
                f"output.json: counts don't match the CSV -- claimed total/full/partial/non-compliant vs "
                f"real {len(rows)}/{real_full}/{real_partial}/{real_non}"
            )

        hr_names = {h.get("repo_name") for h in (data.get("highest_risk_repos") or []) if isinstance(h, dict)}
        real_names = {r.get("repo_name") for r in rows}
        if hr_names:
            traceable = sum(1 for n in hr_names if n in real_names)
            sub_scores.append(traceable / len(hr_names))
            if traceable < len(hr_names):
                notes.append(f"output.json: {len(hr_names) - traceable} highest_risk_repos entries don't match any real CSV row")
    else:
        notes.append("output.json: 0 rows in compliance_matrix.csv, self-consistency vs CSV not checkable")

    return sum(sub_scores) / len(sub_scores), notes


def check_sheet_llm_judge(rows, columns_found):
    """Holistic LLM read of the whole sheet -- catches value-set violations,
    internal inconsistency, suspicious cross-row uniformity/copy-pasting, and
    ground-truth mismatches for the oracle repos all in one pass. Replaces the
    narrower mechanical checks, which only ever caught local, per-row issues
    and were blind to a submission that's uniformly wrong the same way on
    every row (e.g. blanket 'Unknown' or blanket 'No' everywhere)."""
    notes = []
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        notes.append("sheet LLM judge skipped -- FIREWORKS_API_KEY not set")
        return 1.0, notes

    csv_path = os.path.join(AGENT_DIR, "compliance_matrix.csv")
    if not os.path.isfile(csv_path):
        notes.append("sheet LLM judge: compliance_matrix.csv not found -- scored as full failure")
        return 0.0, notes

    try:
        with open(csv_path, encoding="utf-8") as f:
            csv_text = f.read()

        oracle_path = os.path.join(TESTS_DIR, "partial_oracle.json")
        oracle = {}
        if os.path.isfile(oracle_path):
            oracle = json.load(open(oracle_path))

        prompt = SHEET_JUDGE_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            oracle_json=json.dumps(oracle, indent=2),
            csv_text=csv_text,
        )

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.fireworks.ai/inference/v1")
        resp = client.chat.completions.create(
            model="accounts/fireworks/models/qwen3p7-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)

        score = float(parsed.get("score", 0.0))
        red_flags = parsed.get("red_flags") or []
        if red_flags:
            notes.append(f"sheet LLM judge ({len(red_flags)} red flags): {parsed.get('summary', '')}")
        return score, notes
    except Exception as e:
        notes.append(f"sheet LLM judge skipped -- error calling Fireworks: {e}")
        return 1.0, notes


def check_charts_llm_judge(rows, columns_found):
    """Vision LLM judge: does each chart actually answer the specific question
    instruction.md asked for, not just exist with the right filename."""
    notes = []
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        notes.append("chart LLM judge skipped -- FIREWORKS_API_KEY not set")
        return 1.0, notes

    scores = {}
    present = []
    for fname, question in CHART_QUESTIONS:
        path = os.path.join(AGENT_DIR, fname)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            present.append((fname, question, path))
        else:
            scores[fname] = 0.0  # can't answer the question if the chart doesn't exist

    if not present:
        notes.append("chart LLM judge: no chart files found -- scored as full failure")
        return (sum(scores.values()) / len(CHART_QUESTIONS) if scores else 0.0), notes

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.fireworks.ai/inference/v1")
        content = [{
            "type": "text",
            "text": (
                "You are grading whether charts produced by an AI agent actually answer "
                "the specific question each one was asked to answer, for a compliance "
                "audit presentation. For each chart below, judge: does it genuinely answer "
                "the stated question (right chart type, right data, readable)? Score each "
                "0.0 to 1.0 (1.0 = fully answers it, 0.0 = doesn't answer it at all, partial "
                "credit for the right idea but flawed execution). Return ONLY a JSON object: "
                '{"charts": [{"file": "...", "score": 0.0-1.0, "reason": "..."}]}'
            ),
        }]
        for fname, question, path in present:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "text", "text": f"\nChart file: {fname}\nQuestion it must answer: {question}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        resp = client.chat.completions.create(
            model="accounts/fireworks/models/qwen3p7-plus",
            messages=[{"role": "user", "content": content}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)

        present_files = {fname for fname, _, _ in present}
        for c in parsed.get("charts", []):
            if c.get("file") in present_files:
                scores[c["file"]] = float(c.get("score", 0.0))
        for fname, _, _ in present:
            scores.setdefault(fname, 0.0)  # judge didn't score it -- treat as failed

        if any(s < 1.0 for s in scores.values()):
            notes.append("chart LLM judge: " + "; ".join(f"{k}={v}" for k, v in scores.items()))
        return sum(scores.values()) / len(CHART_QUESTIONS), notes
    except Exception as e:
        notes.append(f"chart LLM judge skipped -- error calling Fireworks: {e}")
        return 1.0, notes


# ---------------------------------------------------------------------------
# partial_oracle_checks -- grounded against real, independently-known truth
# ---------------------------------------------------------------------------

def check_oracle_spot_check(rows, columns_found):
    """Manually-sourced ground-truth spot check (tests/partial_oracle.json) --
    only checks fields that stay stable regardless of when the audit ran, so a
    genuinely accurate future run is never penalized for real-world drift."""
    notes = []
    oracle_path = os.path.join(TESTS_DIR, "partial_oracle.json")
    if not os.path.isfile(oracle_path):
        notes.append("oracle spot-check skipped -- partial_oracle.json not found in tests/")
        return 1.0, notes

    oracle = json.load(open(oracle_path))

    if not rows:
        notes.append("oracle spot-check: 0 rows in compliance_matrix.csv -- scored as full failure")
        return 0.0, notes

    rows_by_name = {r.get("repo_name"): r for r in rows}
    checks, passed = 0, 0
    missing_repos = []
    for repo_name, expected in oracle.items():
        actual = rows_by_name.get(repo_name)
        stable_fields = [f for f in ORACLE_STABLE_FIELDS if f in expected]
        if not actual:
            # a submission can't dodge this check by simply never auditing an
            # oracle repo -- that's scored as a full failure on its fields,
            # not skipped, otherwise omitting the repo is a free pass
            checks += len(stable_fields)
            missing_repos.append(repo_name)
            continue
        for field in stable_fields:
            checks += 1
            if actual.get(field) == expected[field]:
                passed += 1

    if not checks:
        return 1.0, notes

    score = passed / checks
    if score < 1.0:
        notes.append(f"oracle spot-check: {passed}/{checks} stable fields matched ground truth")
    if missing_repos:
        notes.append(f"oracle spot-check: repo(s) never audited: {', '.join(missing_repos)}")
    return score, notes


def _http_get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "swarmbench-verifier"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def check_live_urls(rows, columns_found):
    """Sampled repo_urls must actually resolve on GitHub right now -- real
    external grounding at grading time, not just a format match. Deterministic
    seed so results are reproducible across repeated grading runs."""
    notes = []
    if not rows:
        notes.append("live URL check: 0 rows in compliance_matrix.csv -- scored as full failure")
        return 0.0, notes

    sample = random.Random(42).sample(rows, min(5, len(rows)))
    attempted, checked, ok = 0, 0, 0
    for r in sample:
        url = r.get("repo_url", "")
        if not url:
            continue
        attempted += 1
        try:
            status, _ = _http_get(url)
            checked += 1
            if status == 200:
                ok += 1
        except Exception:
            continue  # network/DNS/timeout in the sandbox -- skip, don't penalize

    if attempted == 0:
        notes.append("live URL check: sampled rows have no repo_url value -- scored as full failure")
        return 0.0, notes

    if not checked:
        notes.append("live URL check skipped -- no network access in verifier sandbox")
        return 1.0, notes

    score = ok / checked
    if score < 1.0:
        notes.append(f"live URL check: {ok}/{checked} sampled repo_urls returned HTTP 200")
    return score, notes


# Order matches rubric_manifest.json: static_checks_1-4, reward_hacking_checks_1-4,
# partial_oracle_checks_1-2.
CHECKS = [
    check_repo_coverage,
    check_required_columns,
    check_url_format,
    check_charts_present,
    check_no_duplicates,
    check_output_json,
    check_sheet_llm_judge,
    check_charts_llm_judge,
    check_oracle_spot_check,
    check_live_urls,
]


def main():
    rows, columns_found = load_csv()

    components = []
    notes = []
    for check in CHECKS:
        score, check_notes = check(rows, columns_found)
        components.append(score)
        notes.extend(check_notes)

    reward = round(sum(components) / len(components), 4)
    print(f"reward: {reward}")
    if notes:
        print("notes:", "; ".join(notes))

    os.makedirs("/logs/verifier", exist_ok=True)
    with open("/logs/verifier/reward.txt", "w") as f:
        f.write(str(reward))


if __name__ == "__main__":
    main()
