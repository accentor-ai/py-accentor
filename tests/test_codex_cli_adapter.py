from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from accentor.dispatch.agents.base import AgentRequest
from accentor.dispatch.agents.providers.codex_cli import (
    CodexCli,
    CodexCliConfigurationError,
    CodexCliUnavailable,
    compile_codex_cli_command,
    normalize_sandbox_mode,
)
import accentor.dispatch.agents.providers.codex_cli.adapter as codex_adapter


def completed(
    argv: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def diagnostic_codes(result: object) -> list[str]:
    return [str(item.get("code")) for item in getattr(result, "diagnostics", [])]


def install_fake_codex(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exec_help: str,
    version: str = "codex 1.0.0",
    run_stdout: str = "stdout output",
    run_stderr: str = "",
    run_output: str = "last message",
    run_returncode: int = 0,
) -> list[list[str]]:
    calls: list[list[str]] = []

    monkeypatch.setattr(codex_adapter.shutil, "which", lambda executable: "/fake/bin/codex")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv == ["/fake/bin/codex", "--version"]:
            return completed(argv, stdout=version)
        if argv == ["/fake/bin/codex", "exec", "--help"]:
            return completed(argv, stdout=exec_help)

        output_file = Path(str(argv[argv.index("--output-last-message") + 1]))
        output_file.write_text(run_output, encoding="utf-8")
        assert kwargs.get("shell") is False
        return completed(
            argv,
            returncode=run_returncode,
            stdout=run_stdout,
            stderr=run_stderr,
        )

    monkeypatch.setattr(codex_adapter.subprocess, "run", fake_run)
    return calls


def test_codex_cli_construction_is_side_effect_light(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("construction must not probe subprocess")

    monkeypatch.setattr(codex_adapter.subprocess, "run", fail_run)

    adapter = CodexCli(session="persistent")

    assert adapter.name == "CodexCli"


def test_codex_cli_rejects_unknown_session_mode() -> None:
    with pytest.raises(ValueError, match="'persistent'"):
        CodexCli(session="latest")


def test_require_available_raises_when_executable_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda executable: None)

    with pytest.raises(CodexCliUnavailable, match="could not be found"):
        CodexCli(require_available=True)


def test_capabilities_probe_lazily_and_cache_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n",
    )
    adapter = CodexCli()

    assert calls == []

    first = adapter.capabilities
    second = adapter.capabilities

    assert first.supports_files is True
    assert first.supports_sandbox is True
    assert first.supports_persistence is False
    assert second == first
    assert calls == [
        ["/fake/bin/codex", "--version"],
        ["/fake/bin/codex", "exec", "--help"],
    ]


def test_persistence_capability_reflects_detected_resume_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n  --resume <SESSION>\n",
    )

    adapter = CodexCli(session="persistent")

    assert adapter.capabilities.supports_persistence is True


def test_persistence_capability_accepts_resume_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\nCommands:\n  resume  Resume a previous session\n  help\n",
        run_stderr="session id: sess-123",
    )

    adapter = CodexCli(session="persistent")
    first = adapter.run(AgentRequest(prompt="read"))
    second = adapter.run(AgentRequest(prompt="continue"))

    assert adapter.capabilities.supports_persistence is True
    assert first.ok is True
    assert second.ok is True
    model_calls = [call for call in calls if "--output-last-message" in call]
    assert model_calls[0][:2] == ["/fake/bin/codex", "exec"]
    assert model_calls[1][:3] == ["/fake/bin/codex", "exec", "resume"]
    assert "--skip-git-repo-check" not in model_calls[1]
    assert model_calls[1][-2:] == ["sess-123", "-"]


def test_persistence_capability_accepts_conversation_id_resume_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help=(
            "Usage: codex exec [OPTIONS]\n"
            "  --sandbox <MODE>\n"
            "  --conversation-id <ID>\n"
        ),
        run_stderr='{"conversation_id": "conv-123"}',
    )

    adapter = CodexCli(session="persistent")
    first = adapter.run(AgentRequest(prompt="hello"))
    second = adapter.run(AgentRequest(prompt="continue"))

    assert first.ok is True
    assert second.ok is True
    model_calls = [call for call in calls if "--output-last-message" in call]
    assert "--conversation-id" not in model_calls[0]
    assert model_calls[1][model_calls[1].index("--conversation-id") + 1] == "conv-123"


def test_persistent_session_unsupported_fails_before_model_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n",
    )

    result = CodexCli(session="persistent").run(AgentRequest(prompt="remember this"))

    assert result.ok is False
    assert "codex_cli.persistence_unsupported" in diagnostic_codes(result)
    assert not any("--output-last-message" in call for call in calls)
    assert result.capabilities is not None
    assert result.capabilities.supports_persistence is False


def test_successful_run_uses_output_file_and_captures_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n",
        run_stdout="stdout fallback",
        run_stderr="stderr notes",
        run_output="final from output file",
    )
    request = AgentRequest(prompt="hello", workspace={"root": tmp_path}, timeout_seconds=3)

    result = CodexCli(timeout_seconds=99).run(request)

    model_call = calls[-1]
    assert result.ok is True
    assert result.output == "final from output file"
    assert model_call[:2] == ["/fake/bin/codex", "exec"]
    assert ["--sandbox", "read-only"] == model_call[
        model_call.index("--sandbox") : model_call.index("--sandbox") + 2
    ]
    assert "--ask-for-approval" not in model_call
    assert ["--cd", str(tmp_path.resolve(strict=False))] == model_call[
        model_call.index("--cd") : model_call.index("--cd") + 2
    ]
    assert "--skip-git-repo-check" in model_call
    assert result.metadata["stdout"] == "stdout fallback"
    assert result.metadata["stderr"] == "stderr notes"
    assert result.metadata["command"][-1] == "-"
    assert result.capabilities is not None
    assert result.capabilities.supports_files is True


