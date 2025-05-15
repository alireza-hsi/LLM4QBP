import xml.etree.ElementTree as ET
import argparse
import re

# Global counter for sequence flow IDs
flow_counter = 1
def new_flow_id():
    global flow_counter
    fid = f"Flow_{flow_counter}"
    flow_counter += 1
    return fid

def process_activity(elem):
    """
    Convert an <activity> element from the input BPMN text to a BPMN task.
    The task name will include the action plus role and objects.
    Returns (entry_id, exit_id, list_of_task_elements, list_of_sequenceFlows).
    """
    # Add at the start of the file
    #seen_ids = set()
    
    act_id = elem.attrib.get('id')

    # Check if ID already exists
    #while act_id in seen_ids:
    #    act_id = f"{act_id}-rep"
    #seen_ids.add(act_id)

    role = elem.attrib.get('role')
    action = elem.attrib.get('action')
    objects = elem.attrib.get('objects', '')
    if objects.strip():
        name = f"{action} (Role: {role}; Objects: {objects})"
    else:
        name = f"{action} (Role: {role})"
    task = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}task", id=act_id, name=name)
    return (act_id, act_id, [task], [])

def process_branch(elem):
    """
    Process a <branch> element – if the branch contains multiple activities,
    insert a dummy connector at the start. Returns (branch_entry, branch_exit, nodes, flows)
    """
    nodes = []
    flows = []
    children = list(elem)
    
    # If there is more than one child, insert a dummy node at the branch entry.
    if len(children) > 1:
        dummy_id = "dummy_" + new_flow_id()  # create a unique dummy id
        # Create a dummy task (could also be a gateway if you prefer)
        dummy = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}task",
                           id=dummy_id,
                           name="(dummy branch entry)")
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
        if branch_entry is None:
            branch_entry = s
        if prev_exit is not None:
            # Connect the dummy (or previous element) to the current child
            sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                             id=new_flow_id(), sourceRef=prev_exit, targetRef=s)
            flows.append(sf)
        prev_exit = e
    return (branch_entry, prev_exit, nodes, flows)


def process_parallel_gateway(elem):
    """
    Process a <parallelGateway> element that contains one or more <branch> children.
    Generates a diverging gateway and a matching converging gateway.
    Returns (diverge_id, converge_id, list_of_nodes, list_of_flows)
    """
    pg_id = elem.attrib.get('id')
    diverge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}parallelGateway",
                          id=pg_id, name="Parallel Gateway")
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
    converge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}parallelGateway",
                           id=converge_id, name="Parallel Merge")
    nodes.append(converge)
    for s in branch_entries:
        sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=pg_id, targetRef=s)
        flows.append(sf)
    for e in branch_exits:
        sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf)
    return (pg_id, converge_id, nodes, flows)

def process_inclusive_gateway(elem):
    """
    Process an <inclusiveGateway> element with one or more <branch> children.
    Generates a diverging inclusive gateway and a matching converging inclusive gateway.
    Returns (diverge_id, converge_id, list_of_nodes, list_of_flows)
    """
    ig_id = elem.attrib.get('id')
    diverge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}inclusiveGateway",
                          id=ig_id, name="Inclusive Gateway")
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
    converge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}inclusiveGateway",
                           id=converge_id, name="Inclusive Merge")
    nodes.append(converge)
    for (s, e, cond) in branch_info:
        sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=ig_id, targetRef=s)
        if cond:
            sf.attrib["name"] = cond  # set name attribute to show condition
            ce = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}conditionExpression",
                            attrib={"xsi:type": "bpmn:tFormalExpression"})
            ce.text = cond
            sf.append(ce)
        flows.append(sf)
        sf2 = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                         id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf2)
    return (ig_id, converge_id, nodes, flows)

