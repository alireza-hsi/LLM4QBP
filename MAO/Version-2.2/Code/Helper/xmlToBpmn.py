import xml.etree.ElementTree as ET

# --- Setup Namespaces ---
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
OMGDC_NS = "http://www.omg.org/spec/DD/20100524/DC"
OMGDI_NS = "http://www.omg.org/spec/DD/20100524/DI"

ET.register_namespace("bpmn", BPMN_NS)
ET.register_namespace("bpmndi", BPMNDI_NS)
ET.register_namespace("omgdc", OMGDC_NS)
ET.register_namespace("omgdi", OMGDI_NS)

# --- Create the root definitions element ---
definitions = ET.Element("{%s}definitions" % BPMN_NS, {
    "id": "Definitions_1",
    "targetNamespace": "http://example.com/bpmn"
})
process = ET.SubElement(definitions, "{%s}process" % BPMN_NS, {
    "id": "Process_1",
    "isExecutable": "false"
})

# --- Global layout variables ---
# We'll assign each BPMN element a position (x, y, width, height)
layout_positions = {}
layout_counter = 0  # used to determine horizontal order

def assign_layout(element_id, branch_offset=0):
    """Assign a layout position for an element.
       Each new element gets x = 100 + (layout_counter*150)
       and y = 100 + (branch_offset*150). Width and height are fixed.
    """
    global layout_counter
    x = 100 + layout_counter * 150
    y = 100 + branch_offset * 150
    width = 80
    height = 50
    layout_positions[element_id] = (x, y, width, height)
    layout_counter += 1

# --- Helper Functions for BPMN Elements ---

def create_task(custom_elem, branch_offset=0):
    task = ET.Element("{%s}task" % BPMN_NS, {
        "id": custom_elem.attrib.get("id"),
        "name": custom_elem.attrib.get("action")
    })
    # Add documentation with extra details
    doc = ET.SubElement(task, "{%s}documentation" % BPMN_NS)
    role = custom_elem.attrib.get("role", "")
    objects = custom_elem.attrib.get("objects", "")
    doc.text = f"Role: {role}\nObjects: {objects}"
    process.append(task)
    assign_layout(task.attrib["id"], branch_offset)
    return task

def create_gateway(custom_elem, gateway_type, branch_offset=0):
    # gateway_type: "parallelGateway" or "exclusiveGateway"
    tag = "{%s}%s" % (BPMN_NS, gateway_type)
    gateway = ET.Element(tag, {"id": custom_elem.attrib.get("id")})
    process.append(gateway)
    assign_layout(gateway.attrib["id"], branch_offset)
    return gateway

def create_sequence_flow(source_id, target_id, name=""):
    flow_id = f"Flow_{source_id}_to_{target_id}"
    seq_flow = ET.Element("{%s}sequenceFlow" % BPMN_NS, {
        "id": flow_id,
        "sourceRef": source_id,
        "targetRef": target_id
    })
    if name:
        seq_flow.set("name", name)
    process.append(seq_flow)
    return seq_flow

# --- Recursive Function to Process Custom BPMN Elements ---
def process_elements(elements, branch_offset=0):
    """
    Process a list of custom BPMN elements.
    Returns (entry, exits) where entry is the first BPMN element's ID in this sequence,
    and exits is a list of "last" element IDs that new elements should connect from.
    The branch_offset adjusts the vertical placement.
    """
    entry = None
    exits = []  # list of BPMN element IDs that are the last ones in the sequence

    for elem in elements:
        if elem.tag == "activity":
            task = create_task(elem, branch_offset)
            task_id = task.attrib["id"]
            if entry is None:
                entry = task_id
            # Connect previous exit(s) to current task
            for prev in exits:
                create_sequence_flow(prev, task_id)
            exits = [task_id]

        elif "Gateway" in elem.tag:
            # Determine gateway type
            if "parallel" in elem.tag.lower():
                gw_type = "parallelGateway"
            else:
                gw_type = "exclusiveGateway"
            gateway = create_gateway(elem, gw_type, branch_offset)
            gw_id = gateway.attrib["id"]
            if entry is None:
                entry = gw_id
            for prev in exits:
                create_sequence_flow(prev, gw_id)
            # Process each branch in the gateway.
            branch_exits = []
            branches = list(elem.findall("branch"))
            for i, branch in enumerate(branches):
                # For each branch, use a different vertical offset.
                b_offset = branch_offset + (i + 1)
                branch_elements = list(branch)
                if branch_elements:
                    b_entry, b_exits = process_elements(branch_elements, b_offset)
                    condition = branch.attrib.get("condition", "")
                    create_sequence_flow(gw_id, b_entry, condition)
                    branch_exits.extend(b_exits)
            # For simplicity, we assume branches merge naturally.
            exits = branch_exits
    return entry, exits

