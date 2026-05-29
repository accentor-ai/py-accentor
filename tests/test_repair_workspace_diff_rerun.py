from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.evaluate.validation import RequiredFile


class WorkspaceRepairAgent:
    def __init__(self, edits: dict[str, str]) -> None:
        self.name = "WorkspaceRepairAgent"
        self.capabilities = AgentCapabilities(supports_files=True, supports_sandbox=True)
        self.edits = edits
        self.requests: list[AgentRequest] = []

    @property
    def run_count(self) -> int:
        return len(self.requests)

    def run(self, request: AgentRequest) -> AgentRunResult:
        self.requests.append(request)
        for name, text in self.edits.items():
            request.workspace.write_text(name, text)
        return AgentRunResult(ok=True, output="workspace edited", capabilities=self.capabilities)


def _delimiter_validator(candidate: object) -> bool:
    return candidate == {"delimiter": ","}


def test_repair_agent_edits_staged_workspace_diff_and_rerun_pass(tmp_path: Path) -> None:
    config_file = tmp_path / "parser.conf"
    config_file.write_text("delimiter=.\n", encoding="utf-8")
    artifact_root = tmp_path / "artifacts"
    agent = WorkspaceRepairAgent({"parser.conf": "delimiter=,\n"})

    @stage(
        name="parse_config",
        readable=[config_file],
        editable=[config_file],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Use a comma delimiter.",
                "validators": [_delimiter_validator],
            }
        },
    )
    def parse_config(path: Path) -> dict[str, str]:
        value = path.read_text(encoding="utf-8").strip().split("=", 1)[1]
        if value != ",":
            raise ValueError(f"bad delimiter: {value}")
        return {"delimiter": value}

    result = parse_config(config_file, artifact_root=artifact_root)

    assert result.ok is True
    assert result.output == {"delimiter": ","}
    assert result.attempt_count >= 2
    assert agent.run_count == 1
    assert agent.requests[0].workspace.list_files() == ["parser.conf"]
    assert (artifact_root / "incident.json").is_file()
    assert (artifact_root / "proposed_diff.patch").is_file()
    assert (artifact_root / "validation_report.json").is_file()
    verdict = json.loads((artifact_root / "diff_scope_verdict.json").read_text(encoding="utf-8"))
    assert verdict["ok"] is True
    assert verdict["changed_paths"] == ["parser.conf"]
    patch = (artifact_root / "proposed_diff.patch").read_text(encoding="utf-8")
    assert "-delimiter=." in patch
    assert "+delimiter=," in patch
    assert config_file.read_text(encoding="utf-8") == "delimiter=.\n"


def test_repair_rejects_out_of_scope_edits_before_validation(tmp_path: Path) -> None:
    config_file = tmp_path / "parser.conf"
    config_file.write_text("delimiter=.\n", encoding="utf-8")
    artifact_root = tmp_path / "artifacts"
    agent = WorkspaceRepairAgent(
        {
            "parser.conf": "delimiter=,\n",
            "undeclared.txt": "not allowed\n",
        }
    )

    @stage(
        name="parse_config",
        readable=[config_file],
        editable=[config_file],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Use a comma delimiter.",
                "validators": [_delimiter_validator],
            }
        },
    )
    def parse_config(path: Path) -> dict[str, str]:
        value = path.read_text(encoding="utf-8").strip().split("=", 1)[1]
        if value != ",":
            raise ValueError(f"bad delimiter: {value}")
        return {"delimiter": value}

    result = parse_config(config_file, artifact_root=artifact_root)

    assert result.ok is False
    assert any(diagnostic.code == "repair.diff_scope_violation" for diagnostic in result.diagnostics)
    verdict = json.loads((artifact_root / "diff_scope_verdict.json").read_text(encoding="utf-8"))
    assert verdict["ok"] is False
    assert verdict["violating_paths"] == ["undeclared.txt"]
    assert not (artifact_root / "validation_report.json").exists()


