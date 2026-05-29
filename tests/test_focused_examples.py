from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_focused_examples_import() -> None:
    examples_root = REPO_ROOT / "examples" / "focused_examples"
    for path in sorted(examples_root.glob("*/example.py")):
        module_name = f"focused_{path.parent.name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def test_adapter_contract_focused_example_runs_mock_path() -> None:
    result = subprocess.run(
        [sys.executable, "examples/focused_examples/06_adapter_contract/example.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "All tested adapters satisfy the AgentRunResult contract." in result.stdout
    assert "Skipping CodexCli" in result.stdout
