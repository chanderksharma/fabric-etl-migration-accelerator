"""Versioned, source-neutral intermediate representation for ETL metadata."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

IR_VERSION = "1.0.0"


class SourcePlatform(StrEnum):
    """Supported source platforms."""

    ALTERYX = "alteryx"
    INFORMATICA_POWERCENTER = "informatica_powercenter"
    INFORMATICA_IDMC = "informatica_idmc"


class AssetType(StrEnum):
    """Normalized ETL asset types."""

    WORKFLOW = "workflow"
    MAPPING = "mapping"
    MAPPLET = "mapplet"
    SESSION = "session"
    WORKLET = "worklet"
    MAPPING_TASK = "mapping_task"
    TASKFLOW = "taskflow"
    CONNECTION = "connection"
    SCHEDULE = "schedule"
    UNKNOWN = "unknown"


class GraphKind(StrEnum):
    """Semantic graph layers kept separate in the IR."""

    MAPPING = "mapping"
    ORCHESTRATION = "orchestration"


class NodeKind(StrEnum):
    """Normalized graph node roles."""

    SOURCE = "source"
    TARGET = "target"
    TRANSFORMATION = "transformation"
    TASK = "task"
    CONTROL = "control"
    CONTAINER = "container"
    ANNOTATION = "annotation"
    UNKNOWN = "unknown"


class IrModel(BaseModel):
    """Strict immutable base model for all IR records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceLocation(IrModel):
    """Traceability location inside a native export."""

    path: str = Field(min_length=1, max_length=4096)
    object_path: str | None = Field(default=None, max_length=4096)
    line: int | None = Field(default=None, ge=1)


class EtlPort(IrModel):
    """Input or output port on a mapping node."""

    name: str = Field(min_length=1, max_length=512)
    direction: Literal["input", "output", "input_output"]
    data_type: str | None = Field(default=None, max_length=256)
    nullable: bool | None = None
    ordinal: int | None = Field(default=None, ge=0)
    expression: str | None = Field(default=None, max_length=16_384)


class EtlNode(IrModel):
    """One normalized mapping transformation or orchestration task."""

    native_id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)
    operation: str = Field(min_length=1, max_length=256)
    kind: NodeKind
    native_type: str | None = Field(default=None, max_length=512)
    label: str = Field(default="", max_length=512)
    disabled: bool = False
    ports: tuple[EtlPort, ...] = Field(default=(), max_length=4096)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    issues: tuple[str, ...] = Field(default=(), max_length=100)
    source_location: SourceLocation | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)


class EtlEdge(IrModel):
    """Directed dependency between two normalized nodes."""

    source: str = Field(min_length=1, max_length=512)
    target: str = Field(min_length=1, max_length=512)
    source_port: str | None = Field(default=None, max_length=512)
    target_port: str | None = Field(default=None, max_length=512)
    condition: str | None = Field(default=None, max_length=16_384)
    order: int | None = Field(default=None, ge=0)


class EtlContainer(IrModel):
    """Logical source-system grouping for graph members."""

    native_id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)
    parent_id: str | None = Field(default=None, max_length=512)
    member_ids: tuple[str, ...] = Field(default=(), max_length=10_000)
    description: str | None = Field(default=None, max_length=4096)


