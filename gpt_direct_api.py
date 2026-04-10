#!/usr/bin/env python3
"""
gpt_direct_api.py
=================
"GPT Direct" framework — asks the OpenAI model to produce a valid BPMN 2.0
XML file directly from a clinical process description.

API convention (matches the project's existing usage):
    import openai
    openai.api_key = "..."
    openai.chat.completions.create(
        model=...,
        messages=[...],
        temperature=1.0,            # must be 1 for reasoning models
        max_completion_tokens=32000,
        reasoning_effort="high",    # only for reasoning-capable models
    )

Retry modes (--retry-mode):
  none     Single attempt. Output saved as-is regardless of validity.
           Pure zero-shot baseline — no second chances.
  repair   One fresh generation + up to MAX_REPAIR repair rounds feeding
           validation errors back to the model. No re-generation.
  full     MAX_FRESH fresh generations × MAX_REPAIR repairs each.
           Most robust mode.

DB framework label: GPT-Direct-none | GPT-Direct-repair | GPT-Direct-full

Stdout (last two lines on success):
  GPT_DIRECT_RETRIES: <summary>
  <absolute/path/to/process.bpmn>

Exits 0 on success, 1 on failure.
"""

import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import openai

MAX_FRESH  = 3
MAX_REPAIR = 3

RETRY_MODES = ("none", "repair", "full")


# ════════════════════════════════════════════════════════════════════════════
# Model resolution
# ════════════════════════════════════════════════════════════════════════════

# Maps pipeline token → (openai_model_id, reasoning_effort | None)
# reasoning_effort is forwarded as a kwarg only when not None.
_MODEL_MAP: dict[str, tuple[str, str | None]] = {
    # GPT-4 family — no reasoning_effort
    "GPT_4":                    ("gpt-4",    None),
    "GPT_4_32K":                ("gpt-4-32k", None),
    "GPT_4o":                   ("gpt-4o",   None),
    "GPT_4o1":                  ("gpt-4o",   None),
    # GPT-5.2 family
    "GPT_5o2":                  ("gpt-5.2",  "medium"),
    "GPT_5o2_low_reasoning":    ("gpt-5.2",  "low"),
    "GPT_5o2_medium_reasoning": ("gpt-5.2",  "medium"),
    "GPT_5o2_high_reasoning":   ("gpt-5.2",  "high"),
    # GPT-5.4 family
    "GPT_5o4":                  ("gpt-5.4",  "medium"),
    "GPT_5o4_medium_reasoning": ("gpt-5.4",  "medium"),
    "GPT_5o4_high_reasoning":   ("gpt-5.4",  "high"),
    "GPT_5o4_xhigh_reasoning":  ("gpt-5.4",  "xhigh"),
}


def _resolve_model(model_str: str) -> tuple[str, str | None]:
    """Return (openai_model_id, reasoning_effort_or_None)."""
    if model_str in _MODEL_MAP:
        return _MODEL_MAP[model_str]

    # Passthrough for raw OpenAI IDs (contain "-" or ".")
    # Detect reasoning_effort from trailing suffix convention
    if any(c in model_str for c in ("-", ".")):
        effort = None
        for suffix, eff in [("xhigh", "xhigh"), ("high", "high"),
                             ("medium", "medium"), ("low", "low")]:
            if model_str.endswith(f"-{suffix}"):
                model_str = model_str[: -(len(suffix) + 1)]
                effort = eff
                break
        return model_str, effort

    print(f"[GPT Direct] Warning: unknown model token {model_str!r}, "
          "falling back to gpt-4o", flush=True)
    return "gpt-4o", None


# ════════════════════════════════════════════════════════════════════════════
# API call — single place that talks to OpenAI
# ════════════════════════════════════════════════════════════════════════════

