# MAO/MAO(AiO version)/Code/run.py
import argparse
import logging
import os
import sys
import json
root = os.path.dirname(__file__)
sys.path.append(root)

from camel.typing import ModelType
from MAO.chat_chain import ChatChain


def get_config(company):
    """Return configuration json files for ChatChain"""
    config_dir = os.path.join(root, "CompanyConfig", company)
    default_config_dir = os.path.join(root, "CompanyConfig", "Default")

    config_files = [
        "ChatChainConfig.json",
        "PhaseConfig.json",
        "RoleConfig.json"
    ]

    config_paths = []
    for config_file in config_files:
        company_config_path = os.path.join(config_dir, config_file)
        default_config_path = os.path.join(default_config_dir, config_file)
        config_paths.append(
            company_config_path if os.path.exists(company_config_path) else default_config_path
        )

    return tuple(config_paths)


def parse_args():
    parser = argparse.ArgumentParser(description='argparse')
    parser.add_argument('--config', type=str, default="Default",
                        help="Name of config, which is used to load configuration under CompanyConfig/")
    parser.add_argument('--org', type=str, default="DefaultOrganization",
                        help="Name of organization")
    parser.add_argument('--task', type=str, default="",
                        help="Prompt of software")
    parser.add_argument('--task-file', type=str,
                        help="Path to file containing the task description")
    parser.add_argument('--name', type=str, default="",
                        help="Name of software")
    parser.add_argument('--model', type=str, default="GPT_4",
                        help="GPT Model, choose from {'GPT_3_5_TURBO','GPT_4','GPT_4_32K',"
                             "'GPT_4o','GPT_4o1','GPT_5o2','GPT_5o2_low_reasoning',"
                             "'GPT_5o2_medium_reasoning','GPT_5o2_high_reasoning',"
                             "'GPT_5o4','GPT_5o4_low_reasoning','GPT_5o4_medium_reasoning',"
                             "'GPT_5o4_high_reasoning','GPT_5o4_xhigh_reasoning'}")
    args = parser.parse_args()

    if args.task_file:
        with open(args.task_file, 'r') as f:
            args.task = f.read().strip()

    return args


if __name__ == "__main__":
    args = parse_args()

    # ── Init ChatChain ─────────────────────────────────────────────────────
    config_path, config_phase_path, config_role_path = get_config(args.config)

    args2type = {
        'GPT_3_5_TURBO':             ModelType.GPT_3_5_TURBO,
        'GPT_4':                     ModelType.GPT_4,
        'GPT_4_32K':                 ModelType.GPT_4_32k,
        'GPT_4o':                    ModelType.GPT_4o,
        'GPT_4o1':                   ModelType.GPT_4o1,
        'GPT_5o2':                   ModelType.GPT_5o2,
        'GPT_5o2_low_reasoning':     ModelType.GPT_5o2_low_reasoning,
        'GPT_5o2_medium_reasoning':  ModelType.GPT_5o2_medium_reasoning,
        'GPT_5o2_high_reasoning':    ModelType.GPT_5o2_high_reasoning,
        'GPT_5o4':                   ModelType.GPT_5o4,
        'GPT_5o4_low_reasoning':     ModelType.GPT_5o4_low_reasoning,
        'GPT_5o4_medium_reasoning':  ModelType.GPT_5o4_medium_reasoning,
        'GPT_5o4_high_reasoning':    ModelType.GPT_5o4_high_reasoning,
        'GPT_5o4_xhigh_reasoning':   ModelType.GPT_5o4_xhigh_reasoning,
    }

    chat_chain = ChatChain(
        config_path=config_path,
        config_phase_path=config_phase_path,
        config_role_path=config_role_path,
        task_prompt=args.task,
        project_name=args.name,
        org_name=args.org,
        model_type=args2type[args.model]
    )

    # ── Pre Processing ─────────────────────────────────────────────────────
    # MUST happen before Init Log — pre_processing() calls set_directory(),
    # which populates env_dict["directory"]. If log setup runs first, the
    # directory is still '' and os.path.join('', 'log.txt') = 'log.txt'
    # (bare filename), which later causes FileNotFoundError in get_info().
    chat_chain.pre_processing()

    # ── Init Log ───────────────────────────────────────────────────────────
    # Now that pre_processing has set env_dict["directory"] to a real absolute
    # path, we can safely build log_filepath inside that directory.
    log_filepath = os.path.join(chat_chain.chat_env.env_dict["directory"], "log.txt")
    chat_chain.log_filepath = log_filepath
    # force=True (3.8+): if another import already attached handlers to the root
    # logger, plain basicConfig is a no-op and log.txt is never created — then
    # statistics.get_info() crashes in post_processing.
    _bc_kw = dict(
        filename=log_filepath,
        level=logging.INFO,
        format='[%(asctime)s %(levelname)s] %(message)s',
        datefmt='%Y-%d-%m %H:%M:%S',
        encoding="utf-8",
    )
    if sys.version_info >= (3, 8):
        _bc_kw["force"] = True
    logging.basicConfig(**_bc_kw)

    # ── Personnel Recruitment ──────────────────────────────────────────────
    chat_chain.make_recruitment()

    # ── Chat Chain ─────────────────────────────────────────────────────────
    chat_chain.execute_chain()

    # ── Post Processing ────────────────────────────────────────────────────
    chat_chain.post_processing()

    # ── Output the BPMN path for the pipeline to capture ──────────────────
    # Prefer the no-dummy variant; fall back to the raw process.bpmn.
    # Only print if the file actually exists — printing a non-existent path
    # would cause the pipeline to report bpmn_file_not_found unnecessarily.
    software_dir = chat_chain.chat_env.env_dict["directory"]
    no_dummy = os.path.join(software_dir, "process_no_dummy.bpmn")
    raw_bpmn  = os.path.join(software_dir, "process.bpmn")

    if os.path.exists(no_dummy):
        print(no_dummy)
    elif os.path.exists(raw_bpmn):
        print(raw_bpmn)
    else:
        # Neither file was produced — BPMN conversion failed.
        # Exit with a non-zero code so the pipeline catches it as a failure.
        print(f"ERROR: No BPMN output found in {software_dir}", file=sys.stderr)
        sys.exit(1)