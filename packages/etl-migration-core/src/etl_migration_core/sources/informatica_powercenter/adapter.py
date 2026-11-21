"""Secure PowerCenter repository-export parser."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from pydantic import JsonValue

from etl_migration_core.ir import (
    AssetType,
    EtlAsset,
    EtlDependency,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    EtlPort,
    EtlSchedule,
    GraphKind,
    NodeKind,
    SourceLocation,
    SourcePlatform,
)
from etl_migration_core.sources.base import SourceMatch

MAX_EXPORT_BYTES = 100 * 1024 * 1024


class PowerCenterSourceAdapter:
    """Parse `pmrep ObjectExport` XML into canonical ETL IR."""

    adapter_id = "informatica-powercenter"
    platform = SourcePlatform.INFORMATICA_POWERCENTER
    product = "Informatica PowerCenter"
    adapter_version = "1.3.0"
    parser_version = "1.3.0"
    registry_version = "2026.11.3"
    rules_version = "1.0.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        """Recognize PowerCenter `POWERMART` XML exports."""
        if path.suffix.casefold() != ".xml" or not path.is_file():
            return None
        head = path.read_bytes()[:64_000]
        if b"<POWERMART" not in head:
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="repository_export",
            confidence=100,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Parse mappings and workflow orchestration from one repository export."""
        content = path.read_bytes()
        if len(content) > MAX_EXPORT_BYTES:
            raise ValueError("PowerCenter export exceeds the parser size limit")
        root = ElementTree.fromstring(
            content,
            forbid_dtd=False,
            forbid_entities=True,
            forbid_external=True,
        )
        if root.tag != "POWERMART":
            raise ValueError("PowerCenter export root must be POWERMART")
        repository = root.find("REPOSITORY")
        if repository is None:
            raise ValueError("PowerCenter export has no REPOSITORY")
        assets: list[EtlAsset] = []
        for folder in repository.findall("FOLDER"):
            assets.extend(_folder_assets(folder, match.display_path))
        return EtlPackage(
            source_platform=self.platform,
            source_product=self.product,
            product_version=root.get("REPOSITORY_VERSION"),
            export_id=repository.get("NAME", path.stem),
            export_version=repository.get("VERSION"),
            source_sha256=hashlib.sha256(content).hexdigest(),
            assets=tuple(assets),
        )


