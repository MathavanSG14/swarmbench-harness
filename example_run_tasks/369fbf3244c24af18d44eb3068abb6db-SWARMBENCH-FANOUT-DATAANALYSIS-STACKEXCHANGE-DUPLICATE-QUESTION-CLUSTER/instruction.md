# Identify duplicate-question clusters in a Stack Exchange corpus

You are a community-moderation data scientist embedded with the trust-and-safety team of
a Q&A platform similar to Stack Exchange / Stack Overflow. Every day, users post fresh
questions, and many of them re-ask things the community has already answered. Your job
here is to take a static snapshot of question posts pulled from twelve different Stack
Exchange sub-forums and group the questions so that **every group is exactly one
underlying question**: rewordings of the same problem, follow-ups that have the same
canonical answer, and translations into different jargon all collapse into a single
cluster; questions that merely share a topic but ask for different things stay apart.
This is the input to the platform's duplicate-question moderation queue.

## What the corpus looks like

The snapshot is staged under `/input_artifacts/` and is split into per-community part
files. The directory contains:

- `index.json` - a manifest listing `total_records`, `n_parts`, and the array `parts`
  of part-file names.
- `part_01.json` through `part_12.json` - one part per Stack Exchange sub-forum
  (`gaming`, `stats`, `programmers`, `physics`, `mathematica`, `unix`, `webmasters`,
  `gis`, `tex`, `wordpress`, `android`, `english` - the order is fixed by `index.json`).

The **full corpus you must cluster is the UNION of every record across every part
file**. There are no records hidden elsewhere; everything you need is in
`/input_artifacts/`. Your working directory is `/workspace/`. The environment has no
network access - you do not need it, since the questions are local files.

Each part file has the shape:
```
{
  "note": "...",
  "part": "part_NN.json",
  "count": <int>,
  "records": [ {record}, {record}, ... ]
}
```

A `record` has four string fields and nothing else:
- `id` - a unique question id of the form `se_<forum>_<digits>`, e.g.
  `se_gaming_180046`. Copy it back exactly; do not mutate it.
- `tag_forum` - the Stack Exchange sub-forum the question was posted on
  (`gaming`, `stats`, etc., matching the part's community).
- `title` - the question's verbatim title.
- `body` - the question's verbatim body text, truncated at roughly 500 characters
  where the original is long.

The text is real, unedited Stack Exchange prose: it contains code snippets,
markdown leftovers, broken sentences, varying levels of grammar, and occasional
embedded URLs. Read it as-is.

## The decision you are making per pair of questions

For any two questions, ask yourself: *would a moderator legitimately close one of
them as a duplicate of the other?* That is the bar.

- Two questions are **duplicates** when answering one of them would fully answer the
  other - even if the wording, code snippets, version numbers, or screenshots they
  attach are very different.
- Two questions are **distinct** when they need different answers - even if they share
  vocabulary, the same software, the same error message, or the same general topic.
  "How do I sort an array?" and "How do I sort an array in reverse?" are distinct.
  "Why does my plugin crash on activation?" and "My plugin crashes the moment I
  activate it - help" are duplicates.
- Duplicate-question groups never cross sub-forums in this dataset. A
  `tag_forum = "gaming"` question is never grouped with a `tag_forum = "stats"`
  question.
- A question that has no duplicate-mate in the snapshot is in a group of size one.

## Output you write

Write a single JSON object to `/logs/agent/output.json` with exactly two keys:

- `analyst_line` - a non-empty string. One sentence summarising what you produced
  (for example, mentioning total questions clustered and rough cluster count). The
  exact wording is up to you; brevity is fine.
- `assignments` - an array with **one entry per question id in the corpus**. Each
  entry is an object with two keys:
  - `id` - the question id, copied verbatim from the part files.
  - `group` - a string label of your choosing. Two questions get the SAME `group`
    string if and only if you judge them duplicates of each other; otherwise their
    `group` strings differ. Label values are arbitrary - only the partition they
    induce matters.

Cover every id exactly once. Do not omit ids, do not invent ids that are not in any
part file, and do not assign the same id twice. A question you cannot find a
duplicate mate for is a singleton cluster - give it a label that no other id shares.

## How the result is scored

Your grouping is compared against a frozen reference partition of the same corpus
that was hand-curated by the Q&A platform's moderation team. The scorer is fully
deterministic: it expands both partitions into the set of unordered question pairs
"together in the same group", then computes pairwise F1 (the harmonic mean of
precision - the share of your together-pairs that are reference together-pairs - and
recall - the share of reference together-pairs that you put together). The reward is
that F1 in `[0, 1]`.

This shape rewards two things and only two things: (a) keeping real duplicate
mates in the same group (recall), and (b) keeping non-duplicates apart (precision).
Trivial strategies fail visibly: dumping every question into a single group gives
maximum recall but near-zero precision, and putting every question in its own
singleton group gives 0 recall. The score is sensitive to even a few mis-grouped
pairs, so consider each candidate duplicate carefully.

Time budget: you have several hours of wall-clock. Spend the bulk of it reading the
question bodies, not just the titles - many duplicate pairs only become visible from
the body text, and many surface-similar titles turn out to ask very different things.
