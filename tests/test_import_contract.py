"""Each vendor SDK is imported by its own adapter module and nowhere else.

`judge_model` is the one shared exception: it hands the judge to each judged SDK
in that SDK's shape, importing each only inside the method that needs it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "evalharness"
VENDORS = (
    "azure",
    "deepeval",
    "ragas",
    "presidio_analyzer",
    "presidio_anonymizer",
    "openai",
    "langchain",
    "spacy",
)
ALLOWED: dict[str, set[str]] = {
    "adapters/azure_groundedness.py": {"azure"},
    "adapters/deepeval_tools.py": {"deepeval"},
    "adapters/ragas_faithfulness.py": {"ragas"},
    "adapters/presidio_pii.py": {"presidio_analyzer"},
    "judge_model.py": {"azure", "deepeval", "ragas", "openai"},
}
MODULES = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py"))


def vendors_imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names = (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
        found |= {n.split(".")[0] for n in names if n.split(".")[0] in VENDORS}
    return found


@pytest.mark.parametrize("module", MODULES)
def test_a_vendor_is_imported_only_where_allowed(module: str) -> None:
    assert vendors_imported(SRC / module) <= ALLOWED.get(module, set())


def test_vendor_imports_happen_inside_functions_so_importing_evalharness_installs_nothing() -> None:
    for module in ALLOWED:
        top = ast.parse((SRC / module).read_text()).body
        at_top = [n for n in top if isinstance(n, ast.Import | ast.ImportFrom)]
        assert not any(vendors_imported_node(n) for n in at_top), module


def vendors_imported_node(node: ast.Import | ast.ImportFrom) -> bool:
    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
    return any(n.split(".")[0] in VENDORS for n in names)
