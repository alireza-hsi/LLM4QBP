import xml.etree.ElementTree as ET
import argparse
import re

# ----------------------------
# Namespaces
# ----------------------------
BPMN   = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
OMGDC  = "http://www.omg.org/spec/DD/20100524/DC"
OMGDI  = "http://www.omg.org/spec/DD/20100524/DI"
XSI    = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("bpmn",   BPMN)
ET.register_namespace("bpmndi", BPMNDI)
ET.register_namespace("omgdc",  OMGDC)
ET.register_namespace("omgdi",  OMGDI)
ET.register_namespace("xsi",    XSI)

# ----------------------------
# Global counter for sequence flow IDs
# ----------------------------
flow_counter = 1
def new_flow_id():
    global flow_counter
    fid = f"Flow_{flow_counter}"
    flow_counter += 1
    return fid

# ----------------------------
# Converters
# ----------------------------
def process_activity(elem):
    """
    Convert an <activity> element from the input BPMN text to a BPMN task.
    Returns (entry_id, exit_id, list_of_task_elements, list_of_sequenceFlows).
    """
    act_id = elem.attrib.get('id')
    role = elem.attrib.get('role')
    action = elem.attrib.get('action')
    objects = elem.attrib.get('objects', '')
    if objects.strip():
        name = f"{action} (Role: {role}; Objects: {objects})"
    else:
        name = f"{action} (Role: {role})"
    task = ET.Element(f"{{{BPMN}}}task", id=act_id, name=name)
    return (act_id, act_id, [task], [])

def process_branch(elem):
    """
    Process a <branch> element – if the branch contains multiple activities,
    insert a dummy connector at the start. Returns (branch_entry, branch_exit, nodes, flows)
    """
    nodes = []
    flows = []
    children = list(elem)

    if len(children) > 1:
        dummy_id = "dummy_" + new_flow_id()
        dummy = ET.Element(f"{{{BPMN}}}task", id=dummy_id, name="(dummy branch entry)")
        nodes.append(dummy)
        branch_entry = dummy_id
        prev_exit = dummy_id
    else:
        branch_entry = None
        prev_exit = None

    for child in children:
        s, e, n, f = process_element(child)
        nodes.extend(n)
        flows.extend(f)
        if s is None or e is None:
            continue
        if branch_entry is None:
            branch_entry = s
        if prev_exit is not None:
            sf = ET.Element(f"{{{BPMN}}}sequenceFlow",
                            id=new_flow_id(), sourceRef=prev_exit, targetRef=s)
            flows.append(sf)
        prev_exit = e
    return (branch_entry, prev_exit, nodes, flows)

def process_parallel_gateway(elem):
    """
    <parallelGateway> with one or more <branch> children.
    Returns (diverge_id, converge_id, nodes, flows)
    """
    pg_id = elem.attrib.get('id')
    diverge = ET.Element(f"{{{BPMN}}}parallelGateway", id=pg_id, name="Parallel Gateway")
    nodes = [diverge]
    flows = []
    branch_entries = []
    branch_exits = []
    for branch in elem.findall('branch'):
        s, e, n, f = process_branch(branch)
        nodes.extend(n)
        flows.extend(f)
        branch_entries.append(s)
        branch_exits.append(e)
    converge_id = pg_id + "Join"
    converge = ET.Element(f"{{{BPMN}}}parallelGateway", id=converge_id, name="Parallel Merge")
    nodes.append(converge)
    for s in branch_entries:
        if s is None:  # defensive
            continue
        sf = ET.Element(f"{{{BPMN}}}sequenceFlow",
                        id=new_flow_id(), sourceRef=pg_id, targetRef=s)
        flows.append(sf)
    for e in branch_exits:
        if e is None:
            continue
        sf = ET.Element(f"{{{BPMN}}}sequenceFlow",
                        id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf)
    return (pg_id, converge_id, nodes, flows)

def _add_condition(flow_elem, text):
    """Attach a proper <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">"""
    flow_elem.attrib["name"] = text
    ce = ET.Element(f"{{{BPMN}}}conditionExpression", attrib={f"{{{XSI}}}type": "bpmn:tFormalExpression"})
    ce.text = text
    flow_elem.append(ce)

