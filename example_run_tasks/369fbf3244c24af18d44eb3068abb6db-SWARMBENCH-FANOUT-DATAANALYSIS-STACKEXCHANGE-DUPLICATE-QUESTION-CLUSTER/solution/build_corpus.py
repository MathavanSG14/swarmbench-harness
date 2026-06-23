#!/usr/bin/env python3
"""
Build the STACKEXCHANGE-DUPLICATE-QUESTION-CLUSTER corpus from real Stack Exchange
data (CQADupStack on HuggingFace, mteb/cqadupstack-* subsets).

For each of 12 sub-forums (gaming, stats, programmers, physics, mathematica, unix,
webmasters, gis, tex, wordpress, android, english), we:
  1. Read the published qrels file: each row links a query-id to a corpus-id flagged
     as a duplicate question pair. The corpus-id is the Stack Exchange question id.
  2. Group corpus-ids by query-id. A query that points to N>=2 corpus questions is a
     real duplicate cluster of size N (all N questions are flagged as duplicates of the
     same underlying question). Smaller queries (N=1) are skipped.
  3. Pull a slice of those multi-record clusters per sub-forum, and add random
     non-duplicate corpus questions as singleton "noise" so a sub-forum shard has both
     true duplicates and many distinct questions.
  4. Look up each corpus-id in the corpus.jsonl file (verbatim title + body text) and
     emit the agent-facing record. No text is changed; we truncate body at ~500 chars
     for size budget. The cluster gold label is the query-id (a real, published id).

Output:
  - /input_artifacts/index.json + part_01..part_12.json (agent-facing, NO cluster_id)
  - /tests/oracle.json (gold cluster_id per record)
  - records_full.json (debug copy with cluster_id, for derivation auditing)

The raw inputs are the public files at:
  https://huggingface.co/datasets/mteb/cqadupstack-<forum>/resolve/main/corpus.jsonl
  https://huggingface.co/datasets/mteb/cqadupstack-<forum>/resolve/main/qrels/test.jsonl
released under apache-2.0. The underlying Stack Exchange Data Dump is CC BY-SA 4.0.
"""
import json
import random
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw_sources"
OUT_INPUT = HERE.parent / "environment" / "input_artifacts"
OUT_TESTS = HERE.parent / "tests"
OUT_INPUT.mkdir(parents=True, exist_ok=True)
OUT_TESTS.mkdir(parents=True, exist_ok=True)

# 12 sub-forums -> 12 shards (one shard per sub-forum keeps same-forum questions together,
# which is the natural duplicate-search wedge: a community moderator triaging duplicates
# only ever compares questions within one forum, never across).
SUBFORUMS = [
    "gaming", "stats", "programmers", "physics", "mathematica", "unix",
    "webmasters", "gis", "tex", "wordpress", "android", "english",
]

# Tuning: per sub-forum, take this many true-duplicate clusters (size >=2 corpus) and
# this many random singleton corpus questions for noise. Total per shard ~55-70.
PER_FORUM_CLUSTERS = 14         # ~14 clusters * avg size ~3 = ~42 dup questions
PER_FORUM_SINGLETONS = 18        # +18 singletons -> ~60 records / shard
MAX_BODY_CHARS = 500            # truncate body
RNG_SEED = 20260605


def clean(text: str) -> str:
    if not text:
        return ""
    # Collapse repeated whitespace but keep the verbatim characters (no rewording).
    return re.sub(r"\s+", " ", text).strip()


def load_jsonl(path: Path):
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def build_for_forum(forum: str, rng: random.Random):
    """Return (records_with_gold, total_corpus_size) for one sub-forum.

    records_with_gold: list of dicts with id, tag_forum, title, body, cluster_id
    """
    corpus_path = RAW / f"cqa_{forum}_corpus.jsonl"
    qrels_path = RAW / f"cqa_{forum}_qrels.jsonl"

    corpus = {row["_id"]: row for row in load_jsonl(corpus_path)}
    qrels = load_jsonl(qrels_path)

    by_query = defaultdict(list)
    for r in qrels:
        by_query[r["query-id"]].append(r["corpus-id"])

    # Deterministic ordering before random sampling.
    multi_queries = sorted([q for q, cs in by_query.items() if len(set(cs)) >= 2])
    rng.shuffle(multi_queries)

    selected_clusters = []          # list of (cluster_id, [corpus_id, ...])
    picked_corpus_ids = set()
    for q in multi_queries:
        cids = sorted(set(by_query[q]))
        # Keep clusters of size 2..6 to avoid mega-clusters dominating.
        if not (2 <= len(cids) <= 6):
            continue
        # Make sure each cid actually has body text in corpus.
        cids = [c for c in cids if c in corpus and corpus[c].get("text")]
        if len(cids) < 2:
            continue
        if any(c in picked_corpus_ids for c in cids):
            continue
        selected_clusters.append((q, cids))
        picked_corpus_ids.update(cids)
        if len(selected_clusters) >= PER_FORUM_CLUSTERS:
            break

    # Singletons: random corpus ids not in any picked cluster, each becomes own cluster.
    other_ids = sorted(set(corpus.keys()) - picked_corpus_ids)
    rng.shuffle(other_ids)
    singleton_ids = other_ids[:PER_FORUM_SINGLETONS]
    for c in singleton_ids:
        # singleton cluster_id = synthetic id derived from forum + corpus id, distinct
        # from all multi-cluster query-ids (which are numeric strings).
        selected_clusters.append((f"singleton_{forum}_{c}", [c]))

    # Emit records in interleaved order so each shard sees a mix of dup vs singletons.
    all_pairs = []
    for cluster_id, cids in selected_clusters:
        for cid in cids:
            row = corpus[cid]
            title = clean(row.get("title", ""))
            body = clean(row.get("text", ""))[:MAX_BODY_CHARS]
            # Agent-facing record id: prefix with forum so ids are globally unique
            # across shards (each forum has its own corpus id space and they could
            # collide otherwise).
            rec_id = f"se_{forum}_{cid}"
            all_pairs.append({
                "id": rec_id,
                "tag_forum": forum,
                "title": title,
                "body": body,
                "_cluster_id": f"{forum}__{cluster_id}",
            })
    rng.shuffle(all_pairs)
    return all_pairs


