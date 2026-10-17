"""Run every adapter live on every case it can judge; save each provider's raw
answer to `tests/fixtures/` and print our normalised result beside it.

    GROQ_API_KEY=... python scripts/record_fixtures.py

Re-run after upgrading a provider SDK; a changed fixture is the diff to review.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from cases import CASES  # noqa: E402
from evalharness.config import load  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for adapter in load(ROOT / "evaluators.example.yaml").values():
        for case, request in CASES.items():
            if adapter.needs - request.provides():
                continue
            try:
                raw = adapter.call(adapter.to_provider(request))
            except Exception as failure:
                print(
                    f"{adapter.kind:28} {case:24} CALL FAILED {type(failure).__name__}: {failure}"
                )
                continue
            path = FIXTURES / f"{adapter.kind}__{case}.json"
            path.write_text(json.dumps(raw, indent=2, default=str, ensure_ascii=False) + "\n")
            result = adapter.from_provider(raw, request)
            print(f"{adapter.kind:28} {case:24} {result.verdict:5} score={result.score:.2f}")


if __name__ == "__main__":
    main()
