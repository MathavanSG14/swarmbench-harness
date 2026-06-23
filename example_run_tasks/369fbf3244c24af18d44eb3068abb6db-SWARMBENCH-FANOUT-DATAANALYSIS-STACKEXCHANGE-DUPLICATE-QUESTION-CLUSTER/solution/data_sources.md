# Data Sources

This task is built entirely from public, real-world Stack Exchange question data. No
text in the staged corpus has been re-worded, paraphrased, or
otherwise generated. Every title and body in `/input_artifacts/part_*.json` is the
verbatim text from the public dataset (collapsed whitespace only; truncated at ~500
characters for body length budget).

## Primary source: CQADupStack on HuggingFace (mteb/cqadupstack-*)

The corpus is sliced from the CQADupStack benchmark, packaged on HuggingFace by the
MTEB project, under apache-2.0:

- Landing page: https://huggingface.co/datasets/mteb/cqadupstack
- Per-sub-forum: https://huggingface.co/datasets/mteb/cqadupstack-<forum>
  with `<forum>` in:
  - gaming
  - stats
  - programmers
  - physics
  - mathematica
  - unix
  - webmasters
  - gis
  - tex
  - wordpress
  - android
  - english

Two files per sub-forum were fetched (raw copies preserved under
`solution/raw_sources/`):

- `corpus.jsonl` (https://huggingface.co/datasets/mteb/cqadupstack-<forum>/resolve/main/corpus.jsonl)
  - rows of `{"_id": <stackexchange question id>, "title": ..., "text": ...}`
- `qrels/test.jsonl` (https://huggingface.co/datasets/mteb/cqadupstack-<forum>/resolve/main/qrels/test.jsonl)
  - rows of `{"query-id": ..., "corpus-id": ..., "score": "1"}` flagging the corpus
    question as a known duplicate of the query.

## Upstream source: Stack Exchange Data Dump

CQADupStack itself is derived from the public Stack Exchange Data Dump, released
under CC BY-SA 4.0 by Stack Exchange Inc.:

- Stack Exchange Data Dump: https://archive.org/details/stackexchange
- CQADupStack original: http://nlp.cis.unimelb.edu.au/resources/cqadupstack/

The "marked-as-duplicate" links between questions are real moderator decisions made by
the Stack Exchange community, not synthetic labels.

## Gold derivation

The cluster_id for each record in `/tests/oracle.json` is derived directly from the
qrels file: every corpus question that the qrels link to the same query-id shares
one cluster_id (formatted `"<forum>__<query-id>"`). Corpus questions not present in
any 2+ qrels group are singleton clusters
(`"<forum>__singleton_<forum>_<corpus-id>"`). The mapping is implemented in
`build_corpus.py` and is fully reproducible with the same seed (20260605).

## License compliance

- CQADupStack on HuggingFace: apache-2.0 (research benchmark redistribution allowed).
- Stack Exchange original content: CC BY-SA 4.0 (attribution + share-alike; this
  task's downstream artifacts retain the same license).
- We redistribute only question titles and bodies (no user PII beyond the public
  question text) and the duplicate-cluster ids.
