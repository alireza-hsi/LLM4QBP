#!/usr/bin/env python3
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional


def _get_namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


_ACTIVITY_TAGS = {
    "task",
    "userTask",
    "scriptTask",
    "serviceTask",
    "businessRuleTask",
    "manualTask",
    "sendTask",
    "receiveTask",
    "subProcess",
    "callActivity",
}


def _build_graph(root: ET.Element, ns: str):
    """Build helper maps for elements and sequence flows."""
    elements: Dict[str, ET.Element] = {}
    flows: Dict[str, ET.Element] = {}
    incoming: Dict[str, List[ET.Element]] = defaultdict(list)
    outgoing: Dict[str, List[ET.Element]] = defaultdict(list)
    flow_parents: Dict[str, ET.Element] = {}
    node_parents: Dict[str, ET.Element] = {}

    seq_tag = f"{{{ns}}}sequenceFlow" if ns else "sequenceFlow"

    # Track parents for all elements with ids (nodes + flows)
    for parent in root.iter():
        for child in list(parent):
            cid = child.get("id")
            if cid:
                node_parents[cid] = parent
            if child.tag == seq_tag:
                fid = child.get("id")
                if not fid:
                    continue
                flow_parents[fid] = parent

    # Map all elements by id
    for el in root.iter():
        eid = el.get("id")
        if eid:
            elements[eid] = el

    # Map sequence flows and adjacency
    for fid, parent in flow_parents.items():
        flow = None
        for child in parent:
            if child.get("id") == fid:
                flow = child
                break
        if flow is None:
            continue
        src = flow.get("sourceRef")
        tgt = flow.get("targetRef")
        if not src or not tgt:
            continue
        flows[fid] = flow
        outgoing[src].append(flow)
        incoming[tgt].append(flow)

    return elements, flows, incoming, outgoing, flow_parents, node_parents


def _is_task(el: Optional[ET.Element]) -> bool:
    if el is None:
        return False
    return _local_name(el.tag) in _ACTIVITY_TAGS


def _is_parallel_gateway(el: Optional[ET.Element]) -> bool:
    if el is None:
        return False
    return _local_name(el.tag) == "parallelGateway"


def _dedupe_consecutive_tasks(
    root: ET.Element,
    ns: str,
    elements: Dict[str, ET.Element],
    flows: Dict[str, ET.Element],
    incoming: Dict[str, List[ET.Element]],
    outgoing: Dict[str, List[ET.Element]],
) -> Tuple[Set[str], Set[str]]:
    """
    Collapse simple chains of consecutive tasks with the same name:
    A -> A  (both plain tasks, single in/out)  →  single A.
    """
    flows_to_delete: Set[str] = set()
    nodes_to_delete: Set[str] = set()

    for fid, flow in list(flows.items()):
        src_id = flow.get("sourceRef")
        tgt_id = flow.get("targetRef")
        if not src_id or not tgt_id:
            continue

        src_el = elements.get(src_id)
        tgt_el = elements.get(tgt_id)
        if not (_is_task(src_el) and _is_task(tgt_el)):
            continue

        src_name = (src_el.get("name") or "").strip()
        tgt_name = (tgt_el.get("name") or "").strip()
        if not src_name or src_name != tgt_name:
            continue

        # Safe-only case: each has exactly one incoming/outgoing in the chain
        if len(outgoing.get(src_id, [])) != 1:
            continue
        if len(incoming.get(tgt_id, [])) != 1:
            continue

        # Rewire all outgoing flows of the target to originate from the source.
        for f2 in list(outgoing.get(tgt_id, [])):
            f2.set("sourceRef", src_id)
            outgoing[src_id].append(f2)
            incoming[f2.get("targetRef", "")] = [
                f if f is not flow else f2 for f in incoming.get(f2.get("targetRef", ""), [])
            ]

        # Mark the intermediate flow and duplicate task for deletion.
        flows_to_delete.add(fid)
        nodes_to_delete.add(tgt_id)

    return flows_to_delete, nodes_to_delete


