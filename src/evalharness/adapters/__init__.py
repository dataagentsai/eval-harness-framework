"""One module per provider; each imports its SDK and nothing else does.

The registry names each adapter by `module:Class` so that choosing one in
`evaluators.yaml` imports only that module (and its SDK).
"""

ADAPTERS: dict[str, str] = {
    "azure_groundedness": "evalharness.adapters.azure_groundedness:AzureGroundedness",
    "deepeval_tool_correctness": "evalharness.adapters.deepeval_tools:DeepEvalToolCorrectness",
    "presidio_pii": "evalharness.adapters.presidio_pii:PresidioPii",
    "ragas_faithfulness": "evalharness.adapters.ragas_faithfulness:RagasFaithfulness",
}