def test_mock_agent_cannot_fake_workspace_repair(tmp_path: Path) -> None:
    config_file = tmp_path / "parser.conf"
    config_file.write_text("delimiter=.\n", encoding="utf-8")
    artifact_root = tmp_path / "artifacts"
    agent = MockAgent(responses=["diff --git a/parser.conf b/parser.conf"])

    @stage(
        name="parse_config",
        readable=[config_file],
        editable=[config_file],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Use a comma delimiter.",
                "validators": [_delimiter_validator],
            }
        },
    )
    def parse_config(path: Path) -> dict[str, str]:
        value = path.read_text(encoding="utf-8").strip().split("=", 1)[1]
        if value != ",":
            raise ValueError(f"bad delimiter: {value}")
        return {"delimiter": value}

    result = parse_config(config_file, artifact_root=artifact_root)

    assert result.ok is False
    assert any(diagnostic.code == "repair.unsupported" for diagnostic in result.diagnostics)
    assert agent.run_count == 0
    assert (artifact_root / "incident.json").is_file()
    assert not (artifact_root / "proposed_diff.patch").exists()
    assert not (artifact_root / "diff_scope_verdict.json").exists()


def test_workflow_defers_repair_policy_validation_until_after_downstream_output(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "parser.conf"
    config_file.write_text("delimiter=.\n", encoding="utf-8")
    output_file = tmp_path / "workspace" / "summary.json"
    artifact_root = tmp_path / "artifacts"
    agent = WorkspaceRepairAgent({"parser.conf": "delimiter=,\n"})

    @stage(
        name="parse_config",
        readable=[config_file],
        editable=[config_file],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Use a comma delimiter.",
                "validators": [RequiredFile(output_file)],
            }
        },
    )
    def parse_config(path: Path) -> str:
        value = path.read_text(encoding="utf-8").strip().split("=", 1)[1]
        if value != ",":
            raise ValueError(f"bad delimiter: {value}")
        return value

    @stage(name="write_summary")
    def write_summary(delimiter: str) -> dict[str, Any]:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"delimiter": delimiter}
        output_file.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    @workflow(name="repair_flow")
    def repair_flow() -> dict[str, Any]:
        return write_summary(parse_config(config_file))

    result = repair_flow(artifact_root=artifact_root)

    assert result.ok is True
    assert result.output == {"delimiter": ","}
    assert result.attempt_count >= 2
    prompt = agent.requests[0].prompt
    assert str(output_file) in prompt
    assert "Do not create, delete, or modify validation target files" in prompt
    assert (artifact_root / "incident.json").is_file()
    assert (artifact_root / "proposed_diff.patch").is_file()
    assert (artifact_root / "diff_scope_verdict.json").is_file()
    assert (artifact_root / "validation_report.json").is_file()
    assert output_file.is_file()


def test_repair_rerun_uses_literal_globals_from_repaired_source(tmp_path: Path) -> None:
    source_file = tmp_path / "parser_module.py"
    data_file = tmp_path / "orders.csv"
    data_file.write_text("order_id,amount,status\n1001,10.00,paid\n", encoding="utf-8")
    source_text = "\n".join(
        [
            "from pathlib import Path",
            "CSV_DELIMITER = '.'",
            "",
            "def parse_orders(path):",
            "    if CSV_DELIMITER != ',':",
            "        raise ValueError(f'bad delimiter: {CSV_DELIMITER}')",
            "    return {'rows': Path(path).read_text(encoding='utf-8').splitlines()[1:]}",
            "",
        ]
    )
    source_file.write_text(source_text, encoding="utf-8")
    namespace: dict[str, Any] = {}
    exec(compile(source_text, str(source_file), "exec"), namespace)
    agent = WorkspaceRepairAgent(
        {"parser_module.py": source_text.replace("CSV_DELIMITER = '.'", "CSV_DELIMITER = ','")}
    )

    repaired_parse_orders = stage(
        name="parse_orders",
        readable=[source_file, data_file],
        editable=[source_file],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Use the comma CSV delimiter.",
                "validators": [lambda candidate: candidate == {"rows": ["1001,10.00,paid"]}],
            }
        },
    )(namespace["parse_orders"])

    result = repaired_parse_orders(data_file, artifact_root=tmp_path / "artifacts")

    assert result.ok is True
    assert result.output == {"rows": ["1001,10.00,paid"]}
    assert namespace["CSV_DELIMITER"] == "."
    assert source_file.read_text(encoding="utf-8") == source_text