def _dedupe_parallel_duplicate_branches(
    root: ET.Element,
    ns: str,
    elements: Dict[str, ET.Element],
    flows: Dict[str, ET.Element],
    incoming: Dict[str, List[ET.Element]],
    outgoing: Dict[str, List[ET.Element]],
) -> Tuple[Set[str], Set[str]]:
    """
    Collapse simple parallel structures where a parallel split and join
    surround two identical one-activity branches:

        prev → [ParallelGateway(split)]
                ↘ T(name=X) →   ↘
                ↗ T(name=X) ←   ↙
              [ParallelGateway(join)] → next

    becomes:

        prev → T(name=X) → next
    """
    flows_to_delete: Set[str] = set()
    nodes_to_delete: Set[str] = set()

    for gw_id, gw_el in list(elements.items()):
        if gw_id in nodes_to_delete:
            continue
        if not _is_parallel_gateway(gw_el):
            continue

        outs = outgoing.get(gw_id, [])
        ins = incoming.get(gw_id, [])

        # Candidate split: exactly one incoming, two outgoing.
        if len(ins) != 1 or len(outs) != 2:
            continue

        # Collect branch tasks
        branch_tasks: List[str] = []
        for f in outs:
            t_id = f.get("targetRef")
            t_el = elements.get(t_id or "")
            if not _is_task(t_el):
                break
            # Each branch task must be a simple pass-through (1 in, 1 out)
            if len(incoming.get(t_id, [])) != 1 or len(outgoing.get(t_id, [])) != 1:
                break
            branch_tasks.append(t_id or "")
        else:
            # Only accept if we got exactly two branch tasks.
            if len(branch_tasks) != 2:
                continue

            t1_id, t2_id = branch_tasks
            t1_el = elements.get(t1_id)
            t2_el = elements.get(t2_id)
            if not t1_el or not t2_el:
                continue
            n1 = (t1_el.get("name") or "").strip()
            n2 = (t2_el.get("name") or "").strip()
            if not n1 or n1 != n2:
                continue

            # Both tasks should lead into the same parallel join gateway.
            t1_out = outgoing.get(t1_id, [None])[0]
            t2_out = outgoing.get(t2_id, [None])[0]
            if t1_out is None or t2_out is None:
                continue
            join_id = t1_out.get("targetRef")
            if not join_id or join_id != t2_out.get("targetRef"):
                continue

            join_el = elements.get(join_id)
            if not _is_parallel_gateway(join_el):
                continue

            join_ins = incoming.get(join_id, [])
            join_outs = outgoing.get(join_id, [])
            if len(join_ins) != 2 or len(join_outs) != 1:
                continue

            # At this point we have the simple pattern. Perform the rewrite.
            in_to_split = ins[0]  # prev → split
            join_out = join_outs[0]  # join → next
            prev_id = in_to_split.get("sourceRef")
            next_id = join_out.get("targetRef")
            if not prev_id or not next_id:
                continue

            # Choose one task to keep, remove the other.
            keep_task_id = t1_id
            remove_task_id = t2_id

            # prev → keep_task
            in_to_split.set("targetRef", keep_task_id)

            # keep_task → next
            join_out.set("sourceRef", keep_task_id)

            # Mark flows in the parallel structure for deletion:
            #   split → tasks, tasks → join
            for f in outs:
                flows_to_delete.add(f.get("id", ""))
            for f in join_ins:
                flows_to_delete.add(f.get("id", ""))

            # Remove gateways and the redundant branch task.
            nodes_to_delete.update({gw_id, join_id, remove_task_id})

    # Clean any empty ids accidentally added
    flows_to_delete.discard("")
    nodes_to_delete.discard("")
    return flows_to_delete, nodes_to_delete


def _apply_deletions(
    root: ET.Element,
    flows_to_delete: Set[str],
    nodes_to_delete: Set[str],
) -> None:
    """Remove all elements whose ids are in the provided sets."""
    if not flows_to_delete and not nodes_to_delete:
        return

    ids_to_delete = set(flows_to_delete) | set(nodes_to_delete)
    if not ids_to_delete:
        return

    # Walk the tree and remove matching children from their parents.
    for parent in root.iter():
        children = list(parent)
        for child in children:
            cid = child.get("id")
            if cid and cid in ids_to_delete:
                parent.remove(child)


def remove_safe_duplicates(input_file: str, output_file: Optional[str] = None) -> str:
    """
    Load a BPMN file, remove "safe" duplicate structures, and write the result.

    Currently handled patterns:
    - Consecutive tasks with the same name (A → A) when both are simple pass-through tasks.
    - Simple parallel split/join with two identical one-task branches.

    :param input_file: Path to input .bpmn file.
    :param output_file: Where to write the cleaned BPMN.
                         If None, a new file path is derived by appending '_dedup'.
    :return: Path to the written deduplicated BPMN file.
    """
    tree = ET.parse(input_file)
    root = tree.getroot()
    ns = _get_namespace(root.tag)

    elements, flows, incoming, outgoing, _, _ = _build_graph(root, ns)

    # 1) Collapse consecutive duplicates.
    f_del_1, n_del_1 = _dedupe_consecutive_tasks(root, ns, elements, flows, incoming, outgoing)

    # Rebuild graph after first pass, since ids/flows may have changed.
    if f_del_1 or n_del_1:
        _apply_deletions(root, f_del_1, n_del_1)
        elements, flows, incoming, outgoing, _, _ = _build_graph(root, ns)

    # 2) Collapse simple parallel duplicate branches.
    f_del_2, n_del_2 = _dedupe_parallel_duplicate_branches(
        root, ns, elements, flows, incoming, outgoing
    )
    if f_del_2 or n_del_2:
        _apply_deletions(root, f_del_2, n_del_2)

    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_dedup{ext or '.bpmn'}"

    tree.write(output_file, encoding="UTF-8", xml_declaration=True)
    return output_file


if __name__ == "__main__":
    # Simple manual CLI for experimentation.
    import argparse

    parser = argparse.ArgumentParser(description="Remove safe duplicate patterns from a BPMN file.")
    parser.add_argument("input", help="Input BPMN file path")
    parser.add_argument(
        "-o",
        "--output",
        help="Output BPMN file path (default: <input>_dedup.bpmn)",
        default=None,
    )
    args = parser.parse_args()

    out_path = remove_safe_duplicates(args.input, args.output)
    print(f"Deduplicated BPMN written to: {out_path}")