def _call_api(model_id: str, reasoning_effort: str | None,
              messages: list, timeout: int = 3600) -> str:
    """
    Call the Chat Completions API.

    Key facts about reasoning models (gpt-5.2, gpt-5.4, o3, o4-mini):
    - max_completion_tokens is a SHARED budget for BOTH reasoning tokens AND
      visible output tokens. With xhigh effort the model can spend 50k–100k
      tokens "thinking" before producing a single character of XML.
    - If the budget runs out during reasoning, content is empty and
      finish_reason is "length". This is the root cause of blank responses.
    - OpenAI recommends reserving at least 25k tokens for reasoning alone.
    - Known gpt-5.4 bug: passing max_completion_tokens + reasoning_effort="none"
      causes the API to ignore "none" and reason anyway, burning the entire
      budget invisibly → empty output.

    What we do here:
    - max_completion_tokens = 100_000 (ample for heavy reasoning + BPMN XML)
    - timeout = 3600s (1 hour per call) — gpt-5.4 xhigh can take 20–60 min
    - Check finish_reason and raise a clear human-readable error on "length"
    - Log the reasoning-token vs output-token split on every call so you can
      tune budgets over time
    """
    kwargs: dict = dict(
        model=model_id,
        messages=messages,
        temperature=1.0,
        max_completion_tokens=100_000,
        timeout=timeout,
    )
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    response = openai.chat.completions.create(**kwargs)

    choice  = response.choices[0]
    finish  = choice.finish_reason
    content = choice.message.content or ""

    # Log token breakdown — crucial for diagnosing reasoning budget issues
    usage = response.usage
    reasoning_toks = "?"
    if usage:
        out_detail = getattr(usage, "completion_tokens_details", None)
        if out_detail:
            reasoning_toks = getattr(out_detail, "reasoning_tokens", "?")
        print(
            f"  [tokens] input={usage.prompt_tokens}  "
            f"output={usage.completion_tokens}  "
            f"reasoning≈{reasoning_toks}  "
            f"finish={finish}",
            flush=True,
        )

    if finish == "length":
        raise RuntimeError(
            f"finish_reason='length': the max_completion_tokens budget was "
            f"exhausted before any visible output was produced. "
            f"Reasoning tokens consumed most of the budget "
            f"(reasoning≈{reasoning_toks} of {usage.completion_tokens if usage else '?'} "
            f"total output tokens). "
            f"Lower reasoning_effort or increase max_completion_tokens further."
        )

    if not content.strip():
        raise RuntimeError(
            f"Model returned empty content (finish_reason={finish!r}). "
            "Reasoning tokens likely exhausted the token budget. "
            "Try lowering reasoning_effort or increasing max_completion_tokens."
        )

    return content


# ════════════════════════════════════════════════════════════════════════════
# XML extraction & validation
# ════════════════════════════════════════════════════════════════════════════

def _extract_xml(text: str) -> str:
    """Strip markdown fences and locate the start of the XML."""
    text = re.sub(r"```(?:xml|bpmn)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    for marker in ("<?xml", "<definitions"):
        idx = text.find(marker)
        if idx != -1:
            return text[idx:].strip()
    return text


def _validate_bpmn(xml_str: str) -> tuple[bool, str]:
    """Lightweight structural check. Returns (is_valid, error_message)."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"

    tag_local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_local != "definitions":
        return False, f"Root element must be <definitions>, got <{tag_local}>"

    bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
    processes = (root.findall(f"{{{bpmn_ns}}}process")
                 or root.findall("process"))
    if not processes:
        return False, "No <process> element found inside <definitions>."

    task_types = ("task", "userTask", "serviceTask",
                  "startEvent", "endEvent",
                  "exclusiveGateway", "parallelGateway")
    has_node = any(
        root.find(f".//{{{bpmn_ns}}}{t}") is not None
        or root.find(f".//{t}") is not None
        for t in task_types
    )
    if not has_node:
        return False, "Process contains no tasks, gateways, or events."

    return True, ""


# ════════════════════════════════════════════════════════════════════════════
# Prompts
# ════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are an expert BPMN 2.0 modeller.
Your task is to read a clinical process description and produce a complete, \
valid BPMN 2.0 XML document that faithfully represents the described process.

Rules you MUST follow:
1. Output ONLY the raw XML — no prose, no markdown fences, no explanation.
2. The root element must be <definitions> with these namespaces exactly:
     xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
     xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
     xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
     xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
     targetNamespace="http://www.example.com/bpmn"
3. Include exactly ONE <process> element.
4. Every activity MUST be a <task> (or <userTask>) with a descriptive name= attribute.
5. Use <exclusiveGateway> for XOR decisions, <parallelGateway> for AND splits/joins,
   <inclusiveGateway> for OR decisions. Gateways may have name= attributes.
6. Every flow node (task, gateway, event) needs a unique id= attribute.
7. Connect all nodes with <sequenceFlow> elements (sourceRef / targetRef).
8. Include one <startEvent> and one or more <endEvent> elements.
9. Include a <bpmndi:BPMNDiagram> section with a <bpmndi:BPMNShape> for every
   flow node and a <bpmndi:BPMNEdge> for every sequenceFlow, with plausible
   x/y/width/height coordinates so the diagram renders correctly.
10. All IDs must be XML-safe (no spaces; use underscores or camelCase).
11. Do not add dummy or placeholder tasks. Only model what is described.
"""

USER_PROMPT_TEMPLATE = """\
Create a BPMN 2.0 XML model for the following clinical process:

{task_text}

Remember: output ONLY the raw XML starting with <?xml or <definitions.
"""

REPAIR_PROMPT_TEMPLATE = """\
The BPMN XML you produced is not valid. The parser reported:

{error}

Please fix the XML so it parses correctly and still models the same process.
Output ONLY the corrected raw XML.
"""


# ════════════════════════════════════════════════════════════════════════════
# Generation modes
# ════════════════════════════════════════════════════════════════════════════

def _single_attempt(model_id: str, reasoning_effort: str | None,
                    task_text: str) -> tuple[str, str]:
    """retry_mode=none — one call, save output regardless of validity."""
    print("[GPT Direct / none] Single attempt, no retries …", flush=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(task_text=task_text)},
    ]
    raw = _call_api(model_id, reasoning_effort, messages)
    if not raw.strip():
        raise RuntimeError("Model returned an empty response.")

    xml_str = _extract_xml(raw)
    ok, err = _validate_bpmn(xml_str)
    if ok:
        print("  ✔ Response is valid BPMN.", flush=True)
    else:
        print(f"  ⚠ Validation issues (saved anyway): {err}", flush=True)
    return xml_str, "mode=none"


