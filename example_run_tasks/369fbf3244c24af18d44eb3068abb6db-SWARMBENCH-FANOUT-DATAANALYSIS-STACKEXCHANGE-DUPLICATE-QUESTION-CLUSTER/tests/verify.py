#!/usr/bin/env python3
"""
Deterministic verifier for STACKEXCHANGE-DUPLICATE-QUESTION-CLUSTER.

The agent partitions ~660 real Stack Exchange questions into duplicate-question clusters
(same underlying question, regardless of wording). Scoring is deterministic PAIRWISE-F1
of the agent's grouping against the published CQADupStack duplicate-pair gold (the
query-id partition) - no model is called here.

reward = pairwise-F1:
  - over all pairs of questions in the corpus, a pair is "predicted together" iff the
    agent assigned both the same group label, and "gold together" iff they share a
    cluster_id in the gold partition.
  - precision = true-together / predicted-together
    recall    = true-together / gold-together
    F1        = harmonic mean.
This is spray-proof: putting every question into one giant group maximises recall but
tanks precision (most pairs are NOT duplicates); putting every question in its own
group scores 0 recall. Questions the agent never assigns are treated as unique
singletons (their gold duplicate-mates therefore go unrecovered -> recall penalty).
Reward is fractional in [0, 1].

verifier_type is "executable" in task.toml: this scorer is FULLY DETERMINISTIC
(pairwise-F1 set math over question ids, no LLM call, no network egress). Per the
QD-09.5 contract a fully-deterministic verifier MUST be declared executable, not
llm-judge (whose fail-closed contract requires every non-zero reward to come from a
parsed model verdict, which these rewards do not). solve.sh is cp-only because the
duplicate-cluster reference is the frozen CQADupStack qrels gold (closed-corpus
oracle, copied not re-derived). Editing this docstring does not change the scoring,
so the recorded reward files remain valid.
"""
import argparse
import json
import sys
from collections import Counter
from math import comb
from pathlib import Path


def verify(agent, gold_doc):
    gold = {g["id"]: str(g["cluster_id"]) for g in gold_doc.get("gold", []) if isinstance(g, dict) and "id" in g}
    ids = list(gold)
    n = len(ids)

    ok_obj = isinstance(agent, dict)
    assignments = agent.get("assignments") if ok_obj else None
    ok_list = isinstance(assignments, list) and len(assignments) > 0
    # instruction.md requires the output object to carry BOTH keys: `analyst_line`
    # (a non-empty string summary) and `assignments` (the per-question group labels).
    # The validity gate mirrors that schema; "one sentence" is subjective and is NOT
    # enforced beyond non-empty. analyst_line is not itself scored - the reward stays
    # pairwise-F1 over the question grouping, exactly as instruction.md states.
    ok_line = ok_obj and isinstance(agent.get("analyst_line"), str) and agent.get("analyst_line").strip() != ""

    pred = {}
    dup_id = off_corpus = malformed = 0
    seen = set()
    if ok_list:
        for a in assignments:
            if not isinstance(a, dict):
                malformed += 1
                continue
            rid = a.get("id")
            grp = a.get("group")
            if not isinstance(rid, str) or grp is None or str(grp).strip() == "":
                malformed += 1
                continue
            if rid in seen:
                dup_id += 1
                continue
            seen.add(rid)
            if rid not in gold:
                off_corpus += 1
                continue
            pred[rid] = str(grp)

    # Questions the agent never assigned -> unique singleton groups (they lose their
    # true duplicate mates -> recall drops).
    missing = 0
    for i, rid in enumerate(ids):
        if rid not in pred:
            pred[rid] = f"__missing_{i}__"
            missing += 1

    # Pairwise-F1 via contingency counts.
    cont = Counter((gold[rid], pred[rid]) for rid in ids)
    gold_counts = Counter(gold[rid] for rid in ids)
    pred_counts = Counter(pred[rid] for rid in ids)
    true_together = sum(comb(c, 2) for c in cont.values())
    gold_pairs = sum(comb(c, 2) for c in gold_counts.values())
    pred_pairs = sum(comb(c, 2) for c in pred_counts.values())
    precision = true_together / pred_pairs if pred_pairs else 0.0
    recall = true_together / gold_pairs if gold_pairs else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    if not (ok_obj and ok_list and ok_line):
        f1 = 0.0

    details = {
        "valid_output": ok_obj and ok_list and ok_line,
        "valid_analyst_line": ok_line,
        "questions_total": n,
        "questions_assigned": n - missing,
        "questions_missing": missing,
        "duplicate_ids": dup_id,
        "offcorpus_ids": off_corpus,
        "malformed_entries": malformed,
        "gold_duplicate_pairs": gold_pairs,
        "predicted_together_pairs": pred_pairs,
        "true_together_pairs": true_together,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "pairwise_f1": round(f1, 4),
    }
    return f1, details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-output", default="/logs/agent/output.json")
    ap.add_argument("--oracle", default="/tests/oracle.json")
    ap.add_argument("--reward-out", default="/logs/verifier/reward.txt")
    args = ap.parse_args()
    rp = Path(args.reward_out)
    rp.parent.mkdir(parents=True, exist_ok=True)
    try:
        Path("/logs/agent").mkdir(parents=True, exist_ok=True)
        jp = Path("/logs/agent/judge_justification.txt")
    except OSError:
        jp = rp.parent / "judge_justification.txt"

    def write_reward(score):
        rp.write_text(f"{round(float(score), 4)}\n")
        try:
            (rp.parent / "reward.json").write_text(json.dumps({"reward": round(float(score), 4)}))
        except Exception:
            pass

    try:
        gold_doc = json.loads(Path(args.oracle).read_text())
    except Exception as e:
        write_reward(0.0); jp.write_text(f"Score: 0.0\n\nGold load error: {e}"); sys.exit(0)
    try:
        agent = json.loads(Path(args.agent_output).read_text())
    except FileNotFoundError:
        write_reward(0.0); jp.write_text("Score: 0.0\n\noutput.json missing"); sys.exit(0)
    except json.JSONDecodeError as e:
        write_reward(0.0); jp.write_text(f"Score: 0.0\n\nInvalid JSON: {e}"); sys.exit(0)

    score, d = verify(agent, gold_doc)
    write_reward(score)
    lines = [
        f"Score: {round(score,4)} (pairwise-F1; precision {d['precision']} recall {d['recall']})",
        json.dumps(d, indent=2),
    ]
    jp.write_text("\n".join(lines))
    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
