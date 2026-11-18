"""Bounded parser for IICS/IDMC export packages."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import JsonValue

from accelerator.etl_ir import (
    AssetType,
    EtlAsset,
    EtlDependency,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourceLocation,
    SourcePlatform,
)
from accelerator.sources.base import SourceMatch

MAX_ENTRIES = 10_000
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0


class IdmcSourceAdapter:
    """Parse offline IDMC export packages into canonical ETL IR."""

    adapter_id = "informatica-idmc"
    platform = SourcePlatform.INFORMATICA_IDMC
    product = "Informatica IDMC"
    adapter_version = "1.0.0"
    parser_version = "1.0.0"
    registry_version = "2026.11.1"
    rules_version = "1.0.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        """Recognize an extracted or zipped IDMC export package."""
        try:
            reader = _reader(path)
            manifest = reader.json("manifest.json")
        except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            return None
        if not isinstance(manifest.get("assets"), list):
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="export_package",
            confidence=100,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Parse supported mappings, mapping tasks, and taskflows."""
        reader = _reader(path)
        manifest = reader.json("manifest.json")
        assets: list[EtlAsset] = []
        for entry in _object_list(manifest.get("assets")):
            asset_path = str(entry.get("path", "")).strip("/")
            metadata = reader.json(f"{asset_path}/metadata.json")
            asset_data = reader.optional_json(f"{asset_path}/asset.json")
            assets.append(
                _asset(
                    metadata,
                    asset_data,
                    match.display_path,
                    asset_path,
                )
            )
        return EtlPackage(
            source_platform=self.platform,
            source_product=self.product,
            export_id=path.name,
            export_version=_string(manifest.get("exportVersion")),
            source_sha256=_source_hash(path),
            assets=tuple(assets),
            metadata={"organization": manifest.get("organization")},
        )


class _Reader(Protocol):
    def json(self, name: str) -> dict[str, JsonValue]:
        """Read one required JSON object."""

    def optional_json(self, name: str) -> dict[str, JsonValue]:
        """Read one optional JSON object."""