def process_inclusive_gateway(elem):
    """
    <inclusiveGateway> with <branch condition='...'> children.
    """
    ig_id = elem.attrib.get('id')
    diverge = ET.Element(f"{{{BPMN}}}inclusiveGateway", id=ig_id, name="Inclusive Gateway")
    nodes = [diverge]
    flows = []
    branch_info = []
    for branch in elem.findall('branch'):
        s, e, n, f = process_branch(branch)
        nodes.extend(n)
        flows.extend(f)
        condition = branch.attrib.get('condition', '').strip()
        branch_info.append((s, e, condition))
    converge_id = ig_id + "Join"
    converge = ET.Element(f"{{{BPMN}}}inclusiveGateway", id=converge_id, name="Inclusive Merge")
    nodes.append(converge)
    for (s, e, cond) in branch_info:
        if s is None or e is None:
            continue
        sf = ET.Element(f"{{{BPMN}}}sequenceFlow", id=new_flow_id(), sourceRef=ig_id, targetRef=s)
        if cond:
            _add_condition(sf, cond)
        flows.append(sf)
        sf2 = ET.Element(f"{{{BPMN}}}sequenceFlow", id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf2)
    return (ig_id, converge_id, nodes, flows)

def process_exclusive_gateway(elem):
    """
    <exclusiveGateway> with <branch condition='...'> children.
    """
    eg_id = elem.attrib.get('id')
    diverge = ET.Element(f"{{{BPMN}}}exclusiveGateway", id=eg_id, name="Exclusive Gateway")
    nodes = [diverge]
    flows = []
    branch_info = []
    for branch in elem.findall('branch'):
        s, e, n, f = process_branch(branch)
        nodes.extend(n)
        flows.extend(f)
        condition = branch.attrib.get('condition', '').strip()
        branch_info.append((s, e, condition))
    converge_id = eg_id + "Join"
    converge = ET.Element(f"{{{BPMN}}}exclusiveGateway", id=converge_id, name="Exclusive Merge")
    nodes.append(converge)
    for (s, e, cond) in branch_info:
        if s is None or e is None:
            continue
        sf = ET.Element(f"{{{BPMN}}}sequenceFlow", id=new_flow_id(), sourceRef=eg_id, targetRef=s)
        if cond:
            _add_condition(sf, cond)
        flows.append(sf)
        sf2 = ET.Element(f"{{{BPMN}}}sequenceFlow", id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf2)
    return (eg_id, converge_id, nodes, flows)

def process_element(elem):
    """
    Determine the element type and process accordingly.
    Returns (entry_id, exit_id, list_of_BPMN_nodes, list_of_sequenceFlows)
    """
    tag = elem.tag
    if tag == "activity":
        return process_activity(elem)
    elif tag == "parallelGateway":
        return process_parallel_gateway(elem)
    elif tag == "inclusiveGateway":
        return process_inclusive_gateway(elem)
    elif tag == "exclusiveGateway":
        return process_exclusive_gateway(elem)
    elif tag == "branch":
        return process_branch(elem)
    else:
        return (None, None, [], [])

# ----------------------------
# Wiring helpers
# ----------------------------
def add_flow_references(process_elem, seq_flow):
    """
    For each sequenceFlow, add <incoming> to target and <outgoing> to source.
    """
    ns = f"{{{BPMN}}}"
    source_id = seq_flow.attrib["sourceRef"]
    target_id = seq_flow.attrib["targetRef"]
    source_elem = process_elem.find(f".//*[@id='{source_id}']")
    if source_elem is not None:
        out_elem = ET.Element(ns + "outgoing")
        out_elem.text = seq_flow.attrib["id"]
        source_elem.append(out_elem)
    target_elem = process_elem.find(f".//*[@id='{target_id}']")
    if target_elem is not None:
        in_elem = ET.Element(ns + "incoming")
        in_elem.text = seq_flow.attrib["id"]
        target_elem.append(in_elem)

