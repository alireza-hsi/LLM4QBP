#!/usr/bin/env python3
#MAO/MAO(AiO version)/Code/Helper/duplicateHandling.py
"""
BPMN Safe-Duplicate Remover  –  fully DI-aware
================================================
Removes redundant task structures from a BPMN file and keeps the Diagram
Interchange (DI) layer — shapes, edges, and waypoints — consistent with
the process layer so any BPMN viewer renders the result correctly.

Patterns handled
----------------
1. Consecutive task chains   A → A → A → … → A  (any length ≥ 2)
   Collapsed to a single A.

2. Gateway branches where every branch contains only one task with the
   same name.  Supported gateways: parallelGateway, exclusiveGateway,
   inclusiveGateway.  Works for any number of branches (N ≥ 2).

Both patterns are run in a fixpoint loop until nothing more can be
simplified.

What "fully DI-aware" means
----------------------------
A BPMN file has two layers:

  Process layer  – <sequenceFlow sourceRef/targetRef>
                   <userTask>, <parallelGateway> …
  DI layer       – <bpmndi:BPMNShape bpmnElement="…">  ← pixel bounds
                   <bpmndi:BPMNEdge  bpmnElement="…">  ← waypoints
                   <incoming>/<outgoing> children on flow-nodes

After any structural rewrite this script:
  • Deletes BPMNShape / BPMNEdge for every removed element.
  • For every rewired sequenceFlow (one whose sourceRef or targetRef
    changed), replaces the BPMNEdge waypoints with a clean two-point
    straight line derived from the centre of the surviving shapes.
  • Rebuilds all <incoming> / <outgoing> child text nodes from scratch
    so they exactly match the surviving sequenceFlows.
"""

import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Well-known BPMN namespaces
# ---------------------------------------------------------------------------
_NS_MODEL  = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_NS_BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
_NS_DC     = "http://www.omg.org/spec/DD/20100524/DC"
_NS_DI     = "http://www.omg.org/spec/DD/20100524/DI"

# Register all prefixes so ET serialises them cleanly.
ET.register_namespace("",       _NS_MODEL)
ET.register_namespace("bpmndi", _NS_BPMNDI)
ET.register_namespace("dc",     _NS_DC)
ET.register_namespace("di",     _NS_DI)
# Also register common extra namespaces that appear in real files.
ET.register_namespace("xsi",    "http://www.w3.org/2001/XMLSchema-instance")
ET.register_namespace("camunda","http://camunda.org/schema/1.0/bpmn")
ET.register_namespace("activiti","http://activiti.org/bpmn")
ET.register_namespace("flowable","http://flowable.org/bpmn")


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _get_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}" if ns else local


# ---------------------------------------------------------------------------
# BPMN element classification
# ---------------------------------------------------------------------------

_ACTIVITY_LOCALS: Set[str] = {
    "task", "userTask", "scriptTask", "serviceTask",
    "businessRuleTask", "manualTask", "sendTask", "receiveTask",
    "subProcess", "callActivity",
}

_COLLAPSIBLE_GW_LOCALS: Set[str] = {
    "parallelGateway",
    "exclusiveGateway",
    "inclusiveGateway",
}


def _is_task(el: Optional[ET.Element]) -> bool:
    return el is not None and _local_name(el.tag) in _ACTIVITY_LOCALS


def _is_collapsible_gw(el: Optional[ET.Element]) -> bool:
    return el is not None and _local_name(el.tag) in _COLLAPSIBLE_GW_LOCALS


# ---------------------------------------------------------------------------
# Graph builder  (rebuilt after every mutation)
# ---------------------------------------------------------------------------

Elements = Dict[str, ET.Element]
FlowList = Dict[str, List[ET.Element]]