class _DirectoryReader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def json(self, name: str) -> dict[str, JsonValue]:
        path = (self.root / Path(*PurePosixPath(name).parts)).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise KeyError(name)
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError("IDMC JSON asset exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("IDMC JSON asset must be an object")
        return value

    def optional_json(self, name: str) -> dict[str, JsonValue]:
        try:
            return self.json(name)
        except KeyError:
            return {}


class _ZipReader:
    def __init__(self, path: Path) -> None:
        self.archive = zipfile.ZipFile(path)
        entries = self.archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ValueError("IDMC package exceeds the entry limit")
        total = 0
        self.names: set[str] = set()
        for entry in entries:
            member = PurePosixPath(entry.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError("IDMC package contains an unsafe path")
            if entry.file_size > MAX_JSON_BYTES and entry.filename.endswith(".json"):
                raise ValueError("IDMC JSON asset exceeds the size limit")
            if entry.compress_size == 0 and entry.file_size:
                raise ValueError("IDMC package contains an invalid compressed entry")
            if (
                entry.compress_size
                and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO
            ):
                raise ValueError("IDMC package exceeds the compression-ratio limit")
            total += entry.file_size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("IDMC package exceeds the expanded-size limit")
            self.names.add(entry.filename.rstrip("/"))

    def json(self, name: str) -> dict[str, JsonValue]:
        normalized = PurePosixPath(name).as_posix()
        if normalized not in self.names:
            raise KeyError(name)
        value = json.loads(self.archive.read(normalized).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("IDMC JSON asset must be an object")
        return value

    def optional_json(self, name: str) -> dict[str, JsonValue]:
        try:
            return self.json(name)
        except KeyError:
            return {}


def _reader(path: Path) -> _Reader:
    if path.is_dir():
        return _DirectoryReader(path)
    if path.is_file() and zipfile.is_zipfile(path):
        return _ZipReader(path)
    raise ValueError("IDMC source must be an export directory or ZIP package")


def _asset(
    metadata: dict[str, JsonValue],
    content: dict[str, JsonValue],
    display_path: str,
    asset_path: str,
) -> EtlAsset:
    native_type = _string(metadata.get("type")) or "UNKNOWN"
    asset_type = {
        "DTEMPLATE": AssetType.MAPPING,
        "MTT": AssetType.MAPPING_TASK,
        "TASKFLOW": AssetType.TASKFLOW,
    }.get(native_type, AssetType.UNKNOWN)
    native_id = _string(metadata.get("id")) or asset_path
    name = _string(metadata.get("name")) or Path(asset_path).stem
    mapping_graphs: tuple[EtlGraph, ...] = ()
    orchestration_graph: EtlGraph | None = None
    dependencies: tuple[EtlDependency, ...] = ()
    if asset_type is AssetType.MAPPING:
        mapping_graphs = (_mapping_graph(content, display_path, asset_path),)
    elif asset_type is AssetType.TASKFLOW:
        orchestration_graph = _taskflow_graph(content, display_path, asset_path)
    elif asset_type is AssetType.MAPPING_TASK:
        mapping_id = _string(metadata.get("mappingId"))
        if mapping_id:
            dependencies = (
                EtlDependency(
                    source_native_id=native_id,
                    target_native_id=mapping_id,
                    kind="mapping_task_mapping",
                ),
            )
    return EtlAsset(
        native_id=native_id,
        name=name,
        asset_type=asset_type,
        folder=_string(metadata.get("path")),
        mapping_graphs=mapping_graphs,
        orchestration_graph=orchestration_graph,
        dependencies=dependencies,
        source_location=SourceLocation(path=display_path, object_path=asset_path),
        metadata={"native_type": native_type},
    )


def _mapping_graph(
    content: dict[str, JsonValue],
    display_path: str,
    asset_path: str,
) -> EtlGraph:
    nodes = tuple(
        _idmc_node(value, display_path, asset_path)
        for value in _object_list(content.get("transformations"))
    )
    edges = tuple(
        EtlEdge(
            source=_string(value.get("from")),
            target=_string(value.get("to")),
        )
        for value in _object_list(content.get("links"))
    )
    return EtlGraph(kind=GraphKind.MAPPING, nodes=nodes, edges=edges)


def _taskflow_graph(
    content: dict[str, JsonValue],
    display_path: str,
    asset_path: str,
) -> EtlGraph:
    nodes = tuple(
        EtlNode(
            native_id=_string(value.get("id")),
            name=_string(value.get("name")),
            operation=_string(value.get("type")).casefold().replace(" ", "_"),
            kind=(
                NodeKind.CONTROL
                if _string(value.get("type")).casefold() in {"start", "decision", "end"}
                else NodeKind.TASK
            ),
            native_type=_string(value.get("type")),
            properties={
                key: item
                for key, item in value.items()
                if key not in {"id", "name", "type"}
            },
            source_location=SourceLocation(
                path=display_path,
                object_path=f"{asset_path}/{_string(value.get('id'))}",
            ),
        )
        for value in _object_list(content.get("steps"))
    )
    edges = tuple(
        EtlEdge(
            source=_string(value.get("from")),
            target=_string(value.get("to")),
            condition=_string(value.get("condition")) or None,
        )
        for value in _object_list(content.get("links"))
    )
    return EtlGraph(kind=GraphKind.ORCHESTRATION, nodes=nodes, edges=edges)


def _idmc_node(
    value: dict[str, JsonValue],
    display_path: str,
    asset_path: str,
) -> EtlNode:
    native_type = _string(value.get("type"))
    normalized = native_type.casefold().replace(" ", "_")
    if normalized == "source":
        kind = NodeKind.SOURCE
    elif normalized == "target":
        kind = NodeKind.TARGET
    else:
        kind = NodeKind.TRANSFORMATION
    identity = _string(value.get("id"))
    return EtlNode(
        native_id=identity,
        name=_string(value.get("name")) or identity,
        operation=normalized or "unknown",
        kind=kind,
        native_type=native_type or None,
        properties={
            key: item
            for key, item in value.items()
            if key not in {"id", "name", "type"}
        },
        source_location=SourceLocation(
            path=display_path,
            object_path=f"{asset_path}/{identity}",
        ),
    )


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    for child in sorted(path.rglob("*"), key=lambda item: str(item).casefold()):
        if not child.is_file():
            continue
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _string(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _object_list(value: JsonValue) -> tuple[dict[str, JsonValue], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))