def build_minimal_di(definitions, process_elem):
    """
    Create a minimal BPMN-DI section so viewers can render ALL elements.
    One BPMNShape per node (tasks/events/gateways) and one BPMNEdge per sequenceFlow.
    Simple grid layout, left-to-right in document order.
    """
    bpmndi = f"{{{BPMNDI}}}"
    omgdc  = f"{{{OMGDC}}}"
    omgdi  = f"{{{OMGDI}}}"

    diagram = ET.SubElement(definitions, f"{bpmndi}BPMNDiagram", id="BPMNDiagram_1")
    plane   = ET.SubElement(diagram,   f"{bpmndi}BPMNPlane",
                            id="BPMNPlane_1", bpmnElement=process_elem.attrib["id"])

    # Layout params
    start_x, start_y = 100, 100
    dx, dy = 180, 130
    row_width = 6  # wrap after N nodes

    centers = {}  # id -> (cx, cy)
    idx = 0

    # Shapes for flow nodes
    for node in list(process_elem):
        local = node.tag.split('}')[-1]
        if local not in ("task", "startEvent", "endEvent", "exclusiveGateway", "parallelGateway", "inclusiveGateway"):
            continue

        # sizes
        if local == "task":
            w, h = 100, 80
        elif local in ("exclusiveGateway", "parallelGateway", "inclusiveGateway"):
            w, h = 50, 50
        else:  # start/end
            w, h = 36, 36

        col = idx % row_width
        row = idx // row_width
        bx = start_x + col * dx
        by = start_y + row * dy

        shape = ET.SubElement(plane, f"{bpmndi}BPMNShape",
                              id=f"{node.attrib['id']}_di", bpmnElement=node.attrib["id"])
        ET.SubElement(shape, f"{omgdc}Bounds",
                      x=str(bx), y=str(by), width=str(w), height=str(h))

        centers[node.attrib["id"]] = (bx + w/2.0, by + h/2.0)
        idx += 1

    # Edges for sequence flows
    for flow in [n for n in list(process_elem) if n.tag.split('}')[-1] == "sequenceFlow"]:
        sid = flow.attrib["sourceRef"]
        tid = flow.attrib["targetRef"]
        (sx, sy) = centers.get(sid, (start_x, start_y))
        (tx, ty) = centers.get(tid, (start_x + dx, start_y))

        edge = ET.SubElement(plane, f"{bpmndi}BPMNEdge",
                             id=f"{flow.attrib['id']}_di", bpmnElement=flow.attrib["id"])
        ET.SubElement(edge, f"{omgdi}waypoint", x=str(int(sx)), y=str(int(sy)))
        ET.SubElement(edge, f"{omgdi}waypoint", x=str(int(tx)), y=str(int(ty)))

# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert custom BPMN-like text to BPMN XML with flows, conditions, and DI")
    parser.add_argument("input", help="Input BPMN text file (custom XML-like format, e.g. input.txt)")
    parser.add_argument("output", help="Output BPMN XML file")
    args = parser.parse_args()

    # Read and lightly escape attribute values that might break XML
    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    def escape_xml_attr_values(text):
        # Replace <= first to avoid double-escaping
        text = text.replace("<=", "&lt;=")
        # Replace & (but not already-escaped ones)
        text = re.sub(r'&(?!lt;|gt;|amp;|apos;|quot;)', '&amp;', text)
        # Replace < and > in attribute values (but not tags)
        def repl_attr(m):
            val = m.group(2)
            val = (val.replace('<', '&lt;')
                       .replace('>', '&gt;')
                       .replace('"', '&quot;')
                       .replace("'", '&apos;'))
            return f"{m.group(1)}='{val}'"
        text = re.sub(r"(\w+)\s*=\s*'([^']*)'", repl_attr, text)
        return text

    fixed_text = escape_xml_attr_values(text)

    # Parse the custom input (root expected to be <process> with children)
    root = ET.fromstring(fixed_text)

    # Build BPMN document
    definitions = ET.Element(f"{{{BPMN}}}definitions",
                             id="Definitions_1",
                             targetNamespace="http://bpmn.io/schema/bpmn")
    process_elem = ET.SubElement(definitions, f"{{{BPMN}}}process",
                                 id="Process_1", isExecutable="true", name="Stroke Process")

    # Start event
    start_event = ET.SubElement(process_elem, f"{{{BPMN}}}startEvent",
                                id="StartEvent_1", name="Start")
    last_exit = "StartEvent_1"

    all_nodes = []
    all_flows = []

    # Process children sequentially, chaining them from start to end
    for child in root:
        s, e, nodes, flows = process_element(child)
        if s is None or e is None:
            continue
        all_nodes.extend(nodes)
        all_flows.extend(flows)
        sf = ET.Element(f"{{{BPMN}}}sequenceFlow",
                        id=new_flow_id(), sourceRef=last_exit, targetRef=s)
        all_flows.append(sf)
        last_exit = e

    # End event and final flow
    end_event = ET.SubElement(process_elem, f"{{{BPMN}}}endEvent",
                              id="EndEvent_1", name="End")
    sf_end = ET.Element(f"{{{BPMN}}}sequenceFlow",
                        id=new_flow_id(), sourceRef=last_exit, targetRef="EndEvent_1")
    all_flows.append(sf_end)

    # Append nodes and flows to the process
    for node in all_nodes:
        process_elem.append(node)
    for flow in all_flows:
        process_elem.append(flow)

    # Add incoming/outgoing refs for each sequenceFlow
    for flow in all_flows:
        add_flow_references(process_elem, flow)

    # Generate minimal DI so viewers can render everything
    build_minimal_di(definitions, process_elem)

    # Write out
    tree_out = ET.ElementTree(definitions)
    tree_out.write(args.output, encoding="UTF-8", xml_declaration=True)

if __name__ == "__main__":
    main()
