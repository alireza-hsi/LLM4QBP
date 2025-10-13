import xml.etree.ElementTree as ET
import sys

NS = {
    'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
    'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
    'dc': 'http://www.omg.org/spec/DD/20100524/DC',
    'di': 'http://www.omg.org/spec/DD/20100524/DI'
}

def remove_element_from_parent(parent, child):
    """Remove a child element from its parent."""
    for elem in list(parent):
        if elem is child:
            parent.remove(elem)
            return

def find_bpmn_edge(root, flow_id):
    """
    Given a sequence flow id, search for the BPMNEdge element in the BPMNPlane
    that has bpmnElement==flow_id.
    """
    for plane in root.findall('.//bpmndi:BPMNPlane', NS):
        for edge in plane.findall('bpmndi:BPMNEdge', NS):
            if edge.get('bpmnElement') == flow_id:
                return plane, edge
    return None, None

def create_merged_edge(new_flow_id, source_waypoint, target_waypoint):
    """
    Create a new BPMNEdge element for the merged flow.
    Uses the given source and target waypoint coordinates.
    """
    new_edge = ET.Element("{%s}BPMNEdge" % NS['bpmndi'], id="edge_" + new_flow_id, bpmnElement=new_flow_id)
    # Create two di:waypoint elements
    wp1 = ET.Element("{%s}waypoint" % NS['di'])
    wp1.set("x", source_waypoint.get("x"))
    wp1.set("y", source_waypoint.get("y"))
    wp2 = ET.Element("{%s}waypoint" % NS['di'])
    wp2.set("x", target_waypoint.get("x"))
    wp2.set("y", target_waypoint.get("y"))
    new_edge.extend([wp1, wp2])
    return new_edge

def delete_dummy_tasks(input_file, output_file):
    tree = ET.parse(input_file)
    root = tree.getroot()

    # Find the process element (assume one process)
    process_elem = root.find('bpmn:process', NS)
    if process_elem is None:
        print("No <bpmn:process> found.")
        return

    # We'll store new merged sequenceFlow elements here.
    new_flows = []

    # Find dummy tasks (by id starting with "dummy_")
    dummy_tasks = [t for t in process_elem.findall('bpmn:task', NS) if t.get("id", "").startswith("dummy_")]

    for dummy in dummy_tasks:
        dummy_id = dummy.get("id")
        print(f"Processing dummy task: {dummy_id}")

        # Find incoming flows (where targetRef equals dummy_id)
        incoming = [f for f in process_elem.findall('bpmn:sequenceFlow', NS) if f.get("targetRef") == dummy_id]
        # Find outgoing flows (where sourceRef equals dummy_id)
        outgoing = [f for f in process_elem.findall('bpmn:sequenceFlow', NS) if f.get("sourceRef") == dummy_id]

        if len(incoming) != 1 or len(outgoing) != 1:
            print(f"  Skipping dummy {dummy_id}: expected 1 incoming and 1 outgoing, got {len(incoming)} and {len(outgoing)}.")
            continue

        inc_flow = incoming[0]
        out_flow = outgoing[0]

        source_ref = inc_flow.get("sourceRef")
        target_ref = out_flow.get("targetRef")
        new_flow_id = f"merged_{inc_flow.get('id')}_{out_flow.get('id')}"

        print(f"  Merging flow from '{source_ref}' to '{target_ref}' (new flow id: {new_flow_id})")

        # Create the new merged sequenceFlow element.
        merged_flow = ET.Element("{%s}sequenceFlow" % NS['bpmn'],
                                  id=new_flow_id,
                                  sourceRef=source_ref,
                                  targetRef=target_ref)
        # If the incoming flow had a condition, copy it over.
        cond = inc_flow.find("bpmn:conditionExpression", NS)
        if cond is not None:
            # Copy condition attributes and text.
            new_cond = ET.Element("{%s}conditionExpression" % NS['bpmn'], attrib=cond.attrib)
            new_cond.text = cond.text
            merged_flow.append(new_cond)
            # Also copy the name if it exists.
            if "name" in inc_flow.attrib:
                merged_flow.set("name", inc_flow.get("name"))

        new_flows.append(merged_flow)

        # Remove the old flows from the process.
        remove_element_from_parent(process_elem, inc_flow)
        remove_element_from_parent(process_elem, out_flow)

        # Remove the dummy task from the process.
        remove_element_from_parent(process_elem, dummy)

        # In the BPMNDiagram, remove the BPMNShape for the dummy task.
        for plane in root.findall('.//bpmndi:BPMNPlane', NS):
            for shape in plane.findall('bpmndi:BPMNShape', NS):
                if shape.get("bpmnElement") == dummy_id:
                    remove_element_from_parent(plane, shape)
                    print(f"  Removed BPMNShape for dummy '{dummy_id}'.")

        # In the BPMNDiagram, update the diagram for the merged flow.
        # Find BPMNEdge for incoming and outgoing flows.
        plane_inc, edge_inc = find_bpmn_edge(root, inc_flow.get("id"))
        plane_out, edge_out = find_bpmn_edge(root, out_flow.get("id"))
        if edge_inc is not None and edge_out is not None and plane_inc is not None and plane_out is not None:
            # Remove the old edges.
            remove_element_from_parent(plane_inc, edge_inc)
            remove_element_from_parent(plane_out, edge_out)
            # For the merged edge, use the first waypoint of the incoming edge and the last waypoint of the outgoing edge.
            waypoints_inc = edge_inc.findall("{%s}waypoint" % NS['di'])
            waypoints_out = edge_out.findall("{%s}waypoint" % NS['di'])
            if waypoints_inc and waypoints_out:
                source_wp = waypoints_inc[0]
                target_wp = waypoints_out[-1]
            else:
                # Fallback coordinates if waypoints not found.
                source_wp = ET.Element("{%s}waypoint" % NS['di'], x="0", y="0")
                target_wp = ET.Element("{%s}waypoint" % NS['di'], x="0", y="0")
            # Create new BPMNEdge.
            new_edge = create_merged_edge(new_flow_id, source_wp, target_wp)
            # Append new_edge to the first BPMNPlane we found.
            plane_inc.append(new_edge)
            print(f"  Created BPMNEdge for merged flow '{new_flow_id}'.")
        else:
            print(f"  Warning: Could not locate BPMNEdges for flows of dummy '{dummy_id}'.")

    # Append all the new merged sequenceFlows to the process.
    for nf in new_flows:
        process_elem.append(nf)

    tree.write(output_file, encoding="UTF-8", xml_declaration=True)
    print(f"Done. Output written to '{output_file}'.")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python delete_dummy.py input.bpmn output.bpmn")
        sys.exit(1)
    delete_dummy_tasks(sys.argv[1], sys.argv[2])