def _folder_assets(folder: Element, display_path: str) -> list[EtlAsset]:
    folder_name = folder.get("NAME", "")
    folder_reusables = {
        transform.get("NAME", ""): transform
        for transform in folder.findall("TRANSFORMATION")
        if transform.get("NAME")
    }
    mapplet_elements = {
        mapplet.get("NAME", ""): mapplet
        for mapplet in folder.findall("MAPPLET")
        if mapplet.get("NAME")
    }
    mapping_elements = {
        mapping.get("NAME", ""): mapping
        for mapping in folder.findall("MAPPING")
        if mapping.get("NAME")
    }
    mappings = {
        name: _mapping_graph(mapping, folder, display_path)
        for name, mapping in mapping_elements.items()
    }
    reusable_sessions = {
        session.get("NAME", ""): session.get("MAPPINGNAME", "")
        for session in folder.findall("SESSION")
    }
    reusable_session_elements = {
        session.get("NAME", ""): session
        for session in folder.findall("SESSION")
        if session.get("NAME")
    }
    schedules = {
        schedule.get("NAME", ""): EtlSchedule(
            name=schedule.get("NAME", "Schedule"),
            expression=schedule.get("SCHEDULEINFO"),
        )
        for schedule in folder.findall("SCHEDULER")
    }
    assets: list[EtlAsset] = []
    referenced_mappings: set[str] = set()
    for workflow in folder.findall("WORKFLOW"):
        sessions = {
            **reusable_sessions,
            **{
                session.get("NAME", ""): session.get("MAPPINGNAME", "")
                for session in workflow.findall("SESSION")
            },
        }
        session_elements = {
            **reusable_session_elements,
            **{
                session.get("NAME", ""): session
                for session in workflow.findall("SESSION")
                if session.get("NAME")
            },
        }
        session_variables = _session_variable_assignments(workflow)
        workflow_tasks = _workflow_task_assignments(folder, workflow)
        graph = _workflow_graph(
            workflow,
            display_path,
            sessions=sessions,
            session_variables=session_variables,
            workflow_tasks=workflow_tasks,
        )
        mapping_graphs: list[EtlGraph] = []
        dependencies: list[EtlDependency] = []
        linked_mappings: list[Element] = []
        linked_sessions: list[Element] = []
        for task in workflow.findall("TASKINSTANCE"):
            session_name = task.get("TASKNAME", "")
            mapping_name = sessions.get(session_name)
            if not mapping_name or mapping_name not in mappings:
                continue
            referenced_mappings.add(mapping_name)
            mapping_graphs.append(mappings[mapping_name])
            linked_mappings.append(mapping_elements[mapping_name])
            if session_name in session_elements:
                linked_sessions.append(session_elements[session_name])
            dependencies.append(
                EtlDependency(
                    source_native_id=workflow.get("NAME", ""),
                    target_native_id=mapping_name,
                    kind="session_mapping",
                )
            )
        schedule_name = workflow.get("SCHEDULERNAME")
        workflow_schedules = (
            (schedules[schedule_name],)
            if schedule_name is not None and schedule_name in schedules
            else ()
        )
        capacity_meta = _capacity_metadata(
            linked_mappings,
            linked_sessions,
            mapplet_elements,
            folder_reusables,
            workflow=workflow,
        )
        assets.append(
            EtlAsset(
                native_id=workflow.get("NAME", "workflow"),
                name=workflow.get("NAME", "workflow"),
                asset_type=AssetType.WORKFLOW,
                folder=folder_name,
                mapping_graphs=tuple(mapping_graphs),
                orchestration_graph=graph,
                schedules=workflow_schedules,
                dependencies=tuple(dependencies),
                source_location=SourceLocation(
                    path=display_path,
                    object_path=f"{folder_name}/{workflow.get('NAME', '')}",
                ),
                metadata={"capacity": capacity_meta},
            )
        )
    for mapping_name, graph in mappings.items():
        if mapping_name in referenced_mappings:
            continue
        capacity_meta = _capacity_metadata(
            [mapping_elements[mapping_name]],
            [],
            mapplet_elements,
            folder_reusables,
        )
        assets.append(
            EtlAsset(
                native_id=mapping_name,
                name=mapping_name,
                asset_type=AssetType.MAPPING,
                folder=folder_name,
                mapping_graphs=(graph,),
                source_location=SourceLocation(
                    path=display_path,
                    object_path=f"{folder_name}/{mapping_name}",
                ),
                metadata={"capacity": capacity_meta},
            )
        )
    return assets


def _port_direction(
    value: str,
) -> Literal["input", "output", "input_output"]:
    if value == "INPUT":
        return "input"
    if value in {"OUTPUT", "LOCAL VARIABLE"}:
        return "output"
    return "input_output"


