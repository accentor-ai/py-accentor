from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from accentor.evaluate.expose import (
    ArtifactExtractor,
    CustomExtractor,
    ExtractionContext,
    ExtractionResult,
    FileExtractor,
    JsonExtractor,
    TextExtractor,
    extract_json,
)
from accentor.record.artifacts import ArtifactStore


def test_text_extractor_passthrough_and_context_metadata(assert_json_stable: Callable[[Any], Any]) -> None:
    result = TextExtractor().extract("plain response")

    assert result.raw == "plain response"
    assert result.raw_text == "plain response"
    assert result.parsed_available is False
    assert result.candidate(prefer_parsed=True) == "plain response"

    context = result.to_context(metadata={"validator": "text"})
    assert context.raw_candidate == "plain response"
    assert context.raw_text == "plain response"
    assert context.parsed_available is False
    assert context.metadata["validator"] == "text"

    payload = assert_json_stable(result.to_dict())
    assert payload["raw"] == "plain response"
    assert payload["has_parsed"] is False


def test_json_extractor_parses_fenced_and_unfenced_text() -> None:
    fenced = '```json\n{"title": "Accepted", "items": [1, 2]}\n```'
    fenced_result = JsonExtractor().extract(fenced)

    assert fenced_result.raw == fenced
    assert fenced_result.parsed_available is True
    assert fenced_result.parsed_json == {"title": "Accepted", "items": [1, 2]}
    assert fenced_result.metadata["json_source"] == "markdown_fence"
    assert fenced_result.diagnostics == ()

    unfenced = 'Here is the object:\n{"title": "Accepted", "items": [1, 2]}\nDone.'
    unfenced_result = extract_json(unfenced)

    assert unfenced_result.raw == unfenced
    assert unfenced_result.parsed_json == {"title": "Accepted", "items": [1, 2]}
    assert unfenced_result.metadata["json_source"] == "embedded_text"


def test_json_parse_failure_is_nonfatal_and_preserves_raw_text(
    assert_json_stable: Callable[[Any], Any],
) -> None:
    text = '{"title": }'

    result = JsonExtractor().extract(text)

    assert result.raw == text
    assert result.parsed_available is False
    assert result.candidate(prefer_parsed=True) == text
    assert len(result.parse_failures) == 1
    assert result.parse_failures[0].code == "extraction.json_parse_failed"
    assert result.diagnostics[0].severity == "warning"
    assert result.diagnostics[0].code == "extraction.json_parse_failed"

    payload = assert_json_stable(result.to_dict())
    assert payload["raw"] == text
    assert payload["has_parsed"] is False
    assert payload["parse_failures"][0]["line"] == 1


def test_json_extractor_accepts_already_parsed_python_values() -> None:
    candidate = {"status": "ok", "items": ["one", "two"], "count": 2}

    result = JsonExtractor().extract(candidate)

    assert result.raw is candidate
    assert result.parsed_json is candidate
    assert result.parsed_available is True
    assert result.metadata["json_source"] == "python_value"


def test_file_extractor_reads_text_and_json(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text('{"status": "ok", "count": 2}\n', encoding="utf-8")

    result = FileExtractor().extract(output)

    assert result.raw == '{"status": "ok", "count": 2}\n'
    assert result.parsed_json == {"status": "ok", "count": 2}
    assert result.metadata["path"] == str(output)

    text_only = FileExtractor(parse_json=False).extract(output)
    assert text_only.raw == '{"status": "ok", "count": 2}\n'
    assert text_only.parsed_available is False


def test_artifact_extractor_reads_store_and_artifact_records(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    record = store.write_json("responses/final.json", {"ok": True, "value": 7})
    context = ExtractionContext(artifact_store=store, artifact_root=store.root)

    from_store = ArtifactExtractor("responses/final.json").extract(context=context)

    assert from_store.raw.endswith("\n")
    assert from_store.parsed_json == {"ok": True, "value": 7}
    assert from_store.metadata["artifact_name"] == "responses/final.json"

    from_record = ArtifactExtractor().extract(record)
    assert from_record.parsed_json == {"ok": True, "value": 7}
    assert from_record.metadata["artifact"]["name"] == "responses/final.json"


def test_custom_extractor_can_receive_context() -> None:
    def expose_length(candidate: str, context: ExtractionContext | None = None) -> ExtractionResult:
        assert context is not None
        return ExtractionResult(raw=candidate, parsed={"length": len(candidate)}, has_parsed=True)

    result = CustomExtractor(expose_length).extract("abc", context={"source": "unit"})

    assert result.raw == "abc"
    assert result.parsed_json == {"length": 3}


def test_raw_and_parsed_preservation_distinguishes_json_null(
    assert_json_stable: Callable[[Any], Any],
) -> None:
    raw = "```json\nnull\n```"

    result = JsonExtractor().extract(raw)

    assert result.raw == raw
    assert result.parsed_available is True
    assert result.parsed_json is None
    assert result.candidate() == raw
    assert result.candidate(prefer_parsed=True) is None

    context = result.to_context()
    assert context.raw == raw
    assert context.parsed_available is True
    assert context.parsed_json is None

    payload = assert_json_stable(result.to_dict())
    assert payload["raw"] == raw
    assert payload["has_parsed"] is True
    assert payload["parsed"] is None
