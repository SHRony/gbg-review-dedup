#!/usr/bin/env python3
"""Review dedup pipeline for Gangnam Beauty Guide (demo).

Stage 1 (this file, cheap, runs on everything):
  normalize -> char-bigram Jaccard -> candidate blocking (text / metadata /
  author) -> signals emitted to docs/data.js for the demo page, which
  clusters client-side so the threshold slider works live.

Stage 2 (judge.py, expensive, runs on almost nothing):
  LLM verdicts for pairs in the uncertain similarity band and for
  metadata-nominated cross-language pairs.

Design choices (deliberate):
  * Char bigrams, not word tokens: Korean is agglutinative; word tokenization
    needs a morphological analyzer (konlpy + JVM) — wrong tradeoff for a demo.
    Char n-grams are language-agnostic and robust to particle/ending changes.
  * O(n^2) pairwise is fine at n=20; at production scale the same shingles
    feed MinHash/LSH for sublinear candidate generation.
  * Author-handle matches CLASSIFY pairs (cross-post vs suspected seeding)
    but never MERGE on their own — handles collide too often to be proof.
  * Duplicates are flagged, never deleted: the duplication pattern itself is
    a trust signal.
"""

import json
import re
from datetime import date
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT_THRESHOLD = 0.55          # merge threshold shown by the page slider
UNCERTAIN_BAND = (0.25, 0.85)     # stage-2 LLM judge only sees this band
METADATA_PRICE_TOLERANCE = 0.05
METADATA_DATE_WINDOW_DAYS = 14

PRICE_RE = re.compile(r"(?:₩\s*[\d,]+|[\d,]+\s*(?:만\s*원|만원|원|krw|won)|[\d][\d,]{3,})", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Fold prices to a token, drop punctuation/emoji, remove whitespace."""
    t = text.lower()
    t = PRICE_RE.sub(" <p> ", t)
    kept = []
    for ch in t:
        if "가" <= ch <= "힣" or ch.isalnum() or ch.isspace() or ch in "<>":
            kept.append(ch)
        else:
            kept.append(" ")
    return re.sub(r"\s+", "", "".join(kept))


def bigrams(s: str) -> set:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def norm_handle(handle: str) -> str:
    return re.sub(r"[\d_\-.*]+", "", handle.lower())


def author_match(h1: str, h2: str) -> bool:
    a, b = norm_handle(h1), norm_handle(h2)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 4 and shorter in longer


def parse_date(d: str) -> date:
    y, m, dd = map(int, d.split("-"))
    return date(y, m, dd)


def metadata_match(r1: dict, r2: dict) -> bool:
    """Blocking on structured fields — the only way a cross-language
    duplicate can be nominated, since char n-grams score it ~0."""
    if r1["procedure"] != r2["procedure"]:
        return False
    p1, p2 = r1["price_krw"], r2["price_krw"]
    if not p1 or not p2 or abs(p1 - p2) / max(p1, p2) > METADATA_PRICE_TOLERANCE:
        return False
    delta = abs((parse_date(r1["date"]) - parse_date(r2["date"])).days)
    return delta <= METADATA_DATE_WINDOW_DAYS


def main() -> None:
    reviews = json.loads((ROOT / "fixtures" / "reviews.json").read_text(encoding="utf-8"))
    grams = {r["id"]: bigrams(normalize_text(r["text"])) for r in reviews}
    by_id = {r["id"]: r for r in reviews}

    pairs = []
    for r1, r2 in combinations(reviews, 2):
        sim = jaccard(grams[r1["id"]], grams[r2["id"]])
        am = author_match(r1["author_handle"], r2["author_handle"])
        mm = metadata_match(r1, r2)
        cross_lang = r1["lang"] != r2["lang"]
        interesting = sim >= 0.2 or (mm and cross_lang) or (am and r1["author_handle"] != r2["author_handle"])
        if not interesting:
            continue
        pairs.append(
            {
                "a": r1["id"],
                "b": r2["id"],
                "jaccard": round(sim, 3),
                "author_match": am,
                "metadata_match": mm,
                "cross_language": cross_lang,
                "needs_judge": (UNCERTAIN_BAND[0] <= sim <= UNCERTAIN_BAND[1]) or (mm and cross_lang and sim < UNCERTAIN_BAND[0]),
            }
        )

    # Serial-promoter pattern: one normalized handle, many clinics, all reviews.
    by_handle = {}
    for r in reviews:
        by_handle.setdefault(norm_handle(r["author_handle"]) or r["author_handle"], set()).add(r["clinic"])
    promoters = sorted(h for h, clinics in by_handle.items() if len(clinics) >= 3)

    verdicts_path = ROOT / "fixtures" / "verdicts.json"
    verdicts = json.loads(verdicts_path.read_text(encoding="utf-8")) if verdicts_path.exists() else []

    data = {
        "generated_by": "pipeline.py (stage 1) + judge.py (stage 2)",
        "default_threshold": DEFAULT_THRESHOLD,
        "uncertain_band": UNCERTAIN_BAND,
        "reviews": reviews,
        "pairs": pairs,
        "promoter_handles": promoters,
        "verdicts": verdicts,
    }

    out = "const DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "data.js").write_text(out, encoding="utf-8")

    print(f"reviews={len(reviews)} pairs_kept={len(pairs)} promoters={promoters}")
    for p in sorted(pairs, key=lambda p: -p["jaccard"]):
        print(
            f"  {p['a']}-{p['b']} jac={p['jaccard']:.3f} "
            f"author={'Y' if p['author_match'] else 'n'} meta={'Y' if p['metadata_match'] else 'n'} "
            f"xlang={'Y' if p['cross_language'] else 'n'} judge={'Y' if p['needs_judge'] else 'n'}"
        )


if __name__ == "__main__":
    main()