def _mapping_graph(mapping: Element, folder: Element, display_path: str) -> EtlGraph:
    source_names = {source.get("NAME", "") for source in folder.findall("SOURCE")}
    target_names = {target.get("NAME", "") for target in folder.findall("TARGET")}
    transformations = {
        transform.get("NAME", ""): transform
        for transform in mapping.findall("TRANSFORMATION")
    }
    nodes: list[EtlNode] = []
    for instance in mapping.findall("INSTANCE"):
        identity = instance.get("NAME", "")
        instance_type = instance.get("TYPE", "")
        reference = instance.get("TRANSFORMATION_NAME", identity)
        if identity in source_names or instance_type == "SOURCE":
            kind = NodeKind.SOURCE
            operation = "source"
        elif identity in target_names or instance_type == "TARGET":
            kind = NodeKind.TARGET
            operation = "target"
        else:
            kind = NodeKind.TRANSFORMATION
            transformation = transformations.get(reference)
            native_type = (
                transformation.get("TYPE", "Transformation")
                if transformation is not None
                else instance_type
            )
            operation = native_type.casefold().replace(" ", "_")
        transformation = transformations.get(reference)
        properties: dict[str, JsonValue] = (
            {
                attribute.get("NAME", ""): attribute.get("VALUE", "")
                for attribute in transformation.findall("TABLEATTRIBUTE")
                if attribute.get("NAME")
            }
            if transformation is not None
            else {}
        )
        if transformation is not None and transformation.get("TEMPLATENAME"):
            properties["template_name"] = transformation.get("TEMPLATENAME", "")
        fields = (
            transformation.findall("TRANSFORMFIELD")
            if transformation is not None
            else []
        )
        groups = (
            transformation.findall("GROUP")
            if transformation is not None
            else []
        )
        if groups:
            properties["router_groups"] = [
                {
                    "name": group.get("NAME", ""),
                    "type": group.get("TYPE", ""),
                    "expression": group.get("EXPRESSION", ""),
                }
                for group in groups
            ]
        port_groups: dict[str, JsonValue] = {
            field.get("NAME", ""): field.get("GROUP", "") or ""
            for field in fields
            if field.get("NAME") and field.get("GROUP")
        }
        if port_groups:
            properties["port_groups"] = port_groups
        port_ref_fields: dict[str, JsonValue] = {
            field.get("NAME", ""): field.get("REF_FIELD", "") or ""
            for field in fields
            if field.get("NAME") and field.get("REF_FIELD")
        }
        if port_ref_fields:
            properties["port_ref_fields"] = port_ref_fields
        expression_types: dict[str, JsonValue] = {
            field.get("NAME", ""): field.get("EXPRESSIONTYPE", "") or ""
            for field in fields
            if field.get("NAME") and field.get("EXPRESSIONTYPE")
        }
        if expression_types:
            properties["port_expression_types"] = expression_types
        metadata_extensions: dict[str, JsonValue] = (
            {
                extension.get("NAME", ""): extension.get("VALUE", "") or ""
                for extension in transformation.findall("METADATAEXTENSION")
                if extension.get("NAME")
            }
            if transformation is not None
            else {}
        )
        if metadata_extensions:
            properties["metadata_extensions"] = metadata_extensions
        ports = (
            tuple(
                EtlPort(
                    name=field.get("NAME", ""),
                    direction=_port_direction(field.get("PORTTYPE", "")),
                    data_type=field.get("DATATYPE"),
                    expression=field.get("EXPRESSION"),
                )
                for field in fields
                if field.get("NAME")
            )
            if transformation is not None
            else ()
        )
        nodes.append(
            EtlNode(
                native_id=identity,
                name=identity,
                operation=operation,
                kind=kind,
                native_type=(
                    transformation.get("TYPE", instance_type)
                    if transformation is not None
                    else instance_type
                ),
                ports=ports,
                properties=properties,
                source_location=SourceLocation(
                    path=display_path,
                    object_path=f"MAPPING/{mapping.get('NAME', '')}/INSTANCE/{identity}",
                ),
            )
        )
    edges = tuple(
        EtlEdge(
            source=connector.get("FROMINSTANCE", ""),
            target=connector.get("TOINSTANCE", ""),
            source_port=connector.get("FROMFIELD"),
            target_port=connector.get("TOFIELD"),
        )
        for connector in mapping.findall("CONNECTOR")
    )
    return EtlGraph(kind=GraphKind.MAPPING, nodes=tuple(nodes), edges=edges)


