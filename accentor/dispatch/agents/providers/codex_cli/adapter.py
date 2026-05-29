from __future__ import annotations

"""Codex CLI provider adapter.

This module deliberately wraps the local ``codex`` executable through
``subprocess``. It does not import a provider SDK or claim sandbox enforcement
beyond selecting Codex CLI's own sandbox mode.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re
import shutil
import subprocess
import tempfile
import time

from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult


_HELP_TIMEOUT_SECONDS = 5.0
_TIMEOUT_EXIT_CODE = 124
_TEXT_TRIM_LIMIT = 4000
_SESSION_REFERENCE_KEYS = {
    "session_id",
    "conversation_id",
    "thread_id",
    "resume_token",
    "continuation_token",
    "codex_session_id",
}
_SESSION_REFERENCE_RE = re.compile(
    r"\b("
    r"codex[_ -]?session[_ -]?id|session[_ -]?id|conversation[_ -]?id|"
    r"thread[_ -]?id|resume[_ -]?token|continuation[_ -]?token"
    r")\b\"?\s*[:=]\s*\"?([A-Za-z0-9._:-]{1,256})\"?",
    re.IGNORECASE,
)
_RESUME_FLAGS = (
    "resume-subcommand",
    "--resume",
    "--session-id",
    "--conversation-id",
    "--thread-id",
    "--session",
    "--continue",
    "--continuation-token",
)

_SANDBOX_ALIASES = {
    "read-only": "read-only",
    "read_only": "read-only",
    "readonly": "read-only",
    "workspace-write": "workspace-write",
    "workspace_write": "workspace-write",
    "workspacewrite": "workspace-write",
    "write": "workspace-write",
    "danger-full-access": "danger-full-access",
    "danger_full_access": "danger-full-access",
}
_UNSUPPORTED_SANDBOX_MODES = {"", "none", "external"}
_DANGEROUS_EXTRA_FLAGS = {
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
}
_ADAPTER_CONTROLLED_FLAGS = {
    "--sandbox",
    "-s",
    "--output-last-message",
    "-o",
    "--cd",
    "-C",
    "--color",
    "--ask-for-approval",
    "-a",
}


class CodexCliUnavailable(RuntimeError):
    """Raised by explicit availability checks when Codex CLI is unavailable."""


class CodexCliConfigurationError(ValueError):
    """Raised when a local Codex CLI invocation would violate v1 safety rules."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class CodexCliCommand:
    """Compiled, shell-free Codex CLI command."""

    argv: tuple[str, ...]
    sandbox: str

    def __contains__(self, item: object) -> bool:
        return item in self.argv

    def __iter__(self):
        return iter(self.argv)

    def __getitem__(self, index):
        return self.argv[index]

    def __len__(self) -> int:
        return len(self.argv)

    def index(self, value: str) -> int:
        return self.argv.index(value)


@dataclass(frozen=True, slots=True)
class _Availability:
    available: bool
    executable_path: str | None = None
    version: str | None = None
    supports_exec: bool = False
    supports_sandbox: bool = False
    supports_persistence: bool = False
    resume_flag: str | None = None
    reason: str | None = None
    help_text: str = ""


@dataclass(frozen=True, slots=True)
class _SessionReference:
    kind: str
    value: str


def _diagnostic(
    *,
    code: str,
    message: str,
    severity: str = "error",
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "source": "codex_cli",
        "hint": hint,
        "details": dict(details or {}),
    }