def process_exclusive_gateway(elem):
    """
    Process an <exclusiveGateway> element with one or more <branch> children.
    Conditions (if provided in branch attribute 'condition') are attached to the outgoing flows.
    Returns (diverge_id, converge_id, list_of_nodes, list_of_flows)
    """
    eg_id = elem.attrib.get('id')
    diverge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}exclusiveGateway",
                          id=eg_id, name="Exclusive Gateway")
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
    converge = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}exclusiveGateway",
                           id=converge_id, name="Exclusive Merge")
    nodes.append(converge)
    for (s, e, cond) in branch_info:
        sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=eg_id, targetRef=s)
        if cond:
            sf.attrib["name"] = cond  # set the name to display the condition
            ce = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}conditionExpression",
                            attrib={"xsi:type": "bpmn:tFormalExpression"})
            ce.text = cond
            sf.append(ce)
        flows.append(sf)
        sf2 = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                         id=new_flow_id(), sourceRef=e, targetRef=converge_id)
        flows.append(sf2)
    return (eg_id, converge_id, nodes, flows)

def process_element(elem):
    """
    Determine the element type and process accordingly.
    Returns (entry_id, exit_id, list_of_BPMN_nodes, list_of_sequenceFlows)
    """
    if elem.tag == "activity":
        return process_activity(elem)
    elif elem.tag == "parallelGateway":
        return process_parallel_gateway(elem)
    elif elem.tag == "inclusiveGateway":
        return process_inclusive_gateway(elem)
    elif elem.tag == "exclusiveGateway":
        return process_exclusive_gateway(elem)
    elif elem.tag == "branch":
        return process_branch(elem)
    else:
        # Unrecognized element; ignore it.
        return (None, None, [], [])

def add_flow_references(process_elem, seq_flow):
    """
    Given a sequenceFlow element, find the source and target elements in the process
    and add <incoming> and <outgoing> references.
    """
    ns = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
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

def main():
    parser = argparse.ArgumentParser(description="Convert BPMN Text to BPMN XML with sequence flows and branch conditions")
    parser.add_argument("input", help="Input BPMN text file (custom XML-like format, e.g. input.txt)")
    parser.add_argument("output", help="Output BPMN XML file")
    args = parser.parse_args()

    # Read and fix the input file as text to escape problematic tokens.
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
            val = val.replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')
            return f"{m.group(1)}='{val}'"
        text = re.sub(r"(\w+)\s*=\s*'([^']*)'", repl_attr, text)
        return text

    fixed_text = escape_xml_attr_values(text)

    # Parse the fixed text into an XML tree.
    root = ET.fromstring(fixed_text)  # Root element should be <process>

    # Create BPMN definitions element
    bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
    ET.register_namespace("bpmn", bpmn_ns)
    definitions = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions",
                             id="Definitions_1",
                             targetNamespace="http://bpmn.io/schema/bpmn")
    process_elem = ET.SubElement(definitions, "{http://www.omg.org/spec/BPMN/20100524/MODEL}process",
                                  id="Process_1", isExecutable="true", name="Stroke Process")

    # Create start event
    start_event = ET.SubElement(process_elem, "{http://www.omg.org/spec/BPMN/20100524/MODEL}startEvent",
                                id="StartEvent_1", name="Start")
    last_exit = "StartEvent_1"
    all_nodes = []
    all_flows = []

    # Process each child of the input <process> element sequentially
    for child in root:
        s, e, nodes, flows = process_element(child)
        if s is None or e is None:
            continue
        all_nodes.extend(nodes)
        all_flows.extend(flows)
        sf = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=last_exit, targetRef=s)
        all_flows.append(sf)
        last_exit = e

    # Create end event and link last element to end
    end_event = ET.SubElement(process_elem, "{http://www.omg.org/spec/BPMN/20100524/MODEL}endEvent",
                              id="EndEvent_1", name="End")
    sf_end = ET.Element("{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow",
                        id=new_flow_id(), sourceRef=last_exit, targetRef="EndEvent_1")
    all_flows.append(sf_end)

    # Append all generated nodes and flows to the process element
    for node in all_nodes:
        process_elem.append(node)
    for flow in all_flows:
        process_elem.append(flow)

    # Add incoming/outgoing references to each sequenceFlow
    for flow in all_flows:
        add_flow_references(process_elem, flow)

    # Write the output BPMN XML file
    tree_out = ET.ElementTree(definitions)
    tree_out.write(args.output, encoding="UTF-8", xml_declaration=True)

if __name__ == "__main__":
    main()