def _workflow_task_assignments(
    folder: Element, workflow: Element
) -> dict[str, list[JsonValue]]:
    tasks: dict[str, list[JsonValue]] = {}
    for container in (folder, workflow):
        for task in container.findall("TASK"):
            name = task.get("NAME", "")
            if not name or task.get("TYPE", "").casefold() != "assignment":
                continue
            pairs: list[JsonValue] = [
                {
                    "name": pair.get("NAME", ""),
                    "value": pair.get("VALUE", ""),
                }
                for pair in task.findall("VALUEPAIR")
                if pair.get("NAME")
            ]
            if pairs:
                tasks[name] = pairs
    return tasks


def _session_variable_assignments(
    workflow: Element,
) -> dict[str, dict[str, list[JsonValue]]]:
    result: dict[str, dict[str, list[JsonValue]]] = {}
    for session in workflow.findall("SESSION"):
        name = session.get("NAME", "")
        if not name:
            continue
        pre: list[JsonValue] = []
        post: list[JsonValue] = []
        for component in session.findall("SESSIONCOMPONENT"):
            comp_type = component.get("TYPE", "").casefold()
            pairs: list[JsonValue] = [
                {
                    "name": pair.get("NAME", ""),
                    "value": pair.get("VALUE", ""),
                }
                for pair in component.findall("VALUEPAIR")
                if pair.get("NAME")
            ]
            if not pairs:
                continue
            if "pre-session" in comp_type:
                pre.extend(pairs)
            elif "post-session success" in comp_type:
                post.extend(pairs)
        if pre or post:
            result[name] = {"pre": pre, "post": post}
    return result


def _workflow_graph(
    workflow: Element,
    display_path: str,
    *,
    sessions: dict[str, str] | None = None,
    session_variables: dict[str, dict[str, list[JsonValue]]] | None = None,
    workflow_tasks: dict[str, list[JsonValue]] | None = None,
) -> EtlGraph:
    nodes_list: list[EtlNode] = []
    for task in workflow.findall("TASKINSTANCE"):
        task_instance_name = task.get("NAME", "")
        task_name = task.get("TASKNAME", "")
        task_type = task.get("TASKTYPE", "task")
        operation = task_type.casefold().replace(" ", "_")
        properties: dict[str, JsonValue] = {}
        if operation == "session" and sessions and task_name in sessions:
            properties["mapping_name"] = sessions[task_name]
            if session_variables and task_name in session_variables:
                assignments = session_variables[task_name]
                if assignments["pre"]:
                    properties["pre_assignments"] = assignments["pre"]
                if assignments["post"]:
                    properties["post_assignments"] = assignments["post"]
        elif operation == "assignment" and workflow_tasks and task_name in workflow_tasks:
            properties["assignments"] = workflow_tasks[task_name]
        nodes_list.append(
            EtlNode(
                native_id=task_instance_name,
                name=task_instance_name,
                operation=operation,
                kind=(
                    NodeKind.CONTROL
                    if task_type.casefold() in {"start", "decision"}
                    else NodeKind.TASK
                ),
                native_type=task_type,
                properties=properties,
                source_location=SourceLocation(
                    path=display_path,
                    object_path=f"WORKFLOW/{workflow.get('NAME', '')}/{task_instance_name}",
                ),
            )
        )
    nodes = tuple(nodes_list)
    edges = tuple(
        EtlEdge(
            source=link.get("FROMTASK", ""),
            target=link.get("TOTASK", ""),
            condition=link.get("CONDITION"),
        )
        for link in workflow.findall("WORKFLOWLINK")
    )
    return EtlGraph(kind=GraphKind.ORCHESTRATION, nodes=nodes, edges=edges)


def _db_key(value: str | None) -> str:
    text = (value or "").strip()
    if text.startswith("$"):
        text = text[1:]
    text = text.casefold()
    if not text or text in {"source", "target"}:
        return ""
    return text


