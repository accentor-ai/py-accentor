from __future__ import annotations

import importlib
import json
import subprocess
import sys

from accentor.evaluate.validation import ExactMatch, FileRequiredKeys, RequiredFile, RequiredKeys
from accentor.evaluate.validation.base import ValidationContext
from accentor.evaluate.validation.code import RuffValidator
from accentor.evaluate.validation.pydantic import PydanticModelValidator
from accentor.evaluate.validation.tabular import RequiredColumns


def test_required_file_accepts_existing_file(tmp_path):
    output = tmp_path / "report.txt"
    output.write_text("ready\n", encoding="utf-8")

    result = RequiredFile(output).validate()

    assert result.ok
    assert result.metadata["path"] == str(output)


def test_required_file_uses_workspace_context_for_relative_paths(tmp_path):
    output = tmp_path / "nested" / "report.txt"
    output.parent.mkdir()
    output.write_text("ready\n", encoding="utf-8")
    context = ValidationContext(workspace_root=tmp_path)

    result = RequiredFile("nested/report.txt").validate(context=context)

    assert result.ok
    assert result.metadata["path"] == str(output)


def test_missing_file_fails_without_raising(tmp_path):
    result = RequiredFile(tmp_path / "missing.txt").validate()

    assert not result.ok
    assert "not found" in result.message
    assert result.diagnostics[0].code == "validation.file_missing"


def test_file_required_keys_reads_json_file(tmp_path):
    output = tmp_path / "summary.json"
    output.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")

    assert FileRequiredKeys(output, keys=["a", "b"]).validate().ok

    missing = FileRequiredKeys(output, keys=["a", "c"]).validate()
    assert not missing.ok
    assert missing.metadata["missing_keys"] == ["c"]


def test_required_keys_path_compatibility_delegates_to_file_json(tmp_path):
    output = tmp_path / "summary.json"
    output.write_text(json.dumps({"paid_order_count": 2}), encoding="utf-8")

    result = RequiredKeys(output, keys=["paid_order_count"]).validate()

    assert result.ok


def test_exact_match_compares_normalized_text(tmp_path):
    output = tmp_path / "message.txt"
    output.write_text("READY\r\n", encoding="utf-8")

    result = ExactMatch(output, expected="READY").validate()

    assert result.ok


def test_exact_match_parses_json_for_dict_expected(tmp_path):
    output = tmp_path / "summary.json"
    output.write_text('{\n  "a": 1,\n  "b": [2]\n}\n', encoding="utf-8")

    result = ExactMatch(output, expected={"a": 1, "b": [2]}).validate()

    assert result.ok


def test_path_normalization_with_workspace_context(tmp_path):
    output = tmp_path / "summary.json"
    output.write_text(json.dumps({"a": 1}), encoding="utf-8")
    context = ValidationContext(workspace_root=tmp_path)

    result = ExactMatch("nested/../summary.json", expected={"a": 1}).validate(context=context)

    assert result.ok
    assert result.metadata["path"] == str(output)


def test_unsupported_stubs_fail_clearly_without_optional_dependencies():
    validators = [RuffValidator(), RequiredColumns(["id"]), PydanticModelValidator(object)]

    for validator in validators:
        result = validator.validate("candidate")
        assert not result.ok
        assert "[N]" in result.message
        assert result.diagnostics[0].code == "validation.unsupported"


def test_importing_pydantic_stub_does_not_import_pydantic():
    code = """
import importlib
import json
import sys

before = set(sys.modules)
importlib.import_module("accentor.evaluate.validation.pydantic")
after = set(sys.modules)
print(json.dumps("pydantic" in (after - before)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) is False


def test_root_validation_exports_supported_file_validators_only():
    module = importlib.import_module("accentor.evaluate.validation")

    assert module.RequiredFile is RequiredFile
    assert module.RequiredKeys is RequiredKeys
    assert "PydanticModelValidator" not in module.__all__
