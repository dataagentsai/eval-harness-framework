"""Run every adapter live on every case it can judge; save each provider's raw
answer to `fixtures/` and print our normalised result beside it.

    python -m spike.record            # needs GROQ_API_KEY for the judged checks
"""

from __future__ import annotations

import json
from pathlib import Path

from spike.adapter import Adapter
from spike.adapters.azure_groundedness import AzureGroundedness
from spike.adapters.deepeval_tools import DeepEvalToolCorrectness
from spike.adapters.presidio_pii import PresidioPii
from spike.adapters.ragas_faithfulness import RagasFaithfulness
from spike.cases import CASES
from spike.judge import Judge

FIXTURES = Path(__file__).parent / "fixtures"


def adapters() -> list[Adapter]:
    judge = Judge.from_env()
    return [AzureGroundedness(judge), DeepEvalToolCorrectness(judge),RagasFaithfulness(judge), PresidioPii()]


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for adapter in adapters():
        for case, request in CASES.items():
            if adapter.needs - request.provides():
                continue
            try:
                raw = adapter.call(adapter.to_provider(request))
            except Exception as failure:
                print(f"{adapter.name:28} {case:24} CALL FAILED {type(failure).__name__}: {failure}")
                continue
            path = FIXTURES / f"{adapter.name}__{case}.json"
            path.write_text(json.dumps(raw, indent=2, default=str, ensure_ascii=False) + "\n")
            result = adapter.from_provider(raw, request)
            print(
                f"{adapter.name:28} {case:24} {result.verdict:5} "
                f"score={result.score:.2f} raw={result.raw_score} label={result.label!r} "
                f"findings={len(result.findings)} dropped={adapter.dropped(request)}"
            )


if __name__ == "__main__":
    main()
