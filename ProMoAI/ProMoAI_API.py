#!/usr/bin/env python3
import argparse
import os
import sys
import time
import traceback

from CodeGen import get_initial_messages, generate_code_from_messages

# pm4py imports
from pm4py.objects.conversion.powl.variants.to_petri_net import apply as powl_to_pn
from pm4py.objects.conversion.wf_net.variants.to_bpmn import apply as pn_to_bpmn
from pm4py.objects.bpmn.layout import layouter
from pm4py.objects.bpmn.exporter.variants.etree import get_xml_string
from pm4py.visualization.bpmn import visualizer as bpmn_visualizer

MAX_REPAIR = 3
MAX_FRESH  = 3

def exec_and_get_model(code_str):
    """Executes the generated code and returns final_model."""
    local_vars = {}
    try:
        exec(code_str, {}, local_vars)
    except Exception:
        tb = traceback.format_exc()
        raise RuntimeError(tb)
    if "final_model" not in local_vars:
        raise RuntimeError("`final_model` not defined by the generated code.")
    return local_vars["final_model"]

def main():
    p = argparse.ArgumentParser(description="Generate POWL → BPMN with ProMoAI, self-healing up to 3×3")
    p.add_argument("--task-file",    required=True, help=".txt clinical guideline")
    p.add_argument("--api-key",      default=None,   help="OpenAI API key")
    p.add_argument("--model",        default="GPT_4o1",
                   help="Model name (analytics-friendly), maps internally to gpt-4.1")
    p.add_argument("--output-dir",   default="WareHouse", help="Where to stash runs")
    p.add_argument("--project-name", default=None, help="Override run folder name")
    args = p.parse_args()

    # 1) build the one initial message
    initial_messages = get_initial_messages(args.task_file)

    code = None
    powl_model = None

    # 2) iterate fresh generations
    fresh_attempt = repair_attempt = None  
    for fresh in range(1, MAX_FRESH+1):
        print(f"[Fresh attempt {fresh}/{MAX_FRESH}] Generating initial code…")
        try:
            code = generate_code_from_messages(initial_messages.copy(),
                                               openai_api_key=args.api_key,
                                               model=args.model)
        except Exception as e:
            print("  ✗ Error calling LLM for initial code:", e)
            continue


        # 3) try up to MAX_REPAIR repairs
        messages = initial_messages.copy()
        success = False
        for rep in range(1, MAX_REPAIR+1):
            print(f"  [Repair {rep}/{MAX_REPAIR}] Executing code…")
            try:
                powl_model = exec_and_get_model(code)
                success = True
                fresh_attempt = fresh
                repair_attempt = rep - 1
                print("  ✔ Code ran without error.")
                break
            except Exception as err:
                err_msg = str(err)
                print(f"  ✗ Execution error:\n{err_msg}")
                # append assistant + code, then user + error
                messages.append({
                    "role": "assistant",
                    "content": f"```python\n{code}\n```"
                })
                messages.append({
                    "role": "user",
                    "content": f"Executing your code led to an error. Please fix the code so that it runs without error. This is the error message:\n{err_msg}"
                })
                # regen
                try:
                    code = generate_code_from_messages(messages,
                                                       openai_api_key=args.api_key,
                                                       model=args.model)
                except Exception as e2:
                    print("    ✗ LLM failed to return code:", e2)
                    break

        if success:
            break
        else:
            print(f"  All {MAX_REPAIR} repair attempts failed—retrying fresh generation.")

    if powl_model is None:
        print("PROMOAI_RETRIES: failed")  # <--- add this
        print(f"☠ All {MAX_FRESH} fresh attempts (×{MAX_REPAIR} repairs) failed. Skipping run.")
        sys.exit(1)

    # 4) build timestamped run folder
    base = os.path.splitext(os.path.basename(args.task_file))[0]
    ts = time.strftime("%Y%m%d_%H%M%S")
    if args.project_name:
        run_name = f"{args.project_name}_{ts}"
    else:
        run_name = f"{base}_{ts}"
    out_root = os.path.join(os.path.dirname(__file__), args.output_dir)
    os.makedirs(out_root, exist_ok=True)
    run_dir = os.path.join(out_root, run_name)
    os.makedirs(run_dir, exist_ok=True)

    # 5) convert to Petri → BPMN
    net, im, fm = powl_to_pn(powl_model)
    bpmn = pn_to_bpmn(net, im, fm)
    bpmn = layouter.apply(bpmn)

    # 6) export BPMN XML
    xml = get_xml_string(bpmn)
    xml_path = os.path.join(run_dir, "process.bpmn")
    with open(xml_path, "wb") as f:
        f.write(xml)

    # 7) optional PNG preview
    vis = bpmn_visualizer.apply(
        bpmn,
        parameters={bpmn_visualizer.Variants.CLASSIC.value.Parameters.FORMAT: "png"}
    )
    with open(os.path.join(run_dir, "process.png"), "wb") as f:
        f.write(vis.pipe(format="png"))

    # 8) signal success
    print(f"PROMOAI_RETRIES: fresh={fresh_attempt},repair={repair_attempt}")  # <--- add this
    print(xml_path)
    sys.exit(0)

if __name__ == "__main__":
    main()
