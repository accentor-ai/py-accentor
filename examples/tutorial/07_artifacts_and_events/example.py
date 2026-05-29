"""Tutorial 07: Artifacts and Events — persistent inspection of workflow runs.

Part 1: ArtifactStore — path-safe storage, write/read, ArtifactRecord, path
        confinement, and what happens when names try to escape the root.
Part 2: Promotion helpers — promote_artifact, promote_json_artifact,
        promote_validation_report, and the manifest.
Part 3: TaskEvent factory methods — constructing every event type, to_dict(),
        and the canonical event_type vocabulary.
Part 4: TaskObserver and JsonlSink — wiring observation into a workflow,
        serializing events to disk, and reading them back.
Part 5: ObservationPolicy and redaction — which fields get redacted by default,
        custom sensitive field lists, and redaction-off mode.
Part 6: Full workflow with artifact_root — an agent-backed stage that produces
        artifacts, events.jsonl, and task_result.json on disk.
Part 7: What artifacts and events won't do (by design).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow
from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.evaluate.validation import JsonRequired, NoMarkdownFences
from accentor.record.artifacts import (
    ArtifactPathError,
    ArtifactRecord,
    ArtifactStore,
    promote_artifact,
    promote_json_artifact,
    promote_text_artifact,
    promote_validation_report,
)
from accentor.record.observe import (
    DEFAULT_SENSITIVE_FIELD_NAMES,
    JsonlSink,
    ObservationPolicy,
    REDACTED_VALUE,
    TaskObserver,
    json_safe,
    serialize_task_event,
)


# ---------------------------------------------------------------------------
# Part 1: ArtifactStore basics
# ---------------------------------------------------------------------------

def part1_artifact_store() -> None:
    print("=" * 60)
    print("PART 1: ArtifactStore — path-safe storage and records")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp(prefix="accentor_tut07_p1_"))
    try:
        store = ArtifactStore(tmp)
        print(f"\n  root: {store.root}")

        # write_text returns an ArtifactRecord with name, path, size, sha256.
        rec = store.write_text("notes.txt", "Hello from tutorial 07.\n")
        print(f"\n  write_text('notes.txt'):")
        print(f"    name:       {rec.name}")
        print(f"    size_bytes: {rec.size_bytes}")
        print(f"    sha256:     {rec.sha256[:16]}...")
        print(f"    to_dict():  {sorted(rec.to_dict().keys())}")

        # write_json serializes Python data as indented JSON.
        data = {"stage": "summarize", "ok": True, "validators_passed": 3}
        rec_json = store.write_json("results/task_result.json", data)
        print(f"\n  write_json('results/task_result.json'):")
        print(f"    name:       {rec_json.name}")
        print(f"    size_bytes: {rec_json.size_bytes}")

        # read_text / read_json round-trip.
        text_back = store.read_text("notes.txt")
        json_back = store.read_json("results/task_result.json")
        print(f"\n  read_text:  {text_back.strip()!r}")
        print(f"  read_json:  {json_back}")

        # write_bytes for binary data.
        rec_bin = store.write_bytes("logo.bin", b"\x89PNG\r\n\x1a\n")
        print(f"\n  write_bytes('logo.bin'): {rec_bin.size_bytes} bytes")

        # list_artifacts sees everything in the store.
        all_artifacts = store.list_artifacts()
        print(f"\n  list_artifacts(): {len(all_artifacts)} records")
        for a in all_artifacts:
            print(f"    {a.name} ({a.size_bytes} bytes)")

        # Path confinement: absolute names and traversals are rejected.
        print(f"\n  Path safety:")
        for bad_name in ["/etc/passwd", "../escape.txt", "sub/../../escape.txt"]:
            try:
                store.write_text(bad_name, "should fail")
                print(f"    {bad_name!r}: UNEXPECTED SUCCESS")
            except ArtifactPathError as exc:
                print(f"    {bad_name!r}: blocked ({type(exc).__name__})")

        # record() creates an ArtifactRecord for an already-existing file.
        rec_existing = store.record("notes.txt")
        print(f"\n  record('notes.txt'): sha256 matches write_text? "
              f"{rec_existing.sha256 == rec.sha256}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 2: Promotion helpers and manifest
# ---------------------------------------------------------------------------

def part2_promotion() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Promotion helpers and manifest")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp(prefix="accentor_tut07_p2_"))
    try:
        store = ArtifactStore(tmp)

        # promote_text_artifact writes text directly into the store.
        rec = promote_text_artifact(store, "prompts/attempt_1.txt",
                                    "Summarize the issue.\nIssue: CSV import fails.")
        print(f"\n  promote_text_artifact:")
        print(f"    name: {rec.name}")
        print(f"    size: {rec.size_bytes} bytes")

        # promote_json_artifact writes structured data.
        report = {"ok": True, "passed": 4, "failed": 0, "validators": ["A", "B", "C", "D"]}
        rec = promote_json_artifact(store, "validation_report.json", report)
        print(f"\n  promote_json_artifact:")
        print(f"    name: {rec.name}")

        # promote_validation_report is a convenience alias.
        rec = promote_validation_report(store, {"ok": False, "failed": 1})
        # Note: default name is "validation_report.json" — overwrites previous.
        print(f"\n  promote_validation_report (default name):")
        print(f"    name: {rec.name}")
        print(f"    content: {store.read_json(rec.name)}")

        # promote_artifact copies an external file into the store.
        external = tmp / "_external_data.csv"
        external.write_text("id,value\n1,alpha\n2,beta\n")
        rec = promote_artifact(store, external, "inputs/data.csv")
        print(f"\n  promote_artifact (external file):")
        print(f"    name: {rec.name}")

        # manifest() returns a JSON-stable summary of all artifacts.
        manifest = store.manifest()
        print(f"\n  manifest():")
        print(f"    artifact_count: {manifest['artifact_count']}")
        for entry in manifest["artifacts"]:
            print(f"    - {entry['name']} ({entry['size_bytes']} bytes)")

        # write_manifest persists the manifest as an artifact itself.
        manifest_rec = store.write_manifest()
        print(f"\n  write_manifest(): {manifest_rec.name}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 3: TaskEvent factory methods
# ---------------------------------------------------------------------------

def part3_events() -> None:
    print("\n" + "=" * 60)
    print("PART 3: TaskEvent factory methods — the event vocabulary")
    print("=" * 60)

    # Every event has event_type, timestamp, and optional context fields.
    # Factory methods set event_type and status automatically.

    e1 = TaskEvent.workflow_started(workflow="order_summary")
    print(f"\n  workflow_started:")
    print(f"    event_type: {e1.event_type}")
    print(f"    workflow:   {e1.workflow}")
    print(f"    status:     {e1.status}")
    print(f"    timestamp:  {e1.timestamp[:19]}...")

    e2 = TaskEvent.stage_started(stage="parse_csv", workflow="order_summary", attempt=1)
    print(f"\n  stage_started:")
    print(f"    event_type: {e2.event_type}")
    print(f"    stage:      {e2.stage}")
    print(f"    attempt:    {e2.attempt}")

    e3 = TaskEvent.stage_completed(
        stage="parse_csv",
        workflow="order_summary",
        attempt=1,
        status="completed",
        validation={"ok": True, "passed": 3, "failed": 0},
    )
    print(f"\n  stage_completed:")
    print(f"    event_type:  {e3.event_type}")
    print(f"    status:      {e3.status}")
    print(f"    validation:  {dict(e3.validation)}")

    # Validation event with diagnostics.
    e4 = TaskEvent.validation_recorded(
        validation={"ok": False, "passed": 2, "failed": 1},
        stage="summarize",
        attempt=1,
        diagnostics=[
            Diagnostic.error(code="val.title_too_long", message="Title exceeds 5 words."),
        ],
    )
    print(f"\n  validation_recorded:")
    print(f"    event_type:   {e4.event_type}")
    print(f"    diagnostics:  {e4.diagnostics[0].code}: {e4.diagnostics[0].message}")

    # Routing event.
    e5 = TaskEvent.routing_decided(
        routing={"selected": "technical", "confidence": 0.9, "omitted": ["policy"]},
        stage="draft_reply",
    )
    print(f"\n  routing_decided:")
    print(f"    routing: {dict(e5.routing)}")

    # Repair event.
    e6 = TaskEvent.repair_recorded(
        repair={"verdict": "accepted", "changed_paths": ["orders.csv"]},
        stage="parse_orders",
        status="repaired",
    )
    print(f"\n  repair_recorded:")
    print(f"    repair: {dict(e6.repair)}")

    # Artifact event.
    e7 = TaskEvent.artifact_recorded(
        artifact={"name": "task_result.json", "size_bytes": 256},
        workflow="order_summary",
    )
    print(f"\n  artifact_recorded:")
    print(f"    artifacts: {[dict(a) for a in e7.artifacts]}")

    # Workflow completed with diagnostics.
    e8 = TaskEvent.workflow_completed(
        workflow="order_summary",
        status="failed",
        diagnostics=[Diagnostic.warning(code="wf.partial", message="Stage 2 failed.")],
    )
    print(f"\n  workflow_completed:")
    print(f"    status:     {e8.status}")
    print(f"    diagnostic: {e8.diagnostics[0].code}")

    # to_dict() produces a JSON-stable dictionary for every event.
    d = e3.to_dict()
    print(f"\n  to_dict() keys: {sorted(d.keys())}")

    # The canonical event_type vocabulary:
    all_types = [e.event_type for e in [e1, e2, e3, e4, e5, e6, e7, e8]]
    print(f"\n  Event type vocabulary demonstrated:")
    for et in all_types:
        print(f"    {et}")


# ---------------------------------------------------------------------------
# Part 4: TaskObserver and JsonlSink
# ---------------------------------------------------------------------------

def part4_observer() -> None:
    print("\n" + "=" * 60)
    print("PART 4: TaskObserver and JsonlSink — capturing events")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp(prefix="accentor_tut07_p4_"))
    try:
        # JsonlSink writes one JSON object per line to events.jsonl.
        sink = JsonlSink(tmp)
        print(f"\n  JsonlSink path: {sink.path}")

        # TaskObserver wraps sinks and applies redaction policy.
        observer = TaskObserver([sink])

        # emit() serializes a TaskEvent, stores it in memory, and forwards to sinks.
        e1 = TaskEvent.workflow_started(workflow="demo")
        serialized = observer.emit(e1)
        print(f"\n  emit(workflow_started):")
        print(f"    serialized keys: {sorted(serialized.keys())}")
        print(f"    event_type:      {serialized['event_type']}")

        e2 = TaskEvent.stage_started(stage="summarize", workflow="demo", attempt=1)
        observer.emit(e2)

        e3 = TaskEvent.stage_completed(stage="summarize", workflow="demo", attempt=1)
        observer.emit(e3)

        e4 = TaskEvent.workflow_completed(workflow="demo")
        observer.emit(e4)

        # In-memory event log.
        print(f"\n  observer.events: {len(observer.events)} captured")

        # Close flushes and releases the sink.
        observer.close()

        # Read back the JSONL file.
        lines = sink.path.read_text().strip().splitlines()
        print(f"\n  events.jsonl: {len(lines)} lines")
        for line in lines:
            event = json.loads(line)
            print(f"    {event['event_type']}: "
                  f"stage={event.get('stage') or '-'}, "
                  f"workflow={event.get('workflow') or '-'}")

        # Context manager form.
        sink2 = JsonlSink(tmp, filename="events2.jsonl")
        with TaskObserver([sink2]) as obs:
            obs.emit(TaskEvent.workflow_started(workflow="cm_demo"))
            obs.emit(TaskEvent.workflow_completed(workflow="cm_demo"))
        # sink2 is auto-closed here.
        lines2 = sink2.path.read_text().strip().splitlines()
        print(f"\n  Context manager: {len(lines2)} events in events2.jsonl")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 5: ObservationPolicy and redaction
# ---------------------------------------------------------------------------

def part5_redaction() -> None:
    print("\n" + "=" * 60)
    print("PART 5: ObservationPolicy — redaction of sensitive fields")
    print("=" * 60)

    # Default policy redacts common prompt/input field names.
    policy = ObservationPolicy()
    print(f"\n  Default sensitive fields ({len(DEFAULT_SENSITIVE_FIELD_NAMES)}):")
    for name in sorted(DEFAULT_SENSITIVE_FIELD_NAMES):
        print(f"    {name}")
    print(f"  Replacement: {REDACTED_VALUE!r}")

    # Redaction applies recursively to nested dicts.
    raw = {
        "event_type": "stage.completed",
        "stage": "summarize",
        "details": {
            "prompt": "Summarize the ticket about CSV failures.",
            "model": "gpt-4",
            "input": "Customer says CSV import is broken.",
        },
    }
    redacted = policy.redact(raw)
    print(f"\n  Before redaction:")
    print(f"    details.prompt: {raw['details']['prompt']!r}")
    print(f"    details.input:  {raw['details']['input']!r}")
    print(f"    details.model:  {raw['details']['model']!r}")
    print(f"\n  After redaction:")
    print(f"    details.prompt: {redacted['details']['prompt']!r}")
    print(f"    details.input:  {redacted['details']['input']!r}")
    print(f"    details.model:  {redacted['details']['model']!r}")

    # serialize_task_event applies policy to a real TaskEvent.
    event = TaskEvent.stage_completed(
        stage="summarize",
        details={"prompt": "Secret prompt content", "model": "gpt-4"},
    )
    serialized = serialize_task_event(event, policy=policy)
    print(f"\n  serialize_task_event with default policy:")
    details = serialized.get("details", {})
    print(f"    details.prompt: {details.get('prompt')!r}")
    print(f"    details.model:  {details.get('model')!r}")

    # Custom policy with additional sensitive field names.
    custom_policy = ObservationPolicy(
        sensitive_field_names=DEFAULT_SENSITIVE_FIELD_NAMES | frozenset({"api_key", "token"}),
        replacement="***HIDDEN***",
    )
    custom_raw = {"api_key": "sk-12345", "token": "abc", "stage": "test"}
    custom_redacted = custom_policy.redact(custom_raw)
    print(f"\n  Custom policy (api_key, token added):")
    print(f"    api_key: {custom_redacted['api_key']!r}")
    print(f"    token:   {custom_redacted['token']!r}")
    print(f"    stage:   {custom_redacted['stage']!r}")

    # Redaction off: set redact_sensitive_fields=False.
    no_redact = ObservationPolicy(redact_sensitive_fields=False)
    raw_through = no_redact.redact({"prompt": "visible", "input": "also visible"})
    print(f"\n  Redaction disabled:")
    print(f"    prompt: {raw_through['prompt']!r}")
    print(f"    input:  {raw_through['input']!r}")

    # json_safe converts Python objects to JSON-compatible values.
    print(f"\n  json_safe examples:")
    print(f"    Path:       {json_safe(Path('/tmp/test'))!r}")
    print(f"    frozenset:  {json_safe(frozenset({3, 1, 2}))}")
    print(f"    Diagnostic: {type(json_safe(Diagnostic.info(code='test', message='hi'))).__name__}")


# ---------------------------------------------------------------------------
# Part 6: Full workflow with artifact_root
# ---------------------------------------------------------------------------

def part6_full_workflow() -> None:
    print("\n" + "=" * 60)
    print("PART 6: Full workflow — artifacts, events, and task_result")
    print("=" * 60)

    mock_reply = json.dumps({
        "title": "CSV Import Fix",
        "summary": "Blank plan names cause onboarding failures.",
    })
    agent = MockAgent(responses=[mock_reply])

    @stage(
        name="summarize",
        agent=agent,
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["title", "summary"]),
        ],
        max_attempts=1,
        inject_criteria=True,
    )
    def summarize(issue_text: str, success_criteria: str = "") -> str:
        return f"Summarize this issue.\n{success_criteria}\nIssue: {issue_text}"

    @workflow(name="artifact_demo")
    def demo() -> dict:
        return summarize("CSV import fails on blank plan names.")

    artifact_dir = Path(tempfile.mkdtemp(prefix="accentor_tut07_p6_"))
    try:
        result = demo(artifact_root=artifact_dir)

        print(f"\n  ok:            {result.ok}")
        print(f"  attempt_count: {result.attempt_count}")
        print(f"  output:        {json.dumps(result.output, indent=2)}")

        # Artifacts recorded in the result.
        print(f"\n  result.artifacts: {len(result.artifacts)}")
        for artifact in result.artifacts:
            if hasattr(artifact, "name"):
                print(f"    {artifact.name} ({artifact.size_bytes} bytes)")
            elif isinstance(artifact, dict):
                print(f"    {artifact.get('name', '?')}")

        # Files on disk.
        print(f"\n  Files on disk:")
        for path in sorted(artifact_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(artifact_dir)
                size = path.stat().st_size
                print(f"    {rel} ({size} bytes)")

        # events.jsonl reconstruction.
        events_path = artifact_dir / "events.jsonl"
        if events_path.exists():
            print(f"\n  events.jsonl:")
            for line in events_path.read_text().strip().splitlines():
                event = json.loads(line)
                print(f"    {event['event_type']}: "
                      f"stage={event.get('stage') or '-'}, "
                      f"workflow={event.get('workflow') or '-'}")

        # task_result.json.
        tr_path = artifact_dir / "task_result.json"
        if tr_path.exists():
            stored = json.loads(tr_path.read_text())
            print(f"\n  task_result.json:")
            print(f"    ok:            {stored['ok']}")
            print(f"    attempt_count: {stored['attempt_count']}")
            print(f"    output keys:   {sorted(stored.get('output', {}).keys())}")

        # Events from the result object.
        print(f"\n  result.events ({len(result.events)} total):")
        for event in result.events:
            extra = ""
            if event.validation:
                extra = f" validation.ok={event.validation.get('ok')}"
            print(f"    {event.event_type}: "
                  f"{event.stage or event.workflow or '-'}{extra}")

    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 7: What artifacts and events won't do
# ---------------------------------------------------------------------------

def part7_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 7: What artifacts and events won't do (by design)")
    print("=" * 60)

    print("""
    ArtifactStore:
    - Will NOT allow path traversal. Names like "../escape.txt" or absolute
      paths raise ArtifactPathError. Every artifact is confined to the root.
    - Will NOT upload to cloud storage. ArtifactStore is local filesystem only.
      Cloud backends (S3, GCS) are [U] stubs — reserved names, not behavior.
    - Will NOT version artifacts. Writing the same name overwrites the file.
      If you need history, use distinct names (attempt_1.txt, attempt_2.txt).
    - Will NOT compress or encrypt. Files are written as-is. Add compression
      in your own pipeline if needed.

    TaskEvent:
    - Will NOT enforce event ordering. Events carry timestamps but the runtime
      does not sort or sequence-number them. Order comes from emission order.
    - Will NOT validate cross-event consistency. A stage_completed without a
      matching stage_started is valid — events are standalone records.
    - Will NOT carry large payloads. Events hold metadata references (artifact
      names, sizes, hashes), not file contents. Read artifacts separately.

    TaskObserver:
    - Will NOT buffer events for batch processing. Each emit() is immediate
      to every sink. Use your own batching layer if needed.
    - Will NOT recover from sink failures. If a sink raises, the exception
      propagates. Use resilient sinks for production observation.
    - Will NOT observe events from nested workflows. Each workflow creates
      its own observation boundary. Cross-workflow observation requires
      explicit plumbing.

    ObservationPolicy:
    - Will NOT detect sensitive data by content. It redacts by field name only.
      A prompt in a field called "notes" will not be redacted unless you add
      "notes" to sensitive_field_names.
    - Will NOT encrypt redacted fields. Redaction replaces values with a
      placeholder string. The original data is not recoverable.
    """)


if __name__ == "__main__":
    part1_artifact_store()
    part2_promotion()
    part3_events()
    part4_observer()
    part5_redaction()
    part6_full_workflow()
    part7_boundaries()