def _repair_mode(model_id: str, reasoning_effort: str | None,
                 task_text: str) -> tuple[str, str]:
    """retry_mode=repair — one generation + up to MAX_REPAIR repair rounds."""
    print("[GPT Direct / repair] One generation + repair loop …", flush=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(task_text=task_text)},
    ]
    raw = _call_api(model_id, reasoning_effort, messages)
    repairs_done = 0

    for repair in range(1, MAX_REPAIR + 1):
        xml_str = _extract_xml(raw)
        ok, err = _validate_bpmn(xml_str)
        if ok:
            print(f"  ✔ Valid after {repairs_done} repair(s).", flush=True)
            return xml_str, f"mode=repair,repairs={repairs_done}"

        print(f"  ✗ Repair {repair}/{MAX_REPAIR}: {err}", flush=True)
        if repair == MAX_REPAIR:
            print("  ⚠ Max repairs reached — saving last output.", flush=True)
            return xml_str, f"mode=repair,repairs={repairs_done},invalid"

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": REPAIR_PROMPT_TEMPLATE.format(error=err),
        })
        raw = _call_api(model_id, reasoning_effort, messages)
        repairs_done += 1

    raise RuntimeError("Repair loop exited unexpectedly.")  # unreachable


def _full_mode(model_id: str, reasoning_effort: str | None,
               task_text: str) -> tuple[str, str]:
    """retry_mode=full — MAX_FRESH × MAX_REPAIR attempts."""
    for fresh in range(1, MAX_FRESH + 1):
        print(f"[GPT Direct / full] Fresh attempt {fresh}/{MAX_FRESH} …", flush=True)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(task_text=task_text)},
        ]
        try:
            raw = _call_api(model_id, reasoning_effort, messages)
        except Exception as e:
            print(f"  ✗ API call failed: {e}", flush=True)
            continue

        for repair in range(1, MAX_REPAIR + 1):
            xml_str = _extract_xml(raw)
            ok, err = _validate_bpmn(xml_str)
            if ok:
                repairs = repair - 1
                print(f"  ✔ Valid (fresh={fresh}, repairs={repairs})", flush=True)
                return xml_str, f"mode=full,fresh={fresh},repairs={repairs}"

            print(f"  ✗ Repair {repair}/{MAX_REPAIR}: {err}", flush=True)
            if repair == MAX_REPAIR:
                break

            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": REPAIR_PROMPT_TEMPLATE.format(error=err),
            })
            try:
                raw = _call_api(model_id, reasoning_effort, messages)
            except Exception as e:
                print(f"    ✗ Repair API call failed: {e}", flush=True)
                break

        print(f"  All repairs exhausted on fresh {fresh} — retrying.", flush=True)

    raise RuntimeError(
        f"GPT Direct (full): all {MAX_FRESH} fresh × {MAX_REPAIR} repair attempts failed."
    )