def _build_graph(root: ET.Element) -> Tuple[Elements, Elements, FlowList, FlowList]:
    elements: Elements = {}
    flows: Elements = {}
    incoming: FlowList = defaultdict(list)
    outgoing: FlowList = defaultdict(list)

    for el in root.iter():
        eid = el.get("id")
        if eid:
            elements[eid] = el
        if _local_name(el.tag) == "sequenceFlow":
            fid  = el.get("id")
            src  = el.get("sourceRef")
            tgt  = el.get("targetRef")
            if fid and src and tgt:
                flows[fid] = el
                outgoing[src].append(el)
                incoming[tgt].append(el)

    return elements, flows, incoming, outgoing


# ---------------------------------------------------------------------------
# Pattern 1 – consecutive duplicate task chains
# ---------------------------------------------------------------------------

def _dedupe_consecutive_tasks(
    elements: Elements,
    flows:    Elements,
    incoming: FlowList,
    outgoing: FlowList,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Returns (flows_to_delete, nodes_to_delete, rewired_flow_ids).

    For every chain  T0 → T1 → … → Tk  where all tasks share the same name
    and every hop is a 1-in/1-out pass-through, keep T0 and rewire the exit
    flow to originate from T0, deleting all intermediate flows and tasks.
    Handles chains of any length in one forward pass.
    """
    flows_to_delete:  Set[str] = set()
    nodes_to_delete:  Set[str] = set()
    rewired_flow_ids: Set[str] = set()
    tail_visited:     Set[str] = set()   # tasks already consumed as chain tail

    for start_id, start_el in list(elements.items()):
        if start_id in tail_visited or not _is_task(start_el):
            continue
        start_name = (start_el.get("name") or "").strip()
        if not start_name:
            continue
        if len(outgoing.get(start_id, [])) != 1:
            continue

        chain_ids:   List[str]          = [start_id]
        chain_flows: List[ET.Element]   = []
        current_id = start_id

        while True:
            outs = outgoing.get(current_id, [])
            if len(outs) != 1:
                break
            f       = outs[0]
            next_id = f.get("targetRef", "")
            next_el = elements.get(next_id)
            if not _is_task(next_el):
                break
            if (next_el.get("name") or "").strip() != start_name:
                break
            if len(incoming.get(next_id, [])) != 1:
                break
            chain_ids.append(next_id)
            chain_flows.append(f)
            current_id = next_id

        if len(chain_ids) < 2:
            continue

        last_id   = chain_ids[-1]
        last_outs = outgoing.get(last_id, [])
        if len(last_outs) == 1:
            exit_flow = last_outs[0]
            exit_flow.set("sourceRef", start_id)
            fid = exit_flow.get("id", "")
            if fid:
                rewired_flow_ids.add(fid)

        for f in chain_flows:
            fid = f.get("id", "")
            if fid:
                flows_to_delete.add(fid)
        for t_id in chain_ids[1:]:
            nodes_to_delete.add(t_id)
            tail_visited.add(t_id)

    return flows_to_delete, nodes_to_delete, rewired_flow_ids


# ---------------------------------------------------------------------------
# Pattern 2 – gateway branches all containing the same single task
# ---------------------------------------------------------------------------

def _dedupe_gateway_branches(
    elements: Elements,
    flows:    Elements,
    incoming: FlowList,
    outgoing: FlowList,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Returns (flows_to_delete, nodes_to_delete, rewired_flow_ids).

    Detects split/join pairs where every branch is a single task with the
    same name and collapses them to that one task.  Works for any number of
    branches and for parallel, exclusive, and inclusive gateways.
    """
    flows_to_delete:  Set[str] = set()
    nodes_to_delete:  Set[str] = set()
    rewired_flow_ids: Set[str] = set()

    for gw_id, gw_el in list(elements.items()):
        if gw_id in nodes_to_delete:
            continue
        if not _is_collapsible_gw(gw_el):
            continue

        gw_type    = _local_name(gw_el.tag)
        split_ins  = incoming.get(gw_id, [])
        split_outs = outgoing.get(gw_id, [])

        # Split: exactly 1 incoming, at least 2 outgoing.
        if len(split_ins) != 1 or len(split_outs) < 2:
            continue

        # Validate every branch.
        branch_task_ids: List[str] = []
        valid = True
        for f in split_outs:
            t_id = f.get("targetRef", "")
            t_el = elements.get(t_id)
            if not _is_task(t_el):
                valid = False
                break
            if len(incoming.get(t_id, [])) != 1 or len(outgoing.get(t_id, [])) != 1:
                valid = False
                break
            branch_task_ids.append(t_id)

        if not valid or len(branch_task_ids) != len(split_outs):
            continue

        # All branch tasks must share the same non-empty name.
        names = [(elements[t].get("name") or "").strip() for t in branch_task_ids]
        if not names[0] or len(set(names)) != 1:
            continue

        # All branch tasks must converge on the same join gateway.
        join_ids: Set[str] = set()
        for t_id in branch_task_ids:
            t_outs = outgoing.get(t_id, [])
            if len(t_outs) != 1:
                join_ids = set()
                break
            join_ids.add(t_outs[0].get("targetRef", ""))

        if len(join_ids) != 1:
            continue
        join_id = next(iter(join_ids))
        if not join_id:
            continue

        join_el = elements.get(join_id)
        if join_el is None or join_id in nodes_to_delete:
            continue
        if _local_name(join_el.tag) != gw_type:
            continue

        join_ins  = incoming.get(join_id, [])
        join_outs = outgoing.get(join_id, [])
        if len(join_ins) != len(branch_task_ids) or len(join_outs) != 1:
            continue

        # --- All checks passed – perform the rewrite ---
        prev_flow    = split_ins[0]   # upstream  → split
        next_flow    = join_outs[0]   # join      → downstream
        keep_task_id = branch_task_ids[0]

        prev_flow.set("targetRef", keep_task_id)
        next_flow.set("sourceRef", keep_task_id)

        pfid = prev_flow.get("id", "")
        nfid = next_flow.get("id", "")
        if pfid:
            rewired_flow_ids.add(pfid)
        if nfid:
            rewired_flow_ids.add(nfid)

        # Mark all branch flows (split→tasks and tasks→join) for deletion.
        for f in split_outs:
            fid = f.get("id", "")
            if fid:
                flows_to_delete.add(fid)
        for t_id in branch_task_ids:
            for f in outgoing.get(t_id, []):
                fid = f.get("id", "")
                if fid:
                    flows_to_delete.add(fid)

        # Mark gateways and redundant branch tasks for deletion.
        nodes_to_delete.add(gw_id)
        nodes_to_delete.add(join_id)
        nodes_to_delete.update(branch_task_ids[1:])

    flows_to_delete.discard("")
    nodes_to_delete.discard("")
    return flows_to_delete, nodes_to_delete, rewired_flow_ids


# ---------------------------------------------------------------------------
# Apply deletions to process layer
# ---------------------------------------------------------------------------

def _apply_deletions(
    root:             ET.Element,
    flows_to_delete:  Set[str],
    nodes_to_delete:  Set[str],
) -> None:
    ids_to_delete = flows_to_delete | nodes_to_delete
    if not ids_to_delete:
        return
    for parent in root.iter():
        for child in list(parent):
            cid = child.get("id")
            if cid and cid in ids_to_delete:
                parent.remove(child)


# ---------------------------------------------------------------------------
# Rebuild <incoming> / <outgoing> children on every FlowNode
# ---------------------------------------------------------------------------

def _rebuild_flow_node_refs(root: ET.Element) -> None:
    """
    Strip all <incoming>/<outgoing> children from every element and
    re-derive them from the surviving <sequenceFlow> elements.

    This handles both the stale-reference problem (rewired flows whose old
    IDs are still listed) and the missing-reference problem (newly wired
    flows that were never listed).
    """
    process_ns = _get_namespace(root.tag) or _NS_MODEL
    inc_tag = _tag(process_ns, "incoming")
    out_tag = _tag(process_ns, "outgoing")
    seq_tag = _tag(process_ns, "sequenceFlow")

    # 1. Strip all existing <incoming>/<outgoing> everywhere.
    for el in root.iter():
        for child in list(el):
            if child.tag in (inc_tag, out_tag):
                el.remove(child)

    # 2. Derive fresh maps from surviving sequenceFlows.
    node_inc: Dict[str, List[str]] = defaultdict(list)
    node_out: Dict[str, List[str]] = defaultdict(list)
    for el in root.iter():
        if el.tag != seq_tag:
            continue
        fid = el.get("id", "")
        src = el.get("sourceRef", "")
        tgt = el.get("targetRef", "")
        if fid and src:
            node_out[src].append(fid)
        if fid and tgt:
            node_inc[tgt].append(fid)

    # 3. Build id → element map.
    id_to_el: Dict[str, ET.Element] = {
        el.get("id"): el for el in root.iter() if el.get("id")
    }

    # 4. Insert fresh children.
    for nid, fids in node_inc.items():
        el = id_to_el.get(nid)
        if el is None:
            continue
        for fid in fids:
            ET.SubElement(el, inc_tag).text = fid

    for nid, fids in node_out.items():
        el = id_to_el.get(nid)
        if el is None:
            continue
        for fid in fids:
            ET.SubElement(el, out_tag).text = fid


# ---------------------------------------------------------------------------
# Synchronise the DI layer
# ---------------------------------------------------------------------------

def _sync_di(
    root:             ET.Element,
    flows_to_delete:  Set[str],
    nodes_to_delete:  Set[str],
    rewired_flow_ids: Set[str],
) -> None:
    """
    Three-step DI repair:

    Step A – Delete BPMNShape/BPMNEdge for every removed process element.
    Step B – For rewired flows recompute BPMNEdge waypoints as a clean
             straight line between the centres of the source and target
             shapes.
    Step C – Remove any BPMNEdge / BPMNShape that references an id that no
             longer exists in the process layer (defensive catch-all).
    """
    ids_to_delete = flows_to_delete | nodes_to_delete

    shape_tag    = _tag(_NS_BPMNDI, "BPMNShape")
    edge_tag     = _tag(_NS_BPMNDI, "BPMNEdge")
    bounds_tag   = _tag(_NS_DC,     "Bounds")
    waypoint_tag = _tag(_NS_DI,     "waypoint")

    # Collect the centre-point of every surviving BPMNShape.
    # (Build this BEFORE we remove anything so we can look up shapes for
    #  rewired-flow endpoints even when the shape hasn't been touched.)
    shape_centre: Dict[str, Tuple[float, float]] = {}
    for el in root.iter():
        if el.tag != shape_tag:
            continue
        bpmn_el = el.get("bpmnElement", "")
        if not bpmn_el or bpmn_el in ids_to_delete:
            continue
        bounds = el.find(bounds_tag)
        if bounds is None:
            continue
        try:
            x = float(bounds.get("x", 0))
            y = float(bounds.get("y", 0))
            w = float(bounds.get("width",  0))
            h = float(bounds.get("height", 0))
            shape_centre[bpmn_el] = (x + w / 2, y + h / 2)
        except (TypeError, ValueError):
            pass

    # Build the current id→element map for the process layer.
    surviving_ids: Set[str] = {
        el.get("id") for el in root.iter() if el.get("id")
    } - ids_to_delete

    # Build flow endpoint map (after sourceRef/targetRef have been rewritten).
    flow_endpoints: Dict[str, Tuple[str, str]] = {}
    for el in root.iter():
        if _local_name(el.tag) == "sequenceFlow":
            fid = el.get("id", "")
            src = el.get("sourceRef", "")
            tgt = el.get("targetRef", "")
            if fid and src and tgt:
                flow_endpoints[fid] = (src, tgt)

    # Walk the DI plane and act on each BPMNShape / BPMNEdge.
    for parent in root.iter():
        for child in list(parent):
            if child.tag not in (shape_tag, edge_tag):
                continue

            bpmn_el = child.get("bpmnElement", "")

            # Step A + C: remove shapes/edges for deleted or dangling elements.
            if bpmn_el in ids_to_delete or bpmn_el not in surviving_ids:
                parent.remove(child)
                continue

            # Step B: recompute waypoints for rewired edges.
            if child.tag == edge_tag and bpmn_el in rewired_flow_ids:
                endpoints = flow_endpoints.get(bpmn_el)
                if endpoints is None:
                    continue
                src_id, tgt_id = endpoints
                src_c = shape_centre.get(src_id)
                tgt_c = shape_centre.get(tgt_id)
                if src_c is None or tgt_c is None:
                    continue

                # Remove all existing waypoints.
                for wp in list(child):
                    if wp.tag == waypoint_tag:
                        child.remove(wp)

                # Insert two new waypoints (straight line between centres).
                for cx, cy in (src_c, tgt_c):
                    wp = ET.SubElement(child, waypoint_tag)
                    wp.set("x", f"{cx:.1f}")
                    wp.set("y", f"{cy:.1f}")


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def remove_safe_duplicates(
    input_file:  str,
    output_file: Optional[str] = None,
) -> str:
    """
    Load a BPMN file, remove all safe duplicate structures, and write a
    self-consistent result (process layer + DI layer both updated).

    :param input_file:  Path to the input .bpmn file.
    :param output_file: Destination path.  Defaults to ``<stem>_dedup.bpmn``.
    :return: Path to the written deduplicated BPMN file.
    """
    # Preserve the original namespace declarations by parsing with full
    # namespace context.
    tree = ET.parse(input_file)
    root = tree.getroot()

    max_iterations = 100
    for _ in range(max_iterations):
        elements, flows, incoming, outgoing = _build_graph(root)

        # ── Pass A: consecutive chain collapse ──────────────────────────
        fd_a, nd_a, rw_a = _dedupe_consecutive_tasks(
            elements, flows, incoming, outgoing
        )
        if fd_a or nd_a:
            _apply_deletions(root, fd_a, nd_a)
            _sync_di(root, fd_a, nd_a, rw_a)
            _rebuild_flow_node_refs(root)
            elements, flows, incoming, outgoing = _build_graph(root)

        # ── Pass B: gateway branch collapse ─────────────────────────────
        fd_b, nd_b, rw_b = _dedupe_gateway_branches(
            elements, flows, incoming, outgoing
        )
        if fd_b or nd_b:
            _apply_deletions(root, fd_b, nd_b)
            _sync_di(root, fd_b, nd_b, rw_b)
            _rebuild_flow_node_refs(root)

        if not fd_a and not nd_a and not fd_b and not nd_b:
            break   # fixpoint reached

    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_dedup{ext or '.bpmn'}"

    tree.write(output_file, encoding="UTF-8", xml_declaration=True)
    return output_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Remove safe duplicate patterns from a BPMN file.\n\n"
            "Patterns handled:\n"
            "  • Consecutive tasks with the same name (any chain length)\n"
            "  • Parallel / exclusive / inclusive gateway branches where\n"
            "    every branch is the same single task (any branch count)\n\n"
            "Both the process layer and the DI layer (shapes, edges,\n"
            "waypoints, incoming/outgoing refs) are kept fully consistent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input",  help="Input BPMN file path")
    parser.add_argument(
        "-o", "--output",
        help="Output BPMN file path (default: <input>_dedup.bpmn)",
        default=None,
    )
    args = parser.parse_args()

    out = remove_safe_duplicates(args.input, args.output)
    print(f"Deduplicated BPMN written to: {out}")