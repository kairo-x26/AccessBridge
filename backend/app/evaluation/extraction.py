"""Measure extraction precision/recall on the synthetic corpus (spec §14: ≥95% / ≥95%).

Run: ``uv run python -m app.evaluation.extraction``
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass

from app.domain.checklists import CRITICAL_FIELDS
from app.evaluation.corpus import Sample, corpus
from app.services import document_ai

MIN_CONFIDENCE = 0.6


@dataclass
class Scores:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


def evaluate(samples: list[Sample]) -> dict[str, Scores]:
    per_field: dict[str, Scores] = {}
    for s in samples:
        best: dict[str, document_ai.Candidate] = {}
        for c in document_ai.extract_fields(s.text):
            if c.confidence >= MIN_CONFIDENCE and (
                c.name not in best or c.confidence > best[c.name].confidence
            ):
                best[c.name] = c
        names = set(s.truth) | set(best)
        for name in names:
            sc = per_field.setdefault(name, Scores())
            got, want = best.get(name), s.truth.get(name)
            if got and want and got.value == want:
                sc.tp += 1
            else:
                if got:
                    sc.fp += 1
                if want:
                    sc.fn += 1
    return per_field


def report(n: int = 300, seed: int = 7, unseen: bool = False) -> dict[str, object]:
    scores = evaluate(corpus(n, seed, unseen))
    crit = Scores()
    for name in CRITICAL_FIELDS:
        s = scores.get(name, Scores())
        crit.tp, crit.fp, crit.fn = crit.tp + s.tp, crit.fp + s.fp, crit.fn + s.fn
    return {
        "samples": n,
        "label_set": "unseen" if unseen else "template",
        "extractor": document_ai.EXTRACTOR_VERSION,
        "critical": {"precision": round(crit.precision, 4), "recall": round(crit.recall, 4)},
        "fields": {
            k: {
                "precision": round(v.precision, 4),
                "recall": round(v.recall, 4),
                **Counter(tp=v.tp, fp=v.fp, fn=v.fn),
            }
            for k, v in sorted(scores.items())
        },
    }


if __name__ == "__main__":
    out = report()
    held_out = report(unseen=True)
    print(json.dumps({"template": out, "unseen_labels": held_out}, indent=2))
    crit = out["critical"]
    assert isinstance(crit, dict)
    sys.exit(0 if crit["precision"] >= 0.95 and crit["recall"] >= 0.95 else 1)
