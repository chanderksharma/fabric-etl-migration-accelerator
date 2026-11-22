"""Validated repository location and manifest hash for a publication dispatch."""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicationDispatch:
    """Remote location and exact manifest bytes expected by a trusted CI definition."""

    artifact_root: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"published-fabric-workflows/[0-9a-f]{32}/[0-9a-f]{64}",
            self.artifact_root,
        ):
            raise ValueError("Invalid publication repository path")
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest_sha256):
            raise ValueError("Invalid publication manifest hash")