def _capacity_metadata(
    mappings: list[Element],
    sessions: list[Element],
    mapplets: dict[str, Element],
    reusables: dict[str, Element],
    *,
    workflow: Element | None = None,
) -> dict[str, JsonValue]:
    databases: set[str] = set()
    indirect_instances: set[str] = set()
    mapplet_steps: list[JsonValue] = []

    for session in sessions:
        file_types: dict[str, str] = {}
        for ext in session.findall("SESSIONEXTENSION"):
            inst = ext.get("SINSTANCENAME", "")
            for attr in ext.findall(".//ATTRIBUTE"):
                if attr.get("NAME") == "Source filetype" and inst:
                    file_types[inst] = attr.get("VALUE", "")
            conn = ext.find("CONNECTIONREFERENCE") or ext.find(".//CONNECTIONREFERENCE")
            if conn is None:
                continue
            kind = (
                f"{conn.get('CONNECTIONTYPE', '')} {conn.get('CONNECTIONSUBTYPE', '')}"
            ).casefold()
            if "flat" in kind or "xml" in kind:
                continue
            key = _db_key(conn.get("VARIABLE") or conn.get("CONNECTIONNAME"))
            if key and any(
                token in f"{kind} {key}"
                for token in ("relational", "odbc", "oracle", "sql", "application")
            ):
                databases.add(key)
        for mapping in mappings:
            for conn in mapping.findall("CONNECTOR"):
                source_name = conn.get("FROMINSTANCE", "")
                if "indirect" in file_types.get(source_name, "").casefold():
                    indirect_instances.add(conn.get("TOINSTANCE", ""))

    def walk_mapplet(container: Element, depth: int) -> None:
        if depth > 5:
            return
        local_transforms = {
            item.get("NAME", ""): item
            for item in container.findall("TRANSFORMATION")
            if item.get("NAME")
        }
        for inst in container.findall("INSTANCE"):
            trans_type = inst.get("TRANSFORMATION_TYPE", "") or inst.get("TYPE", "")
            inst_name = inst.get("NAME", "")
            trans_name = inst.get("TRANSFORMATION_NAME", inst_name)
            if trans_type.casefold() == "mapplet":
                nested = mapplets.get(trans_name)
                if nested is not None:
                    walk_mapplet(nested, depth + 1)
                continue
            if depth == 0:
                continue
            definition = local_transforms.get(trans_name) or reusables.get(trans_name)
            native_type = (
                definition.get("TYPE", trans_type)
                if definition is not None
                else trans_type
            )
            template = (
                definition.get("TEMPLATENAME", "") if definition is not None else ""
            )
            groups: set[str] = set()
            db_key = ""
            if definition is not None:
                for field in definition.findall("TRANSFORMFIELD"):
                    if "INPUT" in (field.get("PORTTYPE") or "").upper():
                        groups.add(field.get("GROUP") or "IN")
                for attr in definition.findall("TABLEATTRIBUTE"):
                    if attr.get("NAME") == "Connection Information":
                        db_key = _db_key(attr.get("VALUE"))
                        if db_key:
                            databases.add(db_key)
            mapplet_steps.append(
                {
                    "operation": native_type.casefold().replace(" ", "_"),
                    "template_name": template,
                    "input_groups": len(groups) or 2,
                }
            )

    for mapping in mappings:
        walk_mapplet(mapping, 0)

    command_tasks = 0
    if workflow is not None:
        command_tasks = sum(
            1
            for task in workflow.findall("TASKINSTANCE")
            if (task.get("ISENABLED") or "YES").upper() != "NO"
            and (task.get("TASKTYPE") or "").casefold() == "command"
        )

    db_values: list[JsonValue] = list(sorted(databases))
    indirect_values: list[JsonValue] = list(sorted(indirect_instances))
    return {
        "databases": db_values,
        "indirect_instances": indirect_values,
        "mapplet_steps": mapplet_steps,
        "command_tasks": command_tasks,
    }