def _trim_text(value: object, *, limit: int = _TEXT_TRIM_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[trimmed {len(text) - limit} chars]"


def normalize_sandbox_mode(sandbox: str | None, *, allow_unsafe: bool = False) -> str:
    """Return a Codex CLI sandbox mode or raise a configuration error."""

    raw = "read-only" if sandbox is None else str(sandbox).strip().lower()
    normalized = _SANDBOX_ALIASES.get(raw.replace("_", "-"), _SANDBOX_ALIASES.get(raw))
    if normalized in {"read-only", "workspace-write"}:
        return normalized
    if normalized == "danger-full-access":
        if allow_unsafe:
            return normalized
        raise CodexCliConfigurationError(
            "codex_cli.unsafe_sandbox",
            "Codex CLI danger-full-access sandbox mode is refused by default.",
            hint="Pass allow_unsafe=True only in an externally sandboxed environment.",
            details={"sandbox": sandbox},
        )
    if raw in _UNSUPPORTED_SANDBOX_MODES:
        raise CodexCliConfigurationError(
            "codex_cli.invalid_sandbox",
            "Codex CLI adapter requires read-only or workspace-write sandbox mode in v1.",
            hint="Use sandbox='read-only' or sandbox='workspace-write'.",
            details={"sandbox": sandbox},
        )
    raise CodexCliConfigurationError(
        "codex_cli.invalid_sandbox",
        f"Unsupported Codex CLI sandbox mode: {sandbox!r}.",
        hint="Use sandbox='read-only' or sandbox='workspace-write'.",
        details={"sandbox": sandbox},
    )


def _validate_extra_args(extra_args: Sequence[str] | None, *, allow_unsafe: bool) -> tuple[str, ...]:
    validated: list[str] = []
    for arg in extra_args or ():
        text = str(arg)
        flag = text.split("=", 1)[0]
        if flag in _DANGEROUS_EXTRA_FLAGS:
            raise CodexCliConfigurationError(
                "codex_cli.unsafe_extra_arg",
                f"unsafe Codex CLI flag is not allowed: {flag}.",
                hint="Do not bypass Codex CLI approvals or sandboxing from Accentor v1.",
                details={"flag": flag},
            )
        if flag in _ADAPTER_CONTROLLED_FLAGS:
            if flag in {"--sandbox", "-s"}:
                message = "extra_args must not override the selected Codex CLI sandbox."
            else:
                message = f"Codex CLI flag is controlled by the adapter: {flag}."
            raise CodexCliConfigurationError(
                "codex_cli.controlled_extra_arg",
                message,
                hint="Use the adapter constructor or provider options for sandbox, cwd, and output behavior.",
                details={"flag": flag, "allow_unsafe": allow_unsafe},
            )
        validated.append(text)
    return tuple(validated)


def compile_codex_cli_command(
    *,
    executable: str = "codex",
    sandbox: str = "read-only",
    output_file: str | Path | None = None,
    model: str | None = None,
    profile: str | None = None,
    cwd: str | Path | None = None,
    workspace_root: str | Path | None = None,
    extra_args: Sequence[str] | None = None,
    allow_unsafe: bool = False,
    search: bool = False,
    resume_reference: str | None = None,
    resume_flag: str | None = None,
) -> CodexCliCommand:
    """Compile a shell-free non-interactive Codex CLI command."""

    normalized_sandbox = normalize_sandbox_mode(sandbox, allow_unsafe=allow_unsafe)
    validated_extra_args = _validate_extra_args(extra_args, allow_unsafe=allow_unsafe)

    argv: list[str] = [str(executable)]
    if search:
        argv.append("--search")
    root = cwd if cwd is not None else workspace_root
    if resume_reference is not None and resume_flag == "resume-subcommand":
        argv.extend(["exec", "resume"])
        if output_file is not None:
            argv.extend(["--output-last-message", str(output_file)])
        if model:
            argv.extend(["--model", str(model)])
        if root is not None:
            argv.append("--skip-git-repo-check")
        argv.extend(validated_extra_args)
        argv.extend([str(resume_reference), "-"])
        return CodexCliCommand(argv=tuple(argv), sandbox=normalized_sandbox)

    argv.extend(
        [
            "exec",
            "--sandbox",
            normalized_sandbox,
            "--color",
            "never",
        ]
    )
    if output_file is not None:
        argv.extend(["--output-last-message", str(output_file)])
    if model:
        argv.extend(["--model", str(model)])
    if profile:
        argv.extend(["--profile", str(profile)])
    if root is not None:
        argv.extend(["--cd", str(root)])
        argv.append("--skip-git-repo-check")
    if resume_reference is not None:
        argv.extend([resume_flag or "--resume", str(resume_reference)])
    argv.extend(validated_extra_args)
    argv.append("-")
    return CodexCliCommand(argv=tuple(argv), sandbox=normalized_sandbox)


def _redacted_argv(argv: Sequence[str], *, session_reference: str | None = None) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    redact_session_next = False
    for arg in argv:
        if redact_next:
            redacted.append("[output-file]")
            redact_next = False
            continue
        if redact_session_next:
            redacted.append("[REDACTED_SESSION]")
            redact_session_next = False
            continue
        if session_reference is not None and str(arg) == session_reference:
            redacted.append("[REDACTED_SESSION]")
            continue
        redacted.append(str(arg))
        if arg in {"--output-last-message", "-o"}:
            redact_next = True
        if arg in _RESUME_FLAGS:
            redact_session_next = True
    return redacted


def _redact_session_text(text: object, *, known_reference: str | None = None) -> str:
    value = _trim_text(text, limit=12000)
    if known_reference:
        value = value.replace(known_reference, "[REDACTED_SESSION]")
    return _SESSION_REFERENCE_RE.sub(
        lambda match: f"{match.group(1)}: [REDACTED_SESSION]",
        value,
    )


def _validate_session_reference(value: object) -> str | None:
    text = _trim_text(value).strip()
    if not text or len(text) > 256:
        return None
    if any(char.isspace() for char in text):
        return None
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
        return None
    return text


def _find_session_reference(value: object) -> _SessionReference | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SESSION_REFERENCE_KEYS:
                reference = _validate_session_reference(item)
                if reference is not None:
                    if normalized == "codex_session_id":
                        normalized = "session_id"
                    return _SessionReference(kind=normalized, value=reference)
        for item in value.values():
            found = _find_session_reference(item)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_session_reference(item)
            if found is not None:
                return found
    return None


def _json_objects(text: str) -> list[object]:
    stripped = text.strip()
    if not stripped:
        return []
    objects: list[object] = []
    try:
        objects.append(json.loads(stripped))
        return objects
    except json.JSONDecodeError:
        pass
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            objects.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return objects


def _extract_session_reference(*, stdout: str, stderr: str) -> _SessionReference | None:
    for stream in (stderr, stdout):
        for item in _json_objects(stream):
            found = _find_session_reference(item)
            if found is not None:
                return found
    for match in _SESSION_REFERENCE_RE.finditer(stderr):
        reference = _validate_session_reference(match.group(2))
        if reference is None:
            continue
        kind = match.group(1).lower().replace("-", "_").replace(" ", "_")
        if kind == "codex_session_id":
            kind = "session_id"
        return _SessionReference(kind=kind, value=reference)
    return None


def _prompt_from_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "message")).strip() or "message"
        content = message.get("content", message.get("text", message.get("message", "")))
        lines.append(f"{role}: {_trim_text(content, limit=10000)}")
    return "\n".join(lines).strip()