def test_messages_are_compiled_when_prompt_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n",
    )
    captured: dict[str, str] = {}
    original_run = codex_adapter.subprocess.run

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--output-last-message" in argv:
            captured["input"] = str(kwargs.get("input"))
        return original_run(argv, **kwargs)  # type: ignore[misc]

    monkeypatch.setattr(codex_adapter.subprocess, "run", fake_run)

    result = CodexCli().run(
        AgentRequest(
            messages=[
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "Summarize this."},
            ]
        )
    )

    assert result.ok is True
    assert captured["input"] == "system: Be terse.\nuser: Summarize this."


def test_persistent_session_extracts_redacts_reuses_and_rotates_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    run_index = 0
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda executable: "/fake/bin/codex")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal run_index
        calls.append(list(argv))
        if argv == ["/fake/bin/codex", "--version"]:
            return completed(argv, stdout="codex 1.0.0")
        if argv == ["/fake/bin/codex", "exec", "--help"]:
            return completed(
                argv,
                stdout="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n  --resume <SESSION>\n",
            )

        run_index += 1
        output_file = Path(str(argv[argv.index("--output-last-message") + 1]))
        output_file.write_text(f"turn {run_index}", encoding="utf-8")
        if run_index == 1:
            return completed(argv, stderr='{"session_id": "sess-123"}')
        if run_index == 2:
            assert argv[argv.index("--resume") + 1] == "sess-123"
            return completed(argv, stderr='{"continuation_token": "sess-456"}')
        assert argv[argv.index("--resume") + 1] == "sess-456"
        return completed(argv, stderr='{"continuation_token": "sess-789"}')

    monkeypatch.setattr(codex_adapter.subprocess, "run", fake_run)

    adapter = CodexCli(session="persistent")
    first = adapter.run(AgentRequest(prompt="read"))
    second = adapter.run(AgentRequest(prompt="answer"))
    third = adapter.run(AgentRequest(prompt="again"))

    assert first.ok is True
    assert second.ok is True
    assert third.ok is True
    assert first.metadata["session_reference_present"] is True
    assert first.metadata["session_reference_kind"] == "session_id"
    assert second.metadata["session_reused"] is True
    assert third.metadata["session_reused"] is True
    encoded_metadata = str([first.metadata, second.metadata, third.metadata])
    assert "sess-123" not in encoded_metadata
    assert "sess-456" not in encoded_metadata
    assert "sess-789" not in encoded_metadata
    assert any("--resume" in call for call in calls)


def test_persistent_first_run_requires_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n  --resume <SESSION>\n",
        run_output="READY",
        run_stderr="no reusable session metadata",
    )

    result = CodexCli(session="persistent").run(AgentRequest(prompt="read"))

    assert result.ok is False
    assert result.output == "READY"
    assert "codex_cli.persistence_reference_missing" in diagnostic_codes(result)


def test_one_shot_run_does_not_reuse_session_reference_from_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n  --resume <SESSION>\n",
        run_stderr='{"session_id": "sess-123"}',
    )
    adapter = CodexCli()

    first = adapter.run(AgentRequest(prompt="one"))
    second = adapter.run(AgentRequest(prompt="two"))

    assert first.ok is True
    assert second.ok is True
    model_calls = [call for call in calls if "--output-last-message" in call]
    assert len(model_calls) == 2
    assert not any("--resume" in call for call in model_calls)


def test_nonzero_exit_returns_structured_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_codex(
        monkeypatch,
        exec_help="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n",
        run_returncode=7,
        run_stderr="bad request",
    )

    result = CodexCli().run(AgentRequest(prompt="fail"))

    assert result.ok is False
    assert result.exit_code == 7
    assert "codex_cli.nonzero_exit" in diagnostic_codes(result)
    assert result.metadata["stderr"] == "bad request"


def test_timeout_returns_structured_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda executable: "/fake/bin/codex")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv == ["/fake/bin/codex", "--version"]:
            return completed(argv, stdout="codex 1.0.0")
        if argv == ["/fake/bin/codex", "exec", "--help"]:
            return completed(argv, stdout="Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n")
        raise subprocess.TimeoutExpired(argv, timeout=1, output="partial", stderr="late")

    monkeypatch.setattr(codex_adapter.subprocess, "run", fake_run)

    result = CodexCli(timeout_seconds=1).run(AgentRequest(prompt="timeout"))

    assert result.ok is False
    assert result.exit_code == 124
    assert "codex_cli.timeout" in diagnostic_codes(result)
    assert result.metadata["stdout"] == "partial"
    assert result.metadata["stderr"] == "late"


def test_sandbox_normalization_and_unsafe_refusal() -> None:
    assert normalize_sandbox_mode("read_only") == "read-only"
    assert normalize_sandbox_mode("workspace_write") == "workspace-write"

    with pytest.raises(CodexCliConfigurationError):
        normalize_sandbox_mode("danger-full-access")

    argv = compile_codex_cli_command(
        executable="codex",
        sandbox="danger-full-access",
        output_file="out.txt",
        allow_unsafe=True,
    )

    assert "--sandbox" in argv
    assert "danger-full-access" in argv


def test_extra_args_cannot_override_sandbox_or_bypass_safety() -> None:
    with pytest.raises(CodexCliConfigurationError, match="sandbox"):
        compile_codex_cli_command(extra_args=["--sandbox", "workspace-write"])

    with pytest.raises(CodexCliConfigurationError, match="unsafe"):
        compile_codex_cli_command(extra_args=["--dangerously-bypass-approvals-and-sandbox"])
