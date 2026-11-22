"""Synthetic, metadata-only SSIS adapter example."""

import hashlib
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    AssetType,
    EtlAsset,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourceLocation,
)
from etl_migration_core.sources.base import SourceMatch

_DTS = "{www.microsoft.com/SqlServer/Dts}"
_MAX_BYTES = 5 * 1024 * 1024


def _read_package(path: Path) -> tuple[Element, str]:
    if path.is_symlink():
        raise ValueError("Linked SSIS files are not accepted")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("Synthetic SSIS file exceeds the 5 MiB limit")
    with path.open("rb") as stream:
        content = stream.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise ValueError("Synthetic SSIS file exceeds the 5 MiB limit")
    try:
        root = ElementTree.fromstring(
            content, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ParseError, DefusedXmlException) as error:
        raise ValueError("Invalid or unsafe synthetic SSIS XML") from error
    return root, hashlib.sha256(content).hexdigest()


def _identity(element: Element) -> tuple[str, str]:
    native_id = element.get(f"{_DTS}DTSID", "").strip()
    name = element.get(f"{_DTS}ObjectName", "").strip()
    if not native_id or not name:
        raise ValueError("Synthetic SSIS executables require DTSID and ObjectName")
    return native_id, name


class SyntheticSsisAdapter:
    """Extract synthetic package and task identities without interpreting semantics."""

    adapter_id = "synthetic-ssis"
    supported_extensions = (".dtsx",)
    platform = "ssis"
    product = "Synthetic SSIS example"
    adapter_version = "0.1.0"
    parser_version = "0.1.0"
    registry_version = "0.1.0"
    rules_version = "0.1.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        if path.suffix.casefold() != ".dtsx" or not path.is_file():
            return None
        root, _ = _read_package(path)
        if root.tag != f"{_DTS}Executable" or root.get(f"{_DTS}ExecutableType") != "SSIS.Package.2":
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="workflow",
            confidence=100,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        root, digest = _read_package(path)
        if root.tag != f"{_DTS}Executable" or root.get(f"{_DTS}ExecutableType") != "SSIS.Package.2":
            raise ValueError("Unsupported synthetic SSIS package root")
        package_id, package_name = _identity(root)
        nodes: list[EtlNode] = []
        for element in root.iter(f"{_DTS}Executable"):
            if len(nodes) >= 10_000:
                raise ValueError("Synthetic SSIS package exceeds the executable limit")
            native_id, name = _identity(element)
            nodes.append(
                EtlNode(
                    native_id=native_id,
                    name=name,
                    operation="ssis_unverified_task",
                    kind=NodeKind.TASK,
                    native_type=element.get(f"{_DTS}ExecutableType"),
                    issues=("Synthetic example does not assess SSIS semantics.",),
                    source_location=SourceLocation(path=match.display_path),
                )
            )
        asset = EtlAsset(
            native_id=package_id,
            name=package_name,
            asset_type=AssetType.WORKFLOW,
            orchestration_graph=EtlGraph(kind=GraphKind.ORCHESTRATION, nodes=tuple(nodes)),
            source_location=SourceLocation(path=match.display_path),
        )
        return EtlPackage(
            ir_version=EXTENSIBLE_SOURCE_IR_VERSION,
            source_platform=self.platform,
            source_product=self.product,
            export_id=match.display_path,
            source_sha256=digest,
            assets=(asset,),
        )