def _prompt_from_request(request: AgentRequest) -> str:
    if isinstance(request.prompt, str) and request.prompt.strip():
        return request.prompt
    if request.messages:
        return _prompt_from_messages(request.messages)
    return ""


def _mapping_bool(value: Any, *keys: str) -> bool:
    if isinstance(value, Mapping):
        current: Any = value
        for key in keys:
            if not isinstance(current, Mapping) or key not in current:
                return False
            current = current[key]
        return bool(current)
    return False


def _search_requested(request: AgentRequest) -> bool:
    if bool(request.provider_options.get("search")):
        return True
    network = request.permissions.get("network")
    if network is True:
        return True
    return _mapping_bool(network, "search")


def _sandbox_from_request(request: AgentRequest, adapter_sandbox: str) -> str:
    options = request.provider_options
    permissions = request.permissions
    explicit = (
        options.get("sandbox")
        or options.get("sandbox_mode")
        or permissions.get("sandbox")
        or permissions.get("sandbox_mode")
    )
    if explicit:
        return str(explicit)
    editable = permissions.get("editable")
    if editable:
        return "workspace-write"
    return adapter_sandbox


def _option_string(value: Any, fallback: str | None = None) -> str | None:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _option_extra_args(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(item) for item in value)
    except TypeError:
        return (str(value),)