def generate_bpmn(task_text: str, model_id: str, reasoning_effort: str | None,
                  retry_mode: str = "full") -> tuple[str, str]:
    """Entry point: generate BPMN. Returns (xml_string, retries_summary)."""
    if retry_mode == "none":
        return _single_attempt(model_id, reasoning_effort, task_text)
    elif retry_mode == "repair":
        return _repair_mode(model_id, reasoning_effort, task_text)
    else:
        return _full_mode(model_id, reasoning_effort, task_text)


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="GPT Direct BPMN generator.")
    p.add_argument("--task-file",    required=True)
    p.add_argument("--api-key",      default=None)
    p.add_argument("--model",        default="GPT_4o")
    p.add_argument("--output-dir",   default="GPTDirectOutput")
    p.add_argument("--project-name", default=None)
    p.add_argument(
        "--retry-mode",
        choices=RETRY_MODES,
        default="full",
        help="none | repair | full  (see module docstring for details)",
    )
    args = p.parse_args()

    # ── API key ────────────────────────────────────────────────────────────
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: No OpenAI API key. Set OPENAI_API_KEY or pass --api-key.",
              file=sys.stderr)
        sys.exit(1)
    openai.api_key = api_key

    # ── Model ──────────────────────────────────────────────────────────────
    model_id, reasoning_effort = _resolve_model(args.model)
    print(
        f"[GPT Direct] model={model_id}  "
        f"reasoning_effort={reasoning_effort!r}  "
        f"retry_mode={args.retry_mode}",
        flush=True,
    )

    # ── Task text ──────────────────────────────────────────────────────────
    with open(args.task_file, "r", encoding="utf-8", errors="replace") as f:
        task_text = f.read().strip()

    # Sanitize: remove characters that are illegal in JSON strings.
    # Null bytes, Unicode surrogates, and most control characters (except
    # tab/newline/carriage-return) will cause a 400 BadRequestError at the
    # OpenAI API even though Python can hold them in a str.
    import unicodedata
    def _sanitize(text: str) -> str:
        cleaned = []
        for ch in text:
            cp = ord(ch)
            # Allow normal whitespace (tab=9, newline=10, CR=13)
            if cp in (9, 10, 13):
                cleaned.append(ch)
                continue
            # Drop null bytes and C0/C1 control characters
            if cp < 32 or (0x7F <= cp <= 0x9F):
                continue
            # Drop Unicode surrogates (lone surrogates are invalid in JSON)
            if 0xD800 <= cp <= 0xDFFF:
                continue
            cleaned.append(ch)
        return "".join(cleaned)

    original_len = len(task_text)
    task_text    = _sanitize(task_text)
    if len(task_text) != original_len:
        removed = original_len - len(task_text)
        print(f"[GPT Direct] ⚠ Sanitized task text: removed {removed} "
              f"illegal character(s) (null bytes / surrogates / control chars).",
              flush=True)

    # ── Generate ───────────────────────────────────────────────────────────
    try:
        xml_str, retries = generate_bpmn(
            task_text, model_id, reasoning_effort,
            retry_mode=args.retry_mode,
        )
    except RuntimeError as e:
        print("GPT_DIRECT_RETRIES: failed", flush=True)
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # ── Write BPMN ─────────────────────────────────────────────────────────
    base     = os.path.splitext(os.path.basename(args.task_file))[0]
    ts       = time.strftime("%Y%m%d_%H%M%S")
    run_name = f"{args.project_name}_{ts}" if args.project_name else f"{base}_{ts}"

    out_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output_dir)
    os.makedirs(out_root, exist_ok=True)
    run_dir  = os.path.join(out_root, run_name)
    os.makedirs(run_dir, exist_ok=True)

    bpmn_path = os.path.join(run_dir, "process.bpmn")
    with open(bpmn_path, "w", encoding="utf-8") as f:
        if not xml_str.startswith("<?xml"):
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(xml_str)

    print(f"GPT_DIRECT_RETRIES: {retries}", flush=True)
    print(bpmn_path, flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()