class EtlGraph(IrModel):
    """Validated mapping or orchestration graph."""

    kind: GraphKind
    nodes: tuple[EtlNode, ...] = Field(default=(), max_length=10_000)
    edges: tuple[EtlEdge, ...] = Field(default=(), max_length=20_000)
    containers: tuple[EtlContainer, ...] = Field(default=(), max_length=1_000)

    @model_validator(mode="after")
    def validate_references(self) -> EtlGraph:
        """Reject ambiguous identities and dangling graph references."""
        node_ids = [node.native_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate node identity in ETL graph")
        known_nodes = set(node_ids)
        for edge in self.edges:
            if edge.source not in known_nodes or edge.target not in known_nodes:
                raise ValueError("edge references an unknown node")

        container_ids = [container.native_id for container in self.containers]
        if len(container_ids) != len(set(container_ids)):
            raise ValueError("duplicate container identity in ETL graph")
        known_containers = set(container_ids)
        parents: dict[str, str] = {}
        for container in self.containers:
            unknown_members = set(container.member_ids) - known_nodes
            if unknown_members:
                raise ValueError("container references an unknown node")
            if container.parent_id is not None:
                if container.parent_id not in known_containers:
                    raise ValueError("container references an unknown parent")
                if container.parent_id == container.native_id:
                    raise ValueError("container cannot be its own parent")
                parents[container.native_id] = container.parent_id
        for identity in parents:
            visited: set[str] = set()
            current = identity
            while current in parents:
                if current in visited:
                    raise ValueError("container hierarchy contains a cycle")
                visited.add(current)
                current = parents[current]
        return self


class EtlParameter(IrModel):
    """Normalized workflow, mapping, or task parameter."""

    name: str = Field(min_length=1, max_length=512)
    data_type: str | None = Field(default=None, max_length=256)
    default_value: JsonValue = None
    required: bool = False
    scope: str | None = Field(default=None, max_length=512)


class EtlSchedule(IrModel):
    """Normalized source-system schedule."""

    name: str = Field(min_length=1, max_length=512)
    expression: str | None = Field(default=None, max_length=4096)
    enabled: bool = True
    time_zone: str | None = Field(default=None, max_length=128)


class EtlDependency(IrModel):
    """Reference from one native asset to another."""

    source_native_id: str = Field(min_length=1, max_length=512)
    target_native_id: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=256)


class EtlConnectionRef(IrModel):
    """Credential-free reference to an external source or destination."""

    native_id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=256)
    path: str | None = Field(default=None, max_length=4096)
    properties: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("properties")
    @classmethod
    def reject_credentials(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Prevent adapters from persisting credential-bearing properties."""
        markers = ("password", "pwd", "secret", "token", "credential", "accountkey")
        for key in value:
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if any(marker in normalized for marker in markers):
                raise ValueError(
                    "credential properties are not allowed in ETL connection references"
                )
        return value


class EtlAsset(IrModel):
    """One normalized source-system asset."""

    native_id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)
    asset_type: AssetType
    folder: str | None = Field(default=None, max_length=4096)
    description: str | None = Field(default=None, max_length=8192)
    mapping_graphs: tuple[EtlGraph, ...] = Field(default=(), max_length=1_000)
    orchestration_graph: EtlGraph | None = None
    parameters: tuple[EtlParameter, ...] = Field(default=(), max_length=1_000)
    schedules: tuple[EtlSchedule, ...] = Field(default=(), max_length=100)
    connections: tuple[EtlConnectionRef, ...] = Field(default=(), max_length=1_000)
    dependencies: tuple[EtlDependency, ...] = Field(default=(), max_length=10_000)
    source_location: SourceLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_kinds(self) -> EtlAsset:
        """Keep data-mapping and orchestration semantics in separate graphs."""
        if any(graph.kind is not GraphKind.MAPPING for graph in self.mapping_graphs):
            raise ValueError("mapping_graphs can contain only mapping graphs")
        if (
            self.orchestration_graph is not None
            and self.orchestration_graph.kind is not GraphKind.ORCHESTRATION
        ):
            raise ValueError("orchestration_graph must be an orchestration graph")
        return self


class EtlPackage(IrModel):
    """Canonical representation of one source export or workflow package."""

    ir_version: str = IR_VERSION
    source_platform: SourcePlatform
    source_product: str = Field(min_length=1, max_length=256)
    product_version: str | None = Field(default=None, max_length=128)
    export_id: str = Field(min_length=1, max_length=512)
    export_version: str | None = Field(default=None, max_length=128)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    assets: tuple[EtlAsset, ...] = Field(default=(), max_length=10_000)
    connections: tuple[EtlConnectionRef, ...] = Field(default=(), max_length=10_000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_asset_identities(self) -> EtlPackage:
        """Reject duplicate asset identities inside one export."""
        identities = [asset.native_id for asset in self.assets]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate asset identity in ETL package")
        return self

