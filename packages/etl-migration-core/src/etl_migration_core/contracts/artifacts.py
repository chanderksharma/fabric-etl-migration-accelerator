"""Target-neutral generated-artifact projection.

A platform writer owns file bytes. This contract carries identity, state, and
diagnostics so a second platform can be added without reading Fabric paths.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ArtifactFile(BaseModel):
    """One generated file. The Candidate projection leaves this collection empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = Field(default="text/plain", min_length=1, max_length=128)


class ArtifactSet(BaseModel):
    """One workflow's generated artifacts for one target kind, without a disk tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str = Field(min_length=1, max_length=64)
    target_kind: str = Field(min_length=1, max_length=64)
    workflow: str = Field(min_length=1, max_length=512)
    validation_state: Literal["blocked", "generated_unvalidated", "scaffold"]
    translation_mode: Literal["native", "scaffold"] = "native"
    deployable: bool = False
    files: tuple[ArtifactFile, ...] = ()
    diagnostics: tuple[str, ...] = ()
    required_bindings: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