# --- Custom BPMN Text Input ---
custom_bpmn_text = """
<process>
  <activity role='medical staff' action='conduct rapid initial evaluation' objects='airway, breathing, circulation' id='activity1'/>
  <parallelGateway id='parallelgateway1'>
    <branch id='branch1'>
      <activity role='medical staff' action='perform neurological examination' objects='standardized stroke scale (NIHSS or CNS)' id='activity2'/>
    </branch>
    <branch id='branch2'>
      <activity role='medical staff' action='prepare patient for imaging' objects='' id='activity3-1'/>
      <activity role='medical staff' action='perform CT or MRI scan' objects='' id='activity3-2'/>
      <activity role='health care provider' action='interpret brain imaging' objects='CT or MRI results' id='activity4'/>
    </branch>
    <branch id='branch3'>
      <activity role='medical staff' action='perform ECG' objects='detect atrial fibrillation and acute arrhythmias' id='activity5'/>
    </branch>
    <branch id='branch4'>
      <activity role='medical staff' action='collect blood samples' objects='CBC, electrolytes, creatinine, glucose, INR, partial thromboplastin time, troponin test' id='activity6-1'/>
      <activity role='medical staff' action='analyze blood samples' objects='CBC, electrolytes, creatinine, glucose, INR, partial thromboplastin time, troponin test' id='activity6-2'/>
    </branch>
    <branch id='branch5'>
      <activity role='medical staff' action='ensure chest x-ray does not delay thrombolysis assessment' objects='' id='activity7'/>
    </branch>
  </parallelGateway>
  <parallelGateway id='parallelgateway2'>
    <branch id='branch6'>
      <activity role='medical staff' action='make patients NPO and screen swallowing ability' objects='bedside testing protocol' id='activity8'/>
    </branch>
    <branch id='branch7'>
      <activity role='medical staff' action='monitor patients not alert within 24 hours' objects='swallowing ability' id='activity9'/>
    </branch>
    <branch id='branch8'>
      <activity role='speech-language pathologist' action='assess swallowing ability' objects='patients with dysphagia or pulmonary aspiration' id='activity10'/>
    </branch>
  </parallelGateway>
  <activity role='medical staff' action='provide cross-continuum secondary prevention assessments and therapies' objects='Modules 5 and 10' id='activity11'/>
  <activity role='medical staff' action='use standardized triage tool' objects='determine care location for TIA patients' id='activity12'/>
  <exclusiveGateway id='exclusivegateway1'>
    <branch condition='within 48 hours of symptom onset or fluctuating symptoms' id='branch9'>
      <activity role='medical staff' action='prepare patient for vascular imaging' objects='' id='activity13-1'/>
      <activity role='medical staff' action='perform carotid ultrasound, CTA, or MRA' objects='' id='activity13-2'/>
    </branch>
    <branch condition='beyond 48 hours of symptom onset' id='branch10'>
      <activity role='medical staff' action='conduct vascular imaging of brain and neck arteries' objects='as soon as possible' id='activity14'/>
    </branch>
  </exclusiveGateway>
</process>
"""

# Parse the custom BPMN text and process its child elements
custom_root = ET.fromstring(custom_bpmn_text)
proc_entry, proc_exits = process_elements(list(custom_root), branch_offset=0)

# --- Add Start and End Events ---
start_event = ET.SubElement(process, "{%s}startEvent" % BPMN_NS, {
    "id": "StartEvent_1",
    "name": "Start"
})
assign_layout("StartEvent_1", branch_offset=0)

end_event = ET.SubElement(process, "{%s}endEvent" % BPMN_NS, {
    "id": "EndEvent_1",
    "name": "End"
})
assign_layout("EndEvent_1", branch_offset=0)

# Connect the start event to the entry node (if any)
if proc_entry:
    create_sequence_flow("StartEvent_1", proc_entry)

# Connect all exit nodes to the end event
for exit_id in proc_exits:
    create_sequence_flow(exit_id, "EndEvent_1")

# --- Create Minimal BPMN DI (Diagram Interchange) ---
bpmndi = ET.SubElement(definitions, "{%s}BPMNDiagram" % BPMNDI_NS, {"id": "BPMNDiagram_1"})
bpmnplane = ET.SubElement(bpmndi, "{%s}BPMNPlane" % BPMNDI_NS, {"id": "BPMNPlane_1", "bpmnElement": "Process_1"})

# For each BPMN element (nodes) we created, add a BPMNShape with its bounds.
for element in process:
    tag = element.tag
    # We only add shapes for flow nodes (startEvent, endEvent, task, gateways)
    if tag.endswith("sequenceFlow"):
        continue  # will handle edges separately
    elem_id = element.attrib.get("id")
    if not elem_id or elem_id not in layout_positions:
        continue
    x, y, width, height = layout_positions[elem_id]
    shape = ET.SubElement(bpmnplane, "{%s}BPMNShape" % BPMNDI_NS, {
        "id": f"{elem_id}_di",
        "bpmnElement": elem_id
    })
    bounds = ET.SubElement(shape, "{%s}Bounds" % OMGDC_NS, {
        "x": str(x),
        "y": str(y),
        "width": str(width),
        "height": str(height)
    })

# For each sequenceFlow, add a BPMNEdge with two waypoints (from center of source to center of target)
for element in process:
    if element.tag.endswith("sequenceFlow"):
        flow_id = element.attrib["id"]
        source_ref = element.attrib["sourceRef"]
        target_ref = element.attrib["targetRef"]
        if source_ref in layout_positions and target_ref in layout_positions:
            sx, sy, sw, sh = layout_positions[source_ref]
            tx, ty, tw, th = layout_positions[target_ref]
            # Compute center points
            source_center = (sx + sw/2, sy + sh/2)
            target_center = (tx + tw/2, ty + th/2)
            edge = ET.SubElement(bpmnplane, "{%s}BPMNEdge" % BPMNDI_NS, {
                "id": f"{flow_id}_di",
                "bpmnElement": flow_id
            })
            # Add waypoint for source center
            ET.SubElement(edge, "{%s}waypoint" % OMGDI_NS, {
                "x": str(source_center[0]),
                "y": str(source_center[1])
            })
            # Add waypoint for target center
            ET.SubElement(edge, "{%s}waypoint" % OMGDI_NS, {
                "x": str(target_center[0]),
                "y": str(target_center[1])
            })

# --- Write the BPMN XML to a .bpmn file ---
tree = ET.ElementTree(definitions)
output_file = "converted.bpmn"
tree.write(output_file, encoding="utf-8", xml_declaration=True)
print(f"BPMN file has been saved to {output_file}.")