def main():
    rng = random.Random(RNG_SEED)
    all_records = []
    per_forum_records = {}
    for forum in SUBFORUMS:
        recs = build_for_forum(forum, rng)
        per_forum_records[forum] = recs
        all_records.extend(recs)
        print(f"forum={forum}: {len(recs)} records, "
              f"{sum(1 for r in recs if not r['_cluster_id'].startswith(f'{forum}__singleton_'))} in dup clusters")

    total = len(all_records)
    print(f"TOTAL: {total} records across {len(SUBFORUMS)} sub-forums")

    # Shard one part per sub-forum (12 shards). Strip cluster_id for agent-facing.
    parts = []
    for idx, forum in enumerate(SUBFORUMS, start=1):
        part_name = f"part_{idx:02d}.json"
        recs = per_forum_records[forum]
        agent_recs = [{"id": r["id"], "tag_forum": r["tag_forum"], "title": r["title"], "body": r["body"]} for r in recs]
        part_obj = {
            "note": f"One shard of the STACKEXCHANGE-DUPLICATE-QUESTION-CLUSTER corpus: real Stack Exchange questions from the '{forum}' community (no duplicate-cluster labels). Group questions in THIS shard that ask the same underlying thing, per instruction.md. The full set to cluster is the UNION of all part_*.json files.",
            "part": part_name,
            "count": len(agent_recs),
            "records": agent_recs,
        }
        (OUT_INPUT / part_name).write_text(json.dumps(part_obj, indent=2))
        parts.append(part_name)
        print(f"  -> wrote {part_name} ({len(agent_recs)} records)")

    index_obj = {
        "note": "Index of corpus shards. The full set of Stack Exchange questions to cluster into duplicate-question groups is the UNION of all part_*.json files.",
        "total_records": total,
        "n_parts": len(parts),
        "parts": parts,
    }
    (OUT_INPUT / "index.json").write_text(json.dumps(index_obj, indent=2))

    # Oracle: gold cluster_id per record, plus dataset metadata. The "cluster_id" naming
    # mirrors the pairwise-F1 verifier shape used by the sibling PRODUCTMATCH task.
    gold_entries = [{"id": r["id"], "cluster_id": r["_cluster_id"]} for r in all_records]
    oracle = {
        "note": "GOLD duplicate-question partition for STACKEXCHANGE-DUPLICATE-QUESTION-CLUSTER, derived from the published CQADupStack qrels for 12 Stack Exchange sub-forums. Read by tests/verify.py (pairwise-F1 over question pairs).",
        "count": len(gold_entries),
        "gold": gold_entries,
    }
    (OUT_TESTS / "oracle.json").write_text(json.dumps(oracle, indent=2))
    # Mirror into solution/ for the oracle solver inside the container.
    (HERE / "oracle.json").write_text(json.dumps(oracle, indent=2))

    # Debug audit file with cluster_id retained.
    (HERE / "records_full.json").write_text(json.dumps(all_records, indent=2))

    # Sanity: stats on cluster sizes.
    from collections import Counter
    sizes = Counter()
    for r in all_records:
        sizes[r["_cluster_id"]] += 1
    size_dist = Counter(sizes.values())
    print(f"cluster size dist: {sorted(size_dist.items())}")
    print(f"total bytes of input_artifacts/: ~{sum((OUT_INPUT/p).stat().st_size for p in parts)+ (OUT_INPUT/'index.json').stat().st_size}")


if __name__ == "__main__":
    main()
