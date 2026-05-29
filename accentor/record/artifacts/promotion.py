"""Convenience helpers for promoting generated outputs into an artifact store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import ArtifactRecord, ArtifactStore


def _store_for(store: ArtifactStore | str | Path) -> ArtifactStore:
    if isinstance(store, ArtifactStore):
        return store
    return ArtifactStore(store)


def promote_artifact(
    store: ArtifactStore | str | Path,
    source: str | Path,
    artifact_name: str | Path | None = None,
    *,
    content_type: str | None = None,
) -> ArtifactRecord:
    """Copy an existing generated file into the artifact store."""

    artifact_store = _store_for(store)
    return artifact_store.copy_file(source, artifact_name, content_type=content_type)


def promote_text_artifact(
    store: ArtifactStore | str | Path,
    artifact_name: str | Path,
    text: str,
    *,
    content_type: str = "text/plain",
) -> ArtifactRecord:
    artifact_store = _store_for(store)
    return artifact_store.write_text(artifact_name, text, content_type=content_type)


def promote_json_artifact(
    store: ArtifactStore | str | Path,
    artifact_name: str | Path,
    data: Any,
) -> ArtifactRecord:
    artifact_store = _store_for(store)
    return artifact_store.write_json(artifact_name, data)


def promote_patch(
    store: ArtifactStore | str | Path,
    patch_text: str,
    artifact_name: str | Path = "proposed_diff.patch",
) -> ArtifactRecord:
    return promote_text_artifact(
        store,
        artifact_name,
        patch_text,
        content_type="text/x-patch",
    )


def promote_validation_report(
    store: ArtifactStore | str | Path,
    report: Any,
    artifact_name: str | Path = "validation_report.json",
) -> ArtifactRecord:
    return promote_json_artifact(store, artifact_name, report)


def promote_report(
    store: ArtifactStore | str | Path,
    artifact_name: str | Path,
    report: Any,
) -> ArtifactRecord:
    return promote_json_artifact(store, artifact_name, report)
