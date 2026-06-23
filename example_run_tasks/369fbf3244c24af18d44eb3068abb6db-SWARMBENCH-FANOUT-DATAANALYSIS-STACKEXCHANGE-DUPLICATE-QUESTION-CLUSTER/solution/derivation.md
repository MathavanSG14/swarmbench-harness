# Corpus Derivation

Step-by-step procedure for building `/input_artifacts/part_*.json` and
`/tests/oracle.json` from the raw CQADupStack files in `raw_sources/`. The full
implementation is `build_corpus.py`; this document is the human-readable spec.

1. **Sub-forum list.** Twelve Stack Exchange sub-forums are used (one shard each):
   `gaming, stats, programmers, physics, mathematica, unix, webmasters, gis, tex,
   wordpress, android, english`. These are the sub-forums for which CQADupStack
   provides published duplicate-question qrels.

2. **For each sub-forum f:**
   - Load `raw_sources/cqa_<f>_corpus.jsonl` into a dict
     `corpus[corpus-id] -> {_id, title, text}`.
   - Load `raw_sources/cqa_<f>_qrels.jsonl` into a list of
     `{query-id, corpus-id, score}` rows.
   - Group qrels rows by `query-id` -> set of `corpus-id` values.

3. **Pick duplicate clusters.** Sort query-ids deterministically, then shuffle with a
   seeded RNG (seed = 20260605). Walk the shuffled queries and keep the first 14
   queries whose corpus-id set has size in `[2, 6]` and whose corpus-ids all have body
   text. Each kept query becomes one cluster (every corpus-id in its set shares the
   same cluster_id `"<f>__<query-id>"`).

4. **Pick singleton noise.** From corpus-ids not in any chosen multi-cluster, sample
   18 with the same RNG. Each becomes a singleton cluster with id
   `"<f>__singleton_<f>_<corpus-id>"`.

5. **Emit records.** For each picked corpus-id, emit:
   ```json
   {
     "id":        "se_<f>_<corpus-id>",
     "tag_forum": "<f>",
     "title":     "<corpus[cid].title verbatim, whitespace-collapsed>",
     "body":      "<corpus[cid].text verbatim, whitespace-collapsed, truncated to 500 chars>"
   }
   ```
   Also retain `_cluster_id` for the oracle (stripped from the agent-facing shard).

6. **Shuffle and shard.** Per-sub-forum records are shuffled (seeded) and emitted as
   `part_NN.json` in fixed sub-forum order (one part per sub-forum).

7. **Oracle.** Concatenate every record's `(id, _cluster_id)` pair into
   `tests/oracle.json`. A copy is mirrored to `solution/oracle.json` for the cp-only
   oracle solver inside the container.

8. **Stats observed:**
   - 664 records total across 12 shards (range 48-62 records / shard).
   - 168 multi-record clusters (sizes 2-6) plus 216 singletons.
   - 474 gold duplicate pairs across the corpus.
   - ~93K tokens of staged input (~374 KB on disk).

Reproducibility: run `python3 build_corpus.py` from the `solution/` directory; with
the same raw inputs and the seed above, the resulting parts and oracle are
bit-identical.
