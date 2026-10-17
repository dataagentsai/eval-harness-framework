"""One judge model, handed to each SDK in the shape that SDK wants.

Every LLM-judged check needs a model, and every SDK asks for it differently:
Azure takes a TypedDict, DeepEval a model object, Ragas an `instructor` client.
The judge is one setting in the stack profile; this module is the only place
that knows the three shapes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

GROQ = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class Judge:
    model: str
    base_url: str
    api_key: str

    @classmethod
    def from_env(cls, model: str = "openai/gpt-oss-120b") -> Judge:
        return cls(model, os.environ.get("GROQ_BASE_URL", GROQ), os.environ["GROQ_API_KEY"])

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