def _workspace_root(workspace: Any) -> Path | None:
    if workspace is None:
        return None
    if isinstance(workspace, Path):
        return workspace.resolve(strict=False)
    if isinstance(workspace, str):
        return Path(workspace).resolve(strict=False)
    if isinstance(workspace, Mapping):
        for key in ("root", "path", "workspace_root"):
            if key in workspace and workspace[key] is not None:
                value = workspace[key]
                if isinstance(value, (str, Path)):
                    return Path(value).resolve(strict=False)
                raise CodexCliConfigurationError(
                    "codex_cli.invalid_workspace",
                    "Workspace root could not be converted to a filesystem path.",
                    details={"key": key, "type": type(value).__name__},
                )
        return None
    for attr in ("root", "path", "workspace_root"):
        value = getattr(workspace, attr, None)
        if value is not None:
            if isinstance(value, (str, Path)):
                return Path(value).resolve(strict=False)
            raise CodexCliConfigurationError(
                "codex_cli.invalid_workspace",
                "Workspace root could not be converted to a filesystem path.",
                details={"attribute": attr, "type": type(value).__name__},
            )
    return None


class CodexCli:
    """Thin subprocess adapter around the installed ``codex`` executable."""

    name = "CodexCli"

    def __init__(
        self,
        *,
        executable: str = "codex",
        sandbox: str = "read-only",
        model: str | None = None,
        profile: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: float | None = None,
        session: str | None = None,
        require_available: bool = False,
        allow_unsafe: bool = False,
        extra_args: Sequence[str] | None = None,
    ) -> None:
        if session is not None and session != "persistent":
            raise ValueError("CodexCli session must be None or session='persistent'")
        self.executable = str(executable)
        self.sandbox = str(sandbox)
        self.model = model
        self.profile = profile
        self.cwd = Path(cwd) if cwd is not None else None
        self.timeout_seconds = float(timeout_seconds) if timeout_seconds is not None else None
        self.session = session
        self.allow_unsafe = bool(allow_unsafe)
        self.extra_args = tuple(str(arg) for arg in (extra_args or ()))
        self._availability: _Availability | None = None
        self._session_reference: str | None = None
        self._session_reference_kind: str | None = None
        if require_available:
            self.require_available()

    @property
    def capabilities(self) -> AgentCapabilities:
        return self._capabilities().snapshot()

    def require_available(self) -> "CodexCli":
        availability = self._detect_availability()
        if not availability.available:
            raise CodexCliUnavailable(availability.reason or "Codex CLI is unavailable.")
        return self

    def close(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentRunResult:
        start = time.monotonic()
        if not isinstance(request, AgentRequest):
            return self._failure_result(
                code="codex_cli.invalid_request",
                message="CodexCli.run expects an AgentRequest.",
                elapsed_seconds=0.0,
                details={"type": type(request).__name__},
            )

        availability = self._detect_availability()
        if not availability.available:
            return self._failure_result(
                code="codex_cli.unavailable",
                message=availability.reason or "Codex CLI is unavailable.",
                elapsed_seconds=time.monotonic() - start,
                details={"executable": self.executable},
            )

        prompt = _prompt_from_request(request)
        if not prompt:
            return self._failure_result(
                code="codex_cli.empty_request",
                message="Codex CLI request did not contain prompt text or messages.",
                elapsed_seconds=time.monotonic() - start,
            )
        if self.session == "persistent" and not availability.supports_persistence:
            return self._failure_result(
                code="codex_cli.persistence_unsupported",
                message="Codex CLI does not expose a supported non-interactive persistence surface.",
                elapsed_seconds=time.monotonic() - start,
                details={"session": self.session, "version": availability.version},
            )

        try:
            workspace_root = _workspace_root(request.workspace) or self.cwd
            output = self._run_subprocess(
                request=request,
                availability=availability,
                prompt=prompt,
                workspace_root=workspace_root,
                started_at=start,
            )
            return output
        except CodexCliConfigurationError as exc:
            return self._failure_result(
                code=exc.code,
                message=str(exc),
                elapsed_seconds=time.monotonic() - start,
                hint=exc.hint,
                details=exc.details,
            )

    def _run_subprocess(
        self,
        *,
        request: AgentRequest,
        availability: _Availability,
        prompt: str,
        workspace_root: Path | None,
        started_at: float,
    ) -> AgentRunResult:
        options = request.provider_options
        timeout_seconds = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else self.timeout_seconds
        )
        sandbox = _sandbox_from_request(request, self.sandbox)
        model = _option_string(options.get("model"), self.model)
        profile = _option_string(options.get("profile"), self.profile)
        extra_args = (*self.extra_args, *_option_extra_args(options.get("extra_args")))
        diagnostics: list[dict[str, Any]] = []
        resume_reference = self._session_reference if self.session == "persistent" else None
        resume_flag = availability.resume_flag if resume_reference is not None else None

        with tempfile.TemporaryDirectory(prefix="accentor-codex-cli-") as tmpdir:
            output_file = Path(tmpdir) / "last_message.txt"
            command = compile_codex_cli_command(
                executable=availability.executable_path or self.executable,
                sandbox=sandbox,
                output_file=output_file,
                model=model,
                profile=profile,
                cwd=workspace_root,
                extra_args=extra_args,
                allow_unsafe=self.allow_unsafe,
                search=_search_requested(request),
                resume_reference=resume_reference,
                resume_flag=resume_flag,
            )
            if command.sandbox == "danger-full-access":
                diagnostics.append(
                    _diagnostic(
                        code="codex_cli.unsafe_sandbox_allowed",
                        message="Codex CLI danger-full-access sandbox mode was explicitly allowed.",
                        severity="warning",
                        hint="Use only in externally sandboxed environments.",
                        details={"sandbox": command.sandbox},
                    )
                )
            try:
                completed = subprocess.run(
                    list(command.argv),
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                    shell=False,
                    cwd=str(workspace_root) if workspace_root is not None else None,
                )
            except FileNotFoundError:
                self._availability = _Availability(
                    available=False,
                    executable_path=None,
                    reason=f"Codex CLI executable could not be found: {self.executable}",
                )
                return self._failure_result(
                    code="codex_cli.unavailable",
                    message=f"Codex CLI executable could not be found: {self.executable}",
                    elapsed_seconds=time.monotonic() - started_at,
                    diagnostics=diagnostics,
                    metadata=self._metadata(
                        command=command,
                        stdout="",
                        stderr="",
                        session_reference=resume_reference,
                    ),
                    details={"executable": self.executable},
                )
            except PermissionError as exc:
                return self._failure_result(
                    code="codex_cli.launch_error",
                    message="Codex CLI executable could not be launched.",
                    elapsed_seconds=time.monotonic() - started_at,
                    diagnostics=diagnostics,
                    metadata=self._metadata(
                        command=command,
                        stdout="",
                        stderr=str(exc),
                        session_reference=resume_reference,
                    ),
                    details={"error": str(exc), "exception_type": type(exc).__name__},
                )
            except subprocess.TimeoutExpired as exc:
                stdout = _trim_text(exc.output)
                stderr = _trim_text(exc.stderr)
                return AgentRunResult(
                    ok=False,
                    output=stdout,
                    elapsed_seconds=time.monotonic() - started_at,
                    exit_code=_TIMEOUT_EXIT_CODE,
                    diagnostics=[
                        *diagnostics,
                        _diagnostic(
                            code="codex_cli.timeout",
                            message="Codex CLI invocation timed out.",
                            hint="Increase timeout_seconds or reduce the requested work.",
                            details={
                                "timeout_seconds": timeout_seconds,
                                "stdout": stdout,
                                "stderr": stderr,
                            },
                        ),
                    ],
                    capabilities=self.capabilities,
                    metadata=self._metadata(
                        command=command,
                        stdout=stdout,
                        stderr=stderr,
                        session_reference=resume_reference,
                    ),
                )
            except OSError as exc:
                return self._failure_result(
                    code="codex_cli.launch_error",
                    message="Codex CLI executable could not be launched.",
                    elapsed_seconds=time.monotonic() - started_at,
                    diagnostics=diagnostics,
                    metadata=self._metadata(
                        command=command,
                        stdout="",
                        stderr=str(exc),
                        session_reference=resume_reference,
                    ),
                    details={"error": str(exc), "exception_type": type(exc).__name__},
                )

            stdout = _trim_text(completed.stdout)
            stderr = _trim_text(completed.stderr)
            output, output_diagnostic = self._read_output(output_file, fallback=stdout)
            if output_diagnostic is not None:
                diagnostics.append(output_diagnostic)
            elapsed = time.monotonic() - started_at
            metadata = self._metadata(
                command=command,
                stdout=stdout,
                stderr=stderr,
                session_reference=resume_reference,
            )
            metadata["returncode"] = completed.returncode

            if completed.returncode != 0:
                return AgentRunResult(
                    ok=False,
                    output=output,
                    elapsed_seconds=elapsed,
                    exit_code=completed.returncode,
                    diagnostics=[
                        *diagnostics,
                        _diagnostic(
                            code="codex_cli.nonzero_exit",
                            message=f"Codex CLI exited with status {completed.returncode}.",
                            hint="Inspect stderr and the captured command metadata.",
                            details={
                                "exit_code": completed.returncode,
                                "stderr": stderr,
                            },
                        ),
                    ],
                    capabilities=self.capabilities,
                    metadata=metadata,
                )

            if self.session == "persistent":
                found_reference = _extract_session_reference(stdout=stdout, stderr=stderr)
                if found_reference is None and self._session_reference is None:
                    return AgentRunResult(
                        ok=False,
                        output=output,
                        elapsed_seconds=elapsed,
                        exit_code=0,
                        diagnostics=[
                            *diagnostics,
                            _diagnostic(
                                code="codex_cli.persistence_reference_missing",
                                message=(
                                    "Codex CLI did not emit a reusable session reference "
                                    "for the persistent run."
                                ),
                                details={"session_reference_present": False},
                            ),
                        ],
                        capabilities=self.capabilities,
                        metadata={
                            **metadata,
                            "session": self.session,
                            "session_reused": resume_reference is not None,
                            "session_reference_present": False,
                            "session_reference_kind": self._session_reference_kind,
                        },
                    )
                if found_reference is not None:
                    self._session_reference = found_reference.value
                    self._session_reference_kind = found_reference.kind
                    metadata = self._metadata(
                        command=command,
                        stdout=stdout,
                        stderr=stderr,
                        session_reference=found_reference.value,
                        session_reused=resume_reference is not None,
                    )
                    metadata["returncode"] = completed.returncode

            return AgentRunResult(
                ok=True,
                output=output,
                elapsed_seconds=elapsed,
                exit_code=0,
                diagnostics=diagnostics,
                capabilities=self.capabilities,
                metadata=metadata,
            )

    def _detect_availability(self) -> _Availability:
        if self._availability is not None:
            return self._availability

        executable_path = shutil.which(self.executable)
        if executable_path is None:
            self._availability = _Availability(
                available=False,
                reason=f"Codex CLI executable could not be found: {self.executable}",
            )
            return self._availability

        version: str | None = None
        try:
            version_completed = subprocess.run(
                [executable_path, "--version"],
                capture_output=True,
                text=True,
                timeout=_HELP_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
            if version_completed.returncode == 0:
                version = "\n".join(
                    item
                    for item in (version_completed.stdout, version_completed.stderr)
                    if item
                ).strip() or None
        except (OSError, subprocess.TimeoutExpired):
            version = None

        try:
            completed = subprocess.run(
                [executable_path, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=_HELP_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._availability = _Availability(
                available=False,
                executable_path=executable_path,
                reason=f"Codex CLI availability probe failed: {exc}",
            )
            return self._availability

        help_text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        supports_exec = completed.returncode == 0 and "exec" in help_text.lower()
        supports_sandbox = "--sandbox" in help_text or "-s, --sandbox" in help_text
        resume_flag = next((flag for flag in _RESUME_FLAGS if flag in help_text), None)
        if resume_flag is None and re.search(r"^\s+resume\s+", help_text, re.MULTILINE):
            resume_flag = "resume-subcommand"
        supports_persistence = resume_flag is not None
        if not supports_exec:
            self._availability = _Availability(
                available=False,
                executable_path=executable_path,
                version=version,
                supports_exec=False,
                supports_sandbox=supports_sandbox,
                supports_persistence=supports_persistence,
                resume_flag=resume_flag,
                reason="Codex CLI does not expose a usable non-interactive exec command.",
                help_text=help_text,
            )
            return self._availability

        self._availability = _Availability(
            available=True,
            executable_path=executable_path,
            version=version,
            supports_exec=True,
            supports_sandbox=supports_sandbox,
            supports_persistence=supports_persistence,
            resume_flag=resume_flag,
            help_text=help_text,
        )
        return self._availability

    def _capabilities(self) -> AgentCapabilities:
        availability = self._detect_availability()
        if not availability.available:
            return AgentCapabilities()
        return AgentCapabilities(
            supports_files=True,
            supports_shell=False,
            supports_sandbox=availability.supports_sandbox,
            supports_persistence=availability.supports_persistence,
            supports_resume=availability.supports_persistence,
            supports_streaming=False,
            supports_tool_receipts=False,
        )

    def _failure_result(
        self,
        *,
        code: str,
        message: str,
        elapsed_seconds: float,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
        diagnostics: Sequence[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            ok=False,
            output="",
            elapsed_seconds=elapsed_seconds,
            exit_code=1,
            diagnostics=[
                *(diagnostics or ()),
                _diagnostic(code=code, message=message, hint=hint, details=details),
            ],
            capabilities=self.capabilities,
            metadata=metadata or {"adapter": self.name, "executable": self.executable},
        )

    def _metadata(
        self,
        *,
        command: CodexCliCommand,
        stdout: str,
        stderr: str,
        session_reference: str | None = None,
        session_reused: bool | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "adapter": self.name,
            "executable": self.executable,
            "command": _redacted_argv(command.argv, session_reference=session_reference),
            "sandbox": command.sandbox,
            "stdout": _redact_session_text(stdout, known_reference=session_reference),
            "stderr": _redact_session_text(stderr, known_reference=session_reference),
        }
        if self.session is not None:
            metadata["session"] = self.session
            metadata["session_reused"] = (
                session_reference is not None if session_reused is None else session_reused
            )
            metadata["session_reference_present"] = (
                self._session_reference is not None or session_reference is not None
            )
            metadata["session_reference_kind"] = self._session_reference_kind
        return metadata

    def _read_output(
        self,
        output_file: Path,
        *,
        fallback: str,
    ) -> tuple[str, dict[str, Any] | None]:
        if not output_file.exists():
            return fallback, None
        try:
            output = output_file.read_text(encoding="utf-8")
        except OSError as exc:
            return fallback, _diagnostic(
                code="codex_cli.output_read_failed",
                message="Codex CLI last-message output file could not be read.",
                severity="warning",
                details={"error": str(exc), "exception_type": type(exc).__name__},
            )
        if output:
            return output, None
        return fallback, None


__all__ = [
    "CodexCli",
    "CodexCliCommand",
    "CodexCliConfigurationError",
    "CodexCliUnavailable",
    "compile_codex_cli_command",
    "normalize_sandbox_mode",
]
