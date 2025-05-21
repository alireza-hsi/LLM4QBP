#!/usr/bin/env python3
import os
import xml.etree.ElementTree as ET
from openai import OpenAI
import ast
import re

def extract_python_lists(text):
    """
    Extracts Python list assignments for Set_A and Set_C from the LLM response.
    Returns a string with only the two assignments.
    """
    # Try to extract code from a markdown-style code block
    match = re.search(r"```python(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: extract lines that look like Python list assignments
    lines = text.splitlines()
    code_lines = [line for line in lines if line.strip().startswith("Set_A") or line.strip().startswith("Set_C")]
    return "\n".join(code_lines).strip()

# ------------------------------------------------------------------
# Initialize OpenAI client (requires OPENAI_API_KEY in your environment)
# ------------------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ------------------------------------------------------------------
# 1) Activity-name extraction
# ------------------------------------------------------------------
def get_namespace(tag):
    if tag.startswith('{'):
        return tag[1:].split('}', 1)[0]
    return ''

def extract_activity_names(file_path):
    try:
        tree = ET.parse(file_path)
    except Exception as e:
        raise RuntimeError(f"Error parsing {file_path}: {e}")
    root = tree.getroot()
    ns = get_namespace(root.tag)
    activity_tags = [
        'task','userTask','scriptTask','serviceTask','businessRuleTask',
        'manualTask','sendTask','receiveTask','subProcess','callActivity'
    ]
    names = []
    for tag in activity_tags:
        full_tag = f"{{{ns}}}{tag}"
        for elt in root.findall(f'.//{full_tag}'):
            name = elt.get('name')
            if name:
                names.append(name)
    return names

# ------------------------------------------------------------------
# 2) Call GPT to align Set A → Set B, keeping original for "No match."
# ------------------------------------------------------------------
def get_alignment(set_a, set_b, model="gpt-4.1"):
    prompt = f"""
I have two sets of activity labels from two BPMN process models. I want to align each label from Set A to at most one label in Set B if they mean the same thing. If none of the labels in Set B means the same thing, say 'No match.' Return your answer as a table of three columns: (Label from A), (Best Match in B), and (Explanation). Always use full names. Here are the labels:
Set A: {set_a}
Set B: {set_b}

After finding the pairings give two python lists. Set A which is just set A. And Set C which is the pair from Set B or "No match".
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that aligns labels."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0
    )
    text = response.choices[0].message.content

    # Parse the markdown table into mapping and Set C
    lines = text.strip().splitlines()
    start_idx = next((i for i, line in enumerate(lines)
                      if line.strip().startswith("|") and "Label from A" in line), None)
    table_rows = lines[start_idx+2:] if start_idx is not None else []

    mapping = {}
    set_c = []
    for row in table_rows:
        if not row.strip().startswith("|"):
            continue
        cols = [col.strip() for col in row.strip().split("|")[1:-1]]
        if len(cols) < 3:
            continue
        label_a, label_b, _ = cols
        mapped_name = label_b if label_b != "No match." else label_a
        mapping[label_a] = mapped_name
        set_c.append(mapped_name)

    return mapping, set_c, text

# ------------------------------------------------------------------
# 3) Call GPT again for revision, but revisions will be post-processed
# ------------------------------------------------------------------
def get_revision(set_a, set_b, initial_response, model="gpt-4.1"):
    prompt = f"""
Below is the original alignment response you gave and the original sets.

{initial_response}

Set A: {set_a}
Set B: {set_b}

Please revise your alignment, ensuring you use the full activity names, and return only two Python lists:
- Set_A: the original Set A list.
- Set_C: the corresponding list of best matches (or "No match.").
Return them as valid Python list definitions and nothing else.
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that aligns labels."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0
    )
    return response.choices[0].message.content

# ------------------------------------------------------------------
# 4) Apply mapping to rename activities
# ------------------------------------------------------------------
def update_activity_names(input_file, output_file, mapping):
    tree = ET.parse(input_file)
    root = tree.getroot()
    for elt in root.iter():
        name = elt.get('name')
        if name in mapping:
            elt.set('name', mapping[name])
    tree.write(output_file, encoding="UTF-8", xml_declaration=True)
    print(f"Updated BPMN file saved as: {output_file}")

# ------------------------------------------------------------------
# 5) Main flow
# ------------------------------------------------------------------
if __name__ == "__main__":
    file_ai   = "/Users/alireza/Desktop/DTI/Thesis/code experiments/Similarity_BPMN/BPMNs for test/QBP1_v2.1_Take4_gpt4.1.bpmn"
    file_gold = "/Users/alireza/Desktop/DTI/Thesis/code experiments/Similarity_BPMN/BPMNs for test/QBP_1_.bpmn"
    out_file  = "/Users/alireza/Desktop/DTI/Thesis/code experiments/Similarity_BPMN/BPMNs for test/QBP1_v2.1_Take4_changeName_4.1_AAM_7.bpmn"

    set_a = extract_activity_names(file_ai)
    set_b = extract_activity_names(file_gold)
    print(f"Set A has {len(set_a)} activities.")
    print(f"Set B has {len(set_b)} activities.")

    # First GPT alignment
    mapping, set_c, full_table = get_alignment(set_a, set_b)
    print("\nInitial GPT alignment table:\n", full_table)

    # Revision call
    revised_text = get_revision(set_a, set_b, full_table)
    print("\nRevised Python lists (raw):\n", revised_text)

    # Parse revised lists and enforce original-name fallback
    namespace = {}
    cleaned_code = extract_python_lists(revised_text)
    exec(cleaned_code, {}, namespace)
    rev_set_a = namespace.get('Set_A', set_a)
    rev_set_c = namespace.get('Set_C', set_c)
    # Build final mapping: fallback to original when still 'No match.' or 'No match'
    final_mapping = {}
    for a, c in zip(rev_set_a, rev_set_c):
        if c.strip() in ("No match.", "No match"):
            final_mapping[a] = a
        else:
            final_mapping[a] = c

    print("\nFinal mapping applied:")
    for a, c in final_mapping.items():
        print(f"- {a} -> {c}")

    # Apply to BPMN
    update_activity_names(file_ai, out_file, final_mapping)
