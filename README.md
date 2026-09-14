# Review De-duplication & Trust Clustering — Gangnam Beauty Guide demo

**Live demo:** https://shrony.github.io/gbg-review-dedup/

Built in a 45-minute timed assessment for We The Flywheel. The product card
says the hard problem is *"review syndication at scale across many Korean
sources, with translation + de-duplication + clinic normalisation"* and that
*"trust signals are the moat"* — so this is a working miniature of exactly
that slice: multi-source review ingestion → duplicate detection → trust
labeling, with duplicates **flagged, never deleted** (the duplication pattern
is itself a trust signal).

## Architecture

```
fixtures/reviews.json          20 fictional reviews, 4 source shapes (cafe /
                               blog / clinic-site / EN forum), KR + EN
        │
        ▼
pipeline.py   STAGE 1 — cheap, runs on everything (stdlib only)
        │     • normalize: prices folded (35만원 ≡ ₩350,000), punct stripped
        │     • char-bigram Jaccard over all pairs (language-agnostic:
        │       Korean is agglutinative; no tokenizer/konlpy needed)
        │     • blocking: text sim ∪ metadata (procedure+price+date window)
        │       ∪ fuzzy author-handle match
        │     • serial-promoter detection (one handle, 3+ clinics)
        ▼
judge.py      STAGE 2 — expensive, runs on almost nothing
        │     • only the uncertain band (0.25–0.85) + metadata-nominated
        │       cross-language pairs reach the LLM: 4 of 190 pairs here
        │     • structured verdict: relation / confidence / rationale
        ▼
docs/         static demo page (GitHub Pages, vanilla JS)
              • threshold slider re-clusters live (union-find client-side)
              • judge toggle shows stage 2 rescuing false positives and
                catching the KR/EN duplicate that n-grams score ~0
```

## The planted cases (the demo's plot)

| Pair | What it is | Who catches it |
|---|---|---|
| r01–r02 | exact cross-post, handle variant of same author | stage 1 (jac 1.0) + author match → benign |
| r03–r04 | reworded seeding pair, different identities | stage 1 merges (0.767); judge confirms `paraphrase-seeding` |
| r05–r06 | genuinely similar independent reviews (0.284) | judge vetoes the merge at low thresholds |
| r08–r17 | unrelated EN reviews at 0.30 (bigram baseline on English) | judge: `distinct` |
| r07–r08 | same review in Korean and English, different accounts | n-grams ~0 — metadata blocking nominates, judge confirms `cross-language-duplicate` |
| r09–r11 | one handle glowing about 3 clinics in 3 weeks | promoter-pattern badge |

## Deliberate choices

- **Char bigrams, not word tokens** — robust to Korean particle/ending edits,
  no morphological analyzer dependency. O(n²) here; same shingles feed
  MinHash/LSH at production scale.
- **LLM only where the cheap signal is uncertain** — auto-merge ≥0.85,
  auto-reject ≤0.25, judge the band between. Cost-aware AI placement.
- **Identity signals classify, never merge** — handles collide; an author
  match distinguishes benign cross-posts from suspected seeding but is never
  sufficient evidence to merge on its own.
- **Threshold exposed as a slider** — it's a product policy (how aggressively
  you accuse reviewers of shilling), not an implementation detail.
- **Fictional clinics only** — you can't demo "suspected seeding" labels on
  real businesses.

## Run it

```bash
python3 pipeline.py          # stage 1 → docs/data.js
ANTHROPIC_API_KEY=... python3 judge.py   # stage 2 → fixtures/verdicts.json
python3 pipeline.py          # fold verdicts into docs/data.js
open docs/index.html         # or: python3 -m http.server -d docs
```

## Honesty notes

- Fixture corpus, not scraped data — labeled as such on the page.
- No API key on the build machine: the shipped `fixtures/verdicts.json` was
  produced by running `judge.py`'s exact prompt through Claude interactively;
  `judge.py` calls the API for real when a key is present.
- Clinic entity resolution (아이디병원 ≡ ID Hospital) is stubbed: the
  structured `clinic` field is assumed extracted upstream. It's the sibling
  hard problem and the obvious v2.

## v2

Real source connectors · MinHash/LSH blocking · clinic & surgeon entity
resolution · reviewer-graph seeding detection (burst timing, account age) ·
reader "report this review" signals feeding the same trust model.
