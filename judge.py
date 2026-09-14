#!/usr/bin/env python3
"""Stage 2: LLM judge for uncertain duplicate candidates.

Cost design: stage 1 (pipeline.py) auto-merges near-exact copies and
auto-rejects clearly-distinct pairs; only the uncertain band plus
metadata-nominated cross-language pairs reach this judge — 4 of 190
possible pairs in the demo corpus.

With ANTHROPIC_API_KEY set, calls the Claude API and writes
fixtures/verdicts.json. Without a key, prints each prompt so the same
judgment can be run through Claude interactively (the shipped
verdicts.json for this demo was produced that way — see README).
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
MODEL = "claude-sonnet-5"

PROMPT_TEMPLATE = """You are a review-integrity judge for a Korean plastic-surgery
review aggregator. Two reviews were nominated as possible duplicates by cheap
signals (character-bigram Jaccard={jaccard}, metadata_match={metadata_match},
same_author_hint={author_match}). Using ONLY the evidence below, classify the pair.

Review A ({a_id}) — source: {a_source} · handle: {a_handle} · clinic: {a_clinic} ·
procedure: {a_procedure} · price_krw: {a_price} · date: {a_date}
---
{a_text}
---

Review B ({b_id}) — source: {b_source} · handle: {b_handle} · clinic: {b_clinic} ·
procedure: {b_procedure} · price_krw: {b_price} · date: {b_date}
---
{b_text}
---

Answer with strict JSON, no prose:
{{"relation": "cross-post" | "paraphrase-seeding" | "cross-language-duplicate"
             | "coincidental-similarity" | "distinct",
  "confidence": 0.0-1.0,
  "rationale": "<= 2 sentences citing concrete evidence from the texts"}}

Definitions: cross-post = same author reposting; paraphrase-seeding = same text
skeleton lightly edited under different identities (marketing seeding);
cross-language-duplicate = same underlying account of one experience in two
languages; coincidental-similarity = independent reviews sharing generic
phrasing; distinct = unrelated. Do not invent facts not present above."""


def load_candidates():
    data_js = (ROOT / "docs" / "data.js").read_text(encoding="utf-8")
    data = json.loads(data_js[data_js.index("{") : data_js.rindex("}") + 1])
    by_id = {r["id"]: r for r in data["reviews"]}
    return [(p, by_id[p["a"]], by_id[p["b"]]) for p in data["pairs"] if p["needs_judge"]]


def build_prompt(pair, a, b):
    return PROMPT_TEMPLATE.format(
        jaccard=pair["jaccard"], metadata_match=pair["metadata_match"], author_match=pair["author_match"],
        a_id=a["id"], a_source=a["source"], a_handle=a["author_handle"], a_clinic=a["clinic"],
        a_procedure=a["procedure"], a_price=a["price_krw"], a_date=a["date"], a_text=a["text"],
        b_id=b["id"], b_source=b["source"], b_handle=b["author_handle"], b_clinic=b["clinic"],
        b_procedure=b["procedure"], b_price=b["price_krw"], b_date=b["date"], b_text=b["text"],
    )


def call_claude(prompt, api_key):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(
            {"model": MODEL, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}
        ).encode(),
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    text = body["content"][0]["text"]
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


def main():
    candidates = load_candidates()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("No ANTHROPIC_API_KEY — printing prompts for interactive judging.\n", file=sys.stderr)
        for pair, a, b in candidates:
            print(f"===== PAIR {pair['a']}-{pair['b']} =====\n{build_prompt(pair, a, b)}\n")
        return

    verdicts = []
    for pair, a, b in candidates:
        verdict = call_claude(build_prompt(pair, a, b), api_key)
        verdict.update({"a": pair["a"], "b": pair["b"], "generated_via": f"api:{MODEL}"})
        verdicts.append(verdict)
        print(f"{pair['a']}-{pair['b']}: {verdict['relation']} ({verdict['confidence']})")
    (ROOT / "fixtures" / "verdicts.json").write_text(
        json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote fixtures/verdicts.json — re-run pipeline.py to fold into docs/data.js")


if __name__ == "__main__":
    main()
