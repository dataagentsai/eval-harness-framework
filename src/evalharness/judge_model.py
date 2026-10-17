"""One judge model, handed to each SDK in the shape that SDK wants.

Every LLM-judged check needs a model, and every SDK asks for it differently:
Azure takes a TypedDict, DeepEval a model object, Ragas an `instructor` client.
The judge is one setting in `evaluators.yaml`; this module is the only place
that knows the three shapes. Each SDK is imported only inside its method, so
choosing a judge installs nothing.

For a client, the judge is the client's own model endpoint (Azure OpenAI,
Bedrock); a free hosted model such as Groq is for our own and demo work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JudgeModel:
    model: str
    base_url: str
    api_key_env: str
    """The environment variable holding the key: the key itself is never in YAML."""
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    """USD per million tokens; 0 where unknown, and the cost then reads 0."""

    @property
    def api_key(self) -> str:
        return os.environ[self.api_key_env]

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1e6

    def for_azure(self) -> dict[str, Any]:
        from azure.ai.evaluation import OpenAIModelConfiguration

        return dict(
            OpenAIModelConfiguration(
                type="openai", model=self.model, base_url=self.base_url, api_key=self.api_key
            )
        )

    def for_deepeval(self) -> Any:
        from deepeval.models import GPTModel

        return GPTModel(model=self.model, base_url=self.base_url, api_key=self.api_key)

    def for_ragas(self) -> Any:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory

        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        return llm_factory(self.model, provider="openai", client=client)
