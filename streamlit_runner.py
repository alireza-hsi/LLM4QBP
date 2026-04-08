"""
streamlit_runner.py — BPMN Pipeline Runner + Results Dashboard
==============================================================
Run with:  streamlit run streamlit_runner.py

Tabs
----
1. Batch Experiments  – configure & launch pipeline runs
2. BPMN Comparison    – ad-hoc similarity between two BPMN files
3. Results Dashboard  – full analytics: filters, stats tables, 5 chart types,
                        batch picker (with "last batch" shortcut), dedup toggle,
                        CSV + SQLite download
"""

import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

import altair as alt
import pandas as pd
import streamlit as st

# ── Local helper imports ───────────────────────────────────────────────────
sys.path.insert(0, os.path.join("MAO", "MAO(AiO version)", "Code", "Helper"))
from bpmn_compare_similarity import CompareBPMN

# ── Constants ─────────────────────────────────────────────────────────────
PROMOAI_ENV = "promoai"
MAO_ENV     = "mao"

MAO_CONFIG_OPTIONS = [
    "Version-2.2", "Version-3.0", "Version-3.2", "Version-3.3", "Version-3.4",
    "Version-3.5", "Version-3.6", "Version-3.7", "Version-3.8",
    "Version-4.0", "Version-4.1", "Version-4.2",
]

STATUS_ICON = {
    "ok":                "🟢",
    "ok_no_gold":        "🔵",
    "failed_generation": "🔴",
    "failed_mapping":    "🟠",
    "failed_similarity": "🟡",
    "failed_error":      "🔴",
}

CHART_TYPES = [
    "Bar",
    "Bar (with Value Labels)",
    "Stacked Bar (with Value Labels)",
    "Dot",
    "Difference from Min",
]

# ════════════════════════════════════════════════════════════════════════════
# Page config
# ════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="BPMN Pipeline Runner",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ════════════════════════════════════════════════════════════════════════════
# DB loading & schema normalisation
# ════════════════════════════════════════════════════════════════════════════

def _normalise_runs(df: pd.DataFrame) -> pd.DataFrame:
    """Map legacy column names to the new schema so the rest of the code
    only ever sees one set of names."""
    rename = {
        "node_similarity":      "node_sim",
        "structure_similarity": "struct_sim",
        "graph_edit_distance":  "ged",
        "gold_bpmn_path":       "gold_bpmn",
        "generated_bpmn_path":  "generated_bpmn",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # Legacy table has no 'status' column — every row was a success
    if "status" not in df.columns:
        df["status"] = "ok"

    # Convenience: gold basename for grouping / filtering
    if "gold_bpmn" in df.columns:
        df["gold_bpmn_name"] = df["gold_bpmn"].apply(
            lambda x: os.path.basename(x) if isinstance(x, str) else x
        )
    else:
        df["gold_bpmn_name"] = None

    return df


def _load_db(db_path: str) -> tuple:
    """Return (batches_df, runs_df).  Handles new and legacy schemas."""
    if not os.path.exists(db_path):
        return pd.DataFrame(), pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        try:
            batches = pd.read_sql_query(
                "SELECT * FROM batches ORDER BY started_at DESC", conn
            )
        except Exception:
            batches = pd.DataFrame()

        runs = pd.DataFrame()
        for table in ("runs", "experiment_results"):
            try:
                runs = pd.read_sql_query(
                    f"SELECT * FROM {table} ORDER BY id DESC LIMIT 5000", conn
                )
                runs = _normalise_runs(runs)
                break
            except Exception:
                continue
    finally:
        conn.close()

    return batches, runs


def _load_batch(db_path: str, batch_id: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM runs WHERE batch_id = ? ORDER BY id",
            conn, params=[batch_id],
        )
        return _normalise_runs(df)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Analytics helpers
# ════════════════════════════════════════════════════════════════════════════

def _build_grouped(ok_df: pd.DataFrame,
                   node_col: str, struct_col: str, ged_col: str):
    """
    Build two aggregated DataFrames:
      grouped           per (qbp_name, framework, model, gold_bpmn_name)
      framework_grouped per framework only
    Each has min/max/mean/median for all three metrics.
    """
    group_keys = [k for k in ["qbp_name", "framework", "model", "gold_bpmn_name"]
                  if k in ok_df.columns]

    def _agg(by):
        return ok_df.groupby(by).agg(
            runs              = ("status", "count"),
            node_sim_min      = (node_col,   "min"),
            node_sim_max      = (node_col,   "max"),
            node_sim_mean     = (node_col,   "mean"),
            node_sim_median   = (node_col,   "median"),
            struct_sim_min    = (struct_col, "min"),
            struct_sim_max    = (struct_col, "max"),
            struct_sim_mean   = (struct_col, "mean"),
            struct_sim_median = (struct_col, "median"),
            ged_min           = (ged_col, "min"),
            ged_max           = (ged_col, "max"),
            ged_mean          = (ged_col, "mean"),
            ged_median        = (ged_col, "median"),
        ).reset_index()

    grouped    = _agg(group_keys)
    grouped["group"] = grouped.apply(
        lambda r: " | ".join(str(r[k]) for k in group_keys if pd.notna(r.get(k))),
        axis=1,
    )

    fw_grouped = _agg(["framework"])
    return grouped, fw_grouped


# ════════════════════════════════════════════════════════════════════════════
# Altair chart helpers  (all five types, ported from the old dashboard)
# ════════════════════════════════════════════════════════════════════════════

def _chart_bar(data, x, y, color, y_label):
    return (
        alt.Chart(data).mark_bar()
        .encode(
            x=alt.X(f"{x}:N", sort=None, title=x.replace("_", " ").title()),
            y=alt.Y(f"{y}:Q", title=y_label),
            color=alt.Color(f"{color}:N"),
            tooltip=[x, color, alt.Tooltip(f"{y}:Q", format=".4f")],
        )
        .properties(height=400)
    )


def _chart_bar_labels(data, x, x_offset, y, color, y_label):
    base = alt.Chart(data)
    bars = base.mark_bar().encode(
        x=alt.X(f"{x}:N", sort=None, title=x.replace("_", " ").title()),
        xOffset=f"{x_offset}:N",
        y=alt.Y(f"{y}:Q", title=y_label),
        color=alt.Color(f"{color}:N"),
        tooltip=[x, x_offset, alt.Tooltip(f"{y}:Q", format=".4f")],
    )
    text = base.mark_text(align="center", baseline="bottom", dy=-2, fontSize=11).encode(
        x=alt.X(f"{x}:N", sort=None),
        xOffset=f"{x_offset}:N",
        y=alt.Y(f"{y}:Q"),
        text=alt.Text(f"{y}:Q", format=".3f"),
    )
    return (bars + text).properties(height=400)


def _chart_stacked_labels(data, x, y, color, y_label):
    base = alt.Chart(data)
    bars = base.mark_bar().encode(
        x=alt.X(f"{x}:N", sort=None, title=x.replace("_", " ").title()),
        y=alt.Y(f"{y}:Q", title=y_label),
        color=alt.Color(f"{color}:N"),
        tooltip=[x, color, alt.Tooltip(f"{y}:Q", format=".4f")],
    )
    text = base.mark_text(
        align="center", baseline="middle", fontSize=11, color="black"
    ).encode(
        x=alt.X(f"{x}:N", sort=None),
        y=alt.Y(f"{y}:Q", stack="zero"),
        text=alt.Text(f"{y}:Q", format=".3f"),
    )
    return (bars + text).properties(height=400)


def _chart_dot(data, x, y, color, y_label):
    mn, mx = data[y].min(), data[y].max()
    margin = (mx - mn) * 0.15 if mx > mn else 0.05
    return (
        alt.Chart(data).mark_circle(size=180)
        .encode(
            x=alt.X(f"{x}:N", sort=None, title=x.replace("_", " ").title()),
            y=alt.Y(f"{y}:Q", title=y_label,
                    scale=alt.Scale(domain=[mn - margin, mx + margin])),
            color=alt.Color(f"{color}:N"),
            tooltip=[x, color, alt.Tooltip(f"{y}:Q", format=".4f")],
        )
        .properties(height=400)
    )


def _chart_diff(data: pd.DataFrame, x, y, color, y_label):
    d = data.copy()
    baseline = d[y].min()
    d["_diff"] = d[y] - baseline
    return (
        alt.Chart(d).mark_bar()
        .encode(
            x=alt.X(f"{x}:N", sort=None, title=x.replace("_", " ").title()),
            y=alt.Y("_diff:Q", title=f"{y_label} (diff from min)"),
            color=alt.Color(f"{color}:N"),
            tooltip=[x, color, alt.Tooltip("_diff:Q", format=".4f")],
        )
        .properties(height=400)
    )


def _show_grouped_chart(grouped: pd.DataFrame, metric: str, y_label: str,
                        chart_type: str, key: str):
    """Dispatch to the correct grouped chart builder and render."""
    if chart_type == "Bar":
        st.altair_chart(
            _chart_bar(grouped, "group", metric, "qbp_name", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Bar (with Value Labels)":
        st.altair_chart(
            _chart_bar_labels(grouped, "framework", "qbp_name", metric, "qbp_name", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Stacked Bar (with Value Labels)":
        st.altair_chart(
            _chart_stacked_labels(grouped, "framework", metric, "qbp_name", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Dot":
        st.altair_chart(
            _chart_dot(grouped, "group", metric, "qbp_name", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Difference from Min":
        st.altair_chart(
            _chart_diff(grouped, "group", metric, "qbp_name", y_label),
            use_container_width=True, key=key,
        )


def _show_framework_chart(fw_grouped: pd.DataFrame, metric: str, y_label: str,
                          chart_type: str, key: str):
    """Dispatch to the correct framework-level chart builder and render."""
    if chart_type == "Bar":
        st.altair_chart(
            _chart_bar(fw_grouped, "framework", metric, "framework", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Dot":
        st.altair_chart(
            _chart_dot(fw_grouped, "framework", metric, "framework", y_label),
            use_container_width=True, key=key,
        )
    elif chart_type == "Difference from Min":
        st.altair_chart(
            _chart_diff(fw_grouped, "framework", metric, "framework", y_label),
            use_container_width=True, key=key,
        )


def _render_all_charts(grouped: pd.DataFrame, fw_grouped: pd.DataFrame, prefix: str):
    """
    Render all six chart panels (3 metrics × grouped + framework level).
    Exactly mirrors the old standalone dashboard.
    """
    fw_chart_types = ["Bar", "Dot", "Difference from Min"]
    metrics = [
        ("node_sim_mean",   "Node Similarity Mean"),
        ("struct_sim_mean", "Structure Similarity Mean"),
        ("ged_mean",        "Graph Edit Distance Mean"),
    ]

    for metric_col, label in metrics:
        st.markdown(f"#### {label}")
        col_l, col_r = st.columns(2)

        with col_l:
            st.caption("Per group (QBP × Framework × Model × Gold)")
            ct_g = st.selectbox(
                f"Chart type — per group",
                CHART_TYPES,
                key=f"{prefix}_g_{metric_col}",
            )
            _show_grouped_chart(grouped, metric_col, label, ct_g,
                                key=f"{prefix}_gc_{metric_col}")

        with col_r:
            st.caption("Framework level")
            ct_fw = st.selectbox(
                f"Chart type — framework level",
                fw_chart_types,
                key=f"{prefix}_fw_{metric_col}",
            )
            _show_framework_chart(fw_grouped, metric_col, label, ct_fw,
                                  key=f"{prefix}_fwc_{metric_col}")

        st.divider()


# ════════════════════════════════════════════════════════════════════════════
# Quick results renderer — compact, no charts, used inside Tab 1
# ════════════════════════════════════════════════════════════════════════════

def _render_quick_results(df: pd.DataFrame, elapsed=None):
    if df.empty:
        st.warning("No results found.")
        return

    ok_df     = df[df["status"] == "ok"]
    no_gold   = df[df["status"] == "ok_no_gold"]
    failures  = df[~df["status"].isin(["ok", "ok_no_gold"])]
    has_dedup = "node_sim_dedup" in df.columns and df["node_sim_dedup"].notna().any()

    cols = st.columns(5 if elapsed is not None else 4)
    cols[0].metric("Total Attempts", len(df))
    cols[1].metric("✅ Successes",   len(ok_df))
    cols[2].metric("🔵 No Gold",     len(no_gold))
    cols[3].metric("❌ Failures",    len(failures))
    if elapsed is not None:
        cols[4].metric("⏱ Elapsed", f"{elapsed:.1f}s")

    if ok_df.empty:
        st.info("No successful runs with similarity scores.")
        return

    def _avg(s):
        return f"{s.mean():.4f}" if s.notna().any() else "N/A"

    st.divider()
    st.subheader("Average Similarity — Successful Runs")

    if has_dedup:
        lcol, rcol = st.columns(2)
        with lcol:
            st.caption("**Pre-dedup**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Node Sim",   _avg(ok_df["node_sim"]))
            c2.metric("Struct Sim", _avg(ok_df["struct_sim"]))
            c3.metric("GED",        _avg(ok_df["ged"]))
        with rcol:
            st.caption("**Post-dedup**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Node Sim",   _avg(ok_df["node_sim_dedup"]))
            c2.metric("Struct Sim", _avg(ok_df["struct_sim_dedup"]))
            c3.metric("GED",        _avg(ok_df["ged_dedup"]))
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Node Sim",   _avg(ok_df["node_sim"]))
        c2.metric("Struct Sim", _avg(ok_df["struct_sim"]))
        c3.metric("GED",        _avg(ok_df["ged"]))

    st.divider()
    st.subheader("Per-QBP / Per-Framework Summary")
    grp_keys  = [k for k in ["qbp_name", "framework"] if k in ok_df.columns]
    agg_spec  = dict(
        Runs        = ("status",    "count"),
        Node_Mean   = ("node_sim",  "mean"),
        Struct_Mean = ("struct_sim","mean"),
        GED_Mean    = ("ged",       "mean"),
    )
    if has_dedup:
        agg_spec.update(
            Node_dedup   = ("node_sim_dedup",   "mean"),
            Struct_dedup = ("struct_sim_dedup", "mean"),
            GED_dedup    = ("ged_dedup",        "mean"),
        )
    st.dataframe(
        ok_df.groupby(grp_keys).agg(**agg_spec).reset_index().round(4),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("All Runs Detail")
    show_cols = [
        "attempt_number","qbp_name","framework","model","status",
        "elapsed_seconds","node_sim","struct_sim","ged",
    ]
    if has_dedup:
        show_cols += ["node_sim_dedup","struct_sim_dedup","ged_dedup"]
    show_cols += ["promoai_retries","error"]
    avail = [c for c in show_cols if c in df.columns]
    df_disp = df[avail].copy()
    if "status" in df_disp.columns:
        df_disp["status"] = df_disp["status"].map(
            lambda s: f"{STATUS_ICON.get(s,'⚪')} {s}"
        )
    st.dataframe(df_disp.round(4), use_container_width=True, height=380, hide_index=True)

    bid = df["batch_id"].iloc[0] if "batch_id" in df.columns else "export"
    st.download_button(
        "⬇️ Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"results_{bid}.csv",
        mime="text/csv",
        key="dl_1",
    )
    st.caption(
        "💡 For interactive charts, filters, and full analytics open the "
        "**Results Dashboard** tab."
    )


# ════════════════════════════════════════════════════════════════════════════
# Sidebar — Global Settings
# ════════════════════════════════════════════════════════════════════════════

def new_experiment():
    return {"id": uuid.uuid4().hex[:8]}


with st.sidebar:
    st.title("⚙️ Settings")

    st.subheader("API")
    api_key = st.text_input("OpenAI API Key", type="password", key="api_key")

    st.divider()
    st.subheader("Execution")
    max_workers = st.number_input(
        "Parallel workers", min_value=1, max_value=16, value=1, step=1,
        help="Keep at 1 if your API tier is rate-limited.",
    )
    results_db = st.text_input("Results database", value="resultsDb.sqlite")

    st.divider()
    st.subheader("Defaults")
    default_name_prefix   = st.text_input("Run name prefix",  value="PipelineRun")
    default_model         = st.text_input("Model",            value="GPT_5o2")
    default_mapping_model = st.text_input("Mapping model",    value="gpt-5.2")

    st.divider()
    st.subheader("🔁 Reliability")
    only_successful = st.toggle(
        "Only count successful runs",
        value=False,
        help=(
            "Retry failed runs automatically until the target number of "
            "*successful* runs is reached or the attempt ceiling is hit."
        ),
    )
    if only_successful:
        max_retry_multiplier = st.slider(
            "Max retry multiplier", min_value=1.5, max_value=10.0,
            value=3.0, step=0.5,
            help="max_attempts = target_runs × multiplier",
        )
        st.caption(
            f"target=5, multiplier={max_retry_multiplier:.1f} → "
            f"up to **{int(5*max_retry_multiplier)}** attempts"
        )
    else:
        max_retry_multiplier = 3.0


# ════════════════════════════════════════════════════════════════════════════
# Main area — tabs
# ════════════════════════════════════════════════════════════════════════════

st.title("🔬 BPMN Pipeline Runner")

tab_batch, tab_compare, tab_dashboard = st.tabs([
    "🧪 Batch Experiments",
    "🔍 BPMN Comparison",
    "📊 Results Dashboard",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Batch Experiments
# ════════════════════════════════════════════════════════════════════════════

with tab_batch:

    if "experiments" not in st.session_state:
        st.session_state["experiments"] = [new_experiment()]

    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("➕ Add Experiment", use_container_width=True):
            st.session_state["experiments"].append(new_experiment())
            st.rerun()
    with b2:
        if st.button("🗑 Clear All", use_container_width=True):
            st.session_state["experiments"] = [new_experiment()]
            st.rerun()

    st.divider()

    for idx, exp in enumerate(st.session_state["experiments"]):
        eid = exp["id"]

        # Determine expander label — include QBP count for multi mode
        multi_tasks = st.session_state.get(f"multi_tasks_{eid}") or []
        if st.session_state.get(f"multi_mode_{eid}", False) and multi_tasks:
            exp_label = (
                f"📂 Experiment {idx + 1}  "
                f"[{st.session_state.get(f'framework_{eid}','?')} · "
                f"{len(multi_tasks)} QBPs · "
                f"{st.session_state.get(f'runs_{eid}', 5)} runs each]"
            )
        else:
            exp_label = f"📋 Experiment {idx + 1}"

        with st.expander(exp_label, expanded=True):

            _, del_col = st.columns([10, 1])
            with del_col:
                if st.button("✕", key=f"remove_{eid}", help="Remove"):
                    st.session_state["experiments"] = [
                        e for e in st.session_state["experiments"] if e["id"] != eid
                    ]
                    st.rerun()

            # ── Mode toggle ──────────────────────────────────────────────
            mode_col, _ = st.columns([2, 5])
            with mode_col:
                is_multi = st.toggle(
                    "📂 Multi-QBP mode",
                    value=st.session_state.get(f"multi_mode_{eid}", False),
                    key=f"multi_mode_{eid}",
                    help=(
                        "Upload multiple task files + gold BPMNs at once. "
                        "They are paired by filename stem (e.g. QBP1.txt ↔ QBP1.bpmn). "
                        "All QBPs share the same framework / model / run settings."
                    ),
                )

            # ── Shared settings (same in both modes) ────────────────────
            st.markdown("**Shared settings**")
            col_l, col_r = st.columns(2)
            with col_l:
                fw = st.selectbox(
                    "Framework", ["ProMoAI", "MAO (AiO version)"],
                    key=f"framework_{eid}",
                )
                runs_label = "Target *successful* runs per QBP" if only_successful else "Runs per QBP"
                st.number_input(runs_label, min_value=1, value=5, step=1, key=f"runs_{eid}")
                st.text_input("Model", value=default_model, key=f"model_{eid}")
                st.text_input("Run name prefix", value=default_name_prefix, key=f"name_{eid}")

            with col_r:
                st.text_input("Mapping model", value=default_mapping_model, key=f"mapping_model_{eid}")
                if fw == "MAO (AiO version)":
                    st.selectbox("MAO Version", MAO_CONFIG_OPTIONS, key=f"config_{eid}")
                    cfg_val = st.session_state.get(f"config_{eid}", MAO_CONFIG_OPTIONS[0])
                    st.text_input("MAO Organisation", value=cfg_val, key=f"org_{eid}")

            # ── File uploaders ───────────────────────────────────────────
            st.divider()

            if is_multi:
                # ── MULTI-QBP mode ───────────────────────────────────────
                st.markdown("**📂 Upload files for all QBPs**")

                up_col_l, up_col_r = st.columns(2)
                with up_col_l:
                    task_files = st.file_uploader(
                        "Task files (.txt) — select all at once",
                        type=["txt"],
                        accept_multiple_files=True,
                        key=f"multi_tasks_{eid}",
                    )
                with up_col_r:
                    gold_files = st.file_uploader(
                        "Gold BPMNs (optional) — select all at once",
                        type=["bpmn", "xml"],
                        accept_multiple_files=True,
                        key=f"multi_golds_{eid}",
                    )

                # ── Pairing table ────────────────────────────────────────
                if task_files:
                    task_files_sorted = sorted(task_files, key=lambda f: f.name)
                    gold_files_list   = gold_files or []
                    gold_names        = [gf.name for gf in gold_files_list]
                    gold_by_stem      = {
                        os.path.splitext(gf.name)[0]: gf.name
                        for gf in gold_files_list
                    }

                    # Detect when the uploaded file set changes so we can
                    # re-apply auto-pairing (but preserve manual edits otherwise).
                    _NO_GOLD = "— (no gold)"
                    files_sig = "|".join(
                        sorted(tf.name for tf in task_files_sorted)
                        + sorted(gf.name for gf in gold_files_list)
                    )
                    if st.session_state.get(f"pair_sig_{eid}") != files_sig:
                        # New file set → reset all pair selections to auto values
                        for tf in task_files_sorted:
                            stem = os.path.splitext(tf.name)[0]
                            auto = gold_by_stem.get(stem, _NO_GOLD)
                            st.session_state[f"pair_{eid}_{stem}"] = auto
                        st.session_state[f"pair_sig_{eid}"] = files_sig

                    # Header row
                    runs_val   = int(st.session_state.get(f"runs_{eid}", 5))
                    total_runs = len(task_files_sorted) * runs_val
                    hdr_l, hdr_r = st.columns([3, 1])
                    with hdr_l:
                        st.markdown(
                            f"**QBP ↔ Gold pairing  —  {len(task_files_sorted)} QBPs · "
                            f"{runs_val} runs each · {total_runs} total runs**"
                        )
                    with hdr_r:
                        if st.button("↺ Reset to auto", key=f"pair_reset_{eid}",
                                     help="Revert all pairings to automatic stem-matching"):
                            for tf in task_files_sorted:
                                stem = os.path.splitext(tf.name)[0]
                                st.session_state[f"pair_{eid}_{stem}"] = gold_by_stem.get(stem, _NO_GOLD)
                            st.rerun()

                    # One row per task file with an editable selectbox for the gold
                    gold_options = [_NO_GOLD] + gold_names
                    any_paired   = False
                    any_unpaired = False

                    for tf in task_files_sorted:
                        stem    = os.path.splitext(tf.name)[0]
                        row_l, row_r, row_status = st.columns([3, 3, 1])

                        with row_l:
                            st.markdown(f"&nbsp;&nbsp;📄 `{tf.name}`", unsafe_allow_html=True)

                        with row_r:
                            current = st.session_state.get(f"pair_{eid}_{stem}", _NO_GOLD)
                            # Guard: if previously selected gold was removed, fall back
                            if current not in gold_options:
                                current = gold_by_stem.get(stem, _NO_GOLD)
                                st.session_state[f"pair_{eid}_{stem}"] = current

                            selected = st.selectbox(
                                label="Gold BPMN",
                                options=gold_options,
                                index=gold_options.index(current),
                                key=f"pair_{eid}_{stem}",
                                label_visibility="collapsed",
                            )

                        with row_status:
                            if selected == _NO_GOLD:
                                st.markdown("❌ none")
                                any_unpaired = True
                            else:
                                # Detect if this is the auto-match or a manual override
                                auto = gold_by_stem.get(stem, _NO_GOLD)
                                if selected == auto:
                                    st.markdown("✅ auto")
                                else:
                                    st.markdown("✏️ manual")
                                any_paired = True

                    # Legend
                    st.caption(
                        "✅ auto = stem-matched  ·  ✏️ manual = you changed it  ·  "
                        "❌ none = generation only, no similarity scored"
                    )

                    # Warn about gold files not used by any task
                    used_golds = {
                        st.session_state.get(f"pair_{eid}_{os.path.splitext(tf.name)[0]}", _NO_GOLD)
                        for tf in task_files_sorted
                    }
                    unused = [gn for gn in gold_names if gn not in used_golds]
                    if unused:
                        st.warning(
                            f"⚠️ These gold BPMNs are not assigned to any task file: "
                            f"{', '.join(unused)}"
                        )

                else:
                    st.info("Upload task files above to configure pairing.")

            else:
                # ── SINGLE-QBP mode (original behaviour) ────────────────
                st.markdown("**📄 Single QBP files**")
                s_col_l, s_col_r = st.columns(2)
                with s_col_l:
                    st.file_uploader("Task description (.txt)", type=["txt"], key=f"task_{eid}")
                with s_col_r:
                    st.file_uploader(
                        "Gold BPMN (optional — needed for similarity)",
                        type=["bpmn", "xml"], key=f"gold_{eid}",
                    )

            # ── Dedup toggle ─────────────────────────────────────────────
            st.divider()
            dcol_a, dcol_b = st.columns([1, 3])
            with dcol_a:
                use_dedup = st.toggle(
                    "🔄 Duplicate Handling", value=False, key=f"use_dedup_{eid}",
                )
            with dcol_b:
                if use_dedup:
                    st.success(
                        "**ON** — Similarity computed **before AND after** "
                        "duplicate removal. Both sets stored in DB."
                    )
                else:
                    st.caption("OFF — Only pre-dedup similarity is computed.")

    st.divider()

    if only_successful:
        st.info(
            f"**Only-successful mode ON** — Failed runs will be retried "
            f"(up to {max_retry_multiplier:.1f}× attempts per target) until each "
            "experiment reaches its target.",
            icon="🔁",
        )

    run_all = st.button("🚀 Run ALL Experiments", type="primary", use_container_width=True)

    if run_all:
        if not api_key:
            st.error("Enter your OpenAI API Key in the sidebar.")
            st.stop()

        exps = st.session_state["experiments"]

        # Validate: at least one experiment has files
        def _exp_has_files(e):
            eid = e["id"]
            if st.session_state.get(f"multi_mode_{eid}", False):
                return bool(st.session_state.get(f"multi_tasks_{eid}"))
            return st.session_state.get(f"task_{eid}") is not None

        valid = [e for e in exps if _exp_has_files(e)]
        if not valid:
            st.error("Upload at least one task file (in at least one experiment).")
            st.stop()

        env = os.environ.copy()
        env["OPENAI_API_KEY"] = api_key
        env["PROMOAI_ENV"]    = PROMOAI_ENV
        env["MAO_ENV"]        = MAO_ENV

        tmpdir   = tempfile.mkdtemp()
        manifest = []

        for exp in valid:
            eid      = exp["id"]
            fw       = st.session_state.get(f"framework_{eid}", "ProMoAI")
            runs     = int(st.session_state.get(f"runs_{eid}", 5))
            name     = st.session_state.get(f"name_{eid}", default_name_prefix)
            model    = st.session_state.get(f"model_{eid}", default_model)
            mm       = st.session_state.get(f"mapping_model_{eid}", default_mapping_model)
            dedup    = bool(st.session_state.get(f"use_dedup_{eid}", False))
            config   = st.session_state.get(f"config_{eid}") if fw == "MAO (AiO version)" else None
            org      = st.session_state.get(f"org_{eid}")    if fw == "MAO (AiO version)" else None

            # Shared manifest entry fields
            shared = dict(
                framework=fw, runs=runs, name=name, model=model,
                mapping_model=mm, use_dedup=dedup,
                only_successful=only_successful,
                max_retry_multiplier=max_retry_multiplier,
                config=config, org=org,
            )

            if st.session_state.get(f"multi_mode_{eid}", False):
                # ── Multi-QBP: one manifest entry per QBP, using saved pairings ─
                task_files = st.session_state.get(f"multi_tasks_{eid}") or []
                gold_files = st.session_state.get(f"multi_golds_{eid}") or []
                gold_by_name = {gf.name: gf for gf in gold_files}
                _NO_GOLD = "— (no gold)"

                for tf in sorted(task_files, key=lambda f: f.name):
                    stem      = os.path.splitext(tf.name)[0]
                    qbp_eid   = f"{eid}_{stem}"
                    gold_name = st.session_state.get(f"pair_{eid}_{stem}", _NO_GOLD)
                    gf        = gold_by_name.get(gold_name) if gold_name != _NO_GOLD else None

                    task_path = os.path.join(tmpdir, f"{qbp_eid}__{tf.name}")
                    with open(task_path, "wb") as f:
                        f.write(tf.getvalue())

                    gold_path = gold_fn = None
                    if gf:
                        gold_path = os.path.join(tmpdir, f"{qbp_eid}__{gf.name}")
                        with open(gold_path, "wb") as f:
                            f.write(gf.getvalue())
                        gold_fn = gf.name

                    manifest.append({
                        "id":               qbp_eid,
                        "task_file":        task_path,
                        "gold_bpmn":        gold_path,
                        "gold_bpmn_filename": gold_fn,
                        **shared,
                    })

            else:
                # ── Single-QBP: original behaviour ───────────────────────
                tf = st.session_state[f"task_{eid}"]
                gf = st.session_state.get(f"gold_{eid}")

                task_path = os.path.join(tmpdir, f"{eid}__{tf.name}")
                with open(task_path, "wb") as f:
                    f.write(tf.getvalue())

                gold_path = gold_fn = None
                if gf:
                    gold_path = os.path.join(tmpdir, f"{eid}__{gf.name}")
                    with open(gold_path, "wb") as f:
                        f.write(gf.getvalue())
                    gold_fn = gf.name

                manifest.append({
                    "id":               eid,
                    "task_file":        task_path,
                    "gold_bpmn":        gold_path,
                    "gold_bpmn_filename": gold_fn,
                    **shared,
                })

        # Show a summary of what's about to run
        total_manifest_runs = sum(m["runs"] for m in manifest)
        st.info(
            f"📋 **{len(manifest)} QBP(s)** across {len(valid)} experiment card(s) → "
            f"**{total_manifest_runs} total runs** queued.",
            icon="ℹ️",
        )

        manifest_path = os.path.join(tmpdir, "batch_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        cmd = [
            "python", "-u", "pipeline.py",
            "--batch-manifest",       manifest_path,
            "--max-workers",          str(int(max_workers)),
            "--results-db",           results_db,
            "--max-retry-multiplier", str(max_retry_multiplier),
        ]
        if only_successful:
            cmd.append("--only-successful")

        st.markdown("### ⏳ Live Progress")
        progress_bar  = st.progress(0.0)
        progress_text = st.empty()
        status_box    = st.empty()
        log_box       = st.empty()

        logs       = ""
        batch_id   = None
        start_time = time.time()

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )

        for raw_line in proc.stdout:
            logs += raw_line
            log_box.text_area("📋 Live Logs", logs, height=280, disabled=True,
                              key=f"log_{len(logs)}")

            s = raw_line.strip()

            m = re.match(r"BATCH_ID (\w+)", s)
            if m:
                batch_id = m.group(1)

            m = re.search(r"PROGRESS (\d+)/(\d+)", s)
            if m:
                x, y  = int(m.group(1)), int(m.group(2))
                frac  = min(x / y, 1.0) if y else 0.0
                progress_bar.progress(frac)
                label = "successes" if only_successful else "runs"
                m_att = re.search(r"attempts=(\d+)", s)
                suffix = f"  ({m_att.group(1)} attempts)" if m_att else ""
                progress_text.markdown(f"**{x} / {y}** {label}{suffix}")

            if s.startswith("RETRY "):
                status_box.warning(f"🔁 {s}")

            m = re.search(r"DONE successes=(\d+)/(\d+) attempts=(\d+) elapsed=([\d.]+)s", s)
            if m:
                sv, tv, av, ev = m.groups()
                status_box.success(
                    f"✅ Finished — {sv}/{tv} successes in {av} attempts  ({ev}s)"
                )

        proc.wait()
        elapsed = time.time() - start_time
        progress_bar.progress(1.0)

        st.session_state["last_batch_id"] = batch_id
        st.session_state["last_db"]       = results_db
        st.session_state["last_elapsed"]  = elapsed
        st.session_state["last_logs"]     = logs
        st.session_state["has_results"]   = True

        shutil.rmtree(tmpdir, ignore_errors=True)

        if proc.returncode not in (0, None):
            st.warning(f"Pipeline exited with code {proc.returncode}. Check logs.")

    # ── Quick results ─────────────────────────────────────────────────────
    if st.session_state.get("has_results"):
        st.divider()
        st.markdown("## 📊 Run Results (Quick View)")

        bid     = st.session_state.get("last_batch_id")
        db_path = st.session_state.get("last_db", results_db)
        elapsed = st.session_state.get("last_elapsed")

        if bid:
            _render_quick_results(_load_batch(db_path, bid), elapsed)
        else:
            st.warning("Batch ID unknown — check the Results Dashboard tab.")

        with st.expander("📋 Full Logs", expanded=False):
            st.text_area("", st.session_state.get("last_logs", ""),
                         height=500, disabled=True, key="full_log_display")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — BPMN Comparison
# ════════════════════════════════════════════════════════════════════════════

with tab_compare:
    st.header("🔍 Compare Two BPMN Files")
    st.markdown("Upload any two BPMN files to compute similarity scores instantly.")

    cmp_l, cmp_r = st.columns(2)
    with cmp_l:
        st.subheader("File A")
        bpmn_a = st.file_uploader("First BPMN", type=["bpmn", "xml"], key="cmp_a")
        if bpmn_a:
            st.caption(f"📄 {bpmn_a.name}")
    with cmp_r:
        st.subheader("File B")
        bpmn_b = st.file_uploader("Second BPMN", type=["bpmn", "xml"], key="cmp_b")
        if bpmn_b:
            st.caption(f"📄 {bpmn_b.name}")

    if st.button("🔍 Compare", type="primary", disabled=(not bpmn_a or not bpmn_b)):
        with st.spinner("Comparing…"):
            tmpdir = tempfile.mkdtemp()
            try:
                path_a = os.path.join(tmpdir, bpmn_a.name)
                path_b = os.path.join(tmpdir, bpmn_b.name)
                with open(path_a, "wb") as f: f.write(bpmn_a.getvalue())
                with open(path_b, "wb") as f: f.write(bpmn_b.getvalue())

                comp = CompareBPMN(export_csv=False, export_excel=False)
                ns, ss, ged = comp.calculate_similarity(path_a, path_b)

                st.success("Comparison complete!")
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Node Similarity",      f"{ns:.4f}")
                c2.metric("Structure Similarity",  f"{ss:.4f}")
                c3.metric("Graph Edit Distance",   ged)

                with st.expander("ℹ️ Score interpretation"):
                    st.markdown(
                        """
| Score | Closer to 1 means | Closer to 0 means |
|-------|-------------------|-------------------|
| **Node Similarity** | Node labels nearly identical | Very different activity names |
| **Structure Similarity** | Flow topology matches closely | Very different control flow |
| **GED** | — *(lower = better)* | Graphs structurally far apart |
                        """
                    )
            except Exception as e:
                st.error(f"Comparison failed: {e}")
                st.exception(e)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# Dashboard chart primitives
# ════════════════════════════════════════════════════════════════════════════

def _jitter_df(df: pd.DataFrame, group_col: str, seed: int = 42) -> pd.DataFrame:
    """Add a _jitter_x column that offsets points within their category."""
    import numpy as np
    rng = np.random.default_rng(seed)
    cats = sorted(df[group_col].dropna().unique())
    cat_idx = {c: i for i, c in enumerate(cats)}
    df = df.copy()
    df["_jitter_x"] = df[group_col].map(cat_idx) + rng.uniform(-0.25, 0.25, len(df))
    df["_cat_idx"]  = df[group_col].map(cat_idx)
    return df, cats


def _boxplot(df, x_col, y_col, color_col, y_label, tooltip_extra=None, lower_better=False):
    """Box plot with individual run dots overlaid. Hoverable."""
    tooltip = [
        alt.Tooltip(f"{x_col}:N"),
        alt.Tooltip(f"{y_col}:Q", format=".4f"),
    ]
    if tooltip_extra:
        tooltip += [alt.Tooltip(f"{c}:N") for c in tooltip_extra if c in df.columns]

    df_j, cats = _jitter_df(df, x_col)
    tick_vals  = list(range(len(cats)))
    note       = "  ↓ lower is better" if lower_better else ""

    box = (
        alt.Chart(df)
        .mark_boxplot(extent=1.5, size=38, outliers=True)
        .encode(
            x=alt.X(f"{x_col}:N", title=None,
                    sort=cats,
                    axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
            y=alt.Y(f"{y_col}:Q", title=y_label + note,
                    scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N", legend=None),
        )
    )
    dots = (
        alt.Chart(df_j)
        .mark_circle(size=28, opacity=0.55)
        .encode(
            x=alt.X("_jitter_x:Q", title=None,
                    scale=alt.Scale(domain=[-0.6, len(cats) - 0.4]),
                    axis=alt.Axis(values=tick_vals,
                                  labelExpr=f"[{','.join(repr(c) for c in cats)}][datum.value]",
                                  labelAngle=-30, labelFontSize=11)),
            y=alt.Y(f"{y_col}:Q", scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N"),
            tooltip=tooltip,
        )
    )
    return (box + dots).resolve_scale(x="shared").properties(height=320)


def _heatmap(df, x_col, y_col, val_col, x_label, y_label, val_label,
             scheme="greens", lower_better=False):
    """Mean-value heatmap with annotated cells."""
    grp = (
        df.groupby([x_col, y_col])[val_col]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "mean_val", "count": "n"})
    )
    rect = (
        alt.Chart(grp)
        .mark_rect()
        .encode(
            x=alt.X(f"{x_col}:N", title=x_label,
                    axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
            y=alt.Y(f"{y_col}:N", title=y_label,
                    sort=alt.EncodingSortField("mean_val",
                                               order="ascending" if lower_better else "descending")),
            color=alt.Color("mean_val:Q", title=val_label,
                            scale=alt.Scale(scheme=scheme,
                                            reverse=lower_better,
                                            zero=False),
                            legend=alt.Legend(format=".3f")),
            tooltip=[
                alt.Tooltip(f"{x_col}:N"),
                alt.Tooltip(f"{y_col}:N"),
                alt.Tooltip("mean_val:Q", title=val_label, format=".4f"),
                alt.Tooltip("n:Q", title="Runs"),
            ],
        )
    )
    text = (
        alt.Chart(grp)
        .mark_text(fontSize=11, fontWeight="bold")
        .encode(
            x=alt.X(f"{x_col}:N"),
            y=alt.Y(f"{y_col}:N",
                    sort=alt.EncodingSortField("mean_val",
                                               order="ascending" if lower_better else "descending")),
            text=alt.Text("mean_val:Q", format=".3f"),
            color=alt.condition(
                "datum.mean_val > 0.7" if not lower_better else "datum.mean_val < 50",
                alt.value("white"),
                alt.value("#333"),
            ),
        )
    )
    return (rect + text).properties(height=max(200, len(grp[y_col].unique()) * 35 + 40))


def _slope_chart(df, val_pre, val_post, group_col, label_pre="Pre-dedup",
                 label_post="Post-dedup", y_label="Score"):
    """Slope / paired chart: pre vs post dedup for each run, lines per run."""
    needed = [val_pre, val_post, group_col]
    sub = df.dropna(subset=needed).copy()
    if sub.empty:
        return None
    sub["_run_id"] = sub.index.astype(str)

    long = pd.concat([
        sub[[group_col, "_run_id", val_pre]].rename(columns={val_pre: "_val"}).assign(_stage=label_pre),
        sub[[group_col, "_run_id", val_post]].rename(columns={val_post: "_val"}).assign(_stage=label_post),
    ]).reset_index(drop=True)

    stage_order = [label_pre, label_post]
    lines = (
        alt.Chart(long)
        .mark_line(opacity=0.25, strokeWidth=1.2)
        .encode(
            x=alt.X("_stage:O", sort=stage_order, title=None,
                    axis=alt.Axis(labelFontSize=12)),
            y=alt.Y("_val:Q", title=y_label, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{group_col}:N"),
            detail="_run_id:N",
        )
    )
    # Mean lines — thicker
    mean_df = long.groupby([group_col, "_stage"])["_val"].mean().reset_index()
    mean_lines = (
        alt.Chart(mean_df)
        .mark_line(strokeWidth=3, point=alt.OverlayMarkDef(size=100))
        .encode(
            x=alt.X("_stage:O", sort=stage_order),
            y=alt.Y("_val:Q", scale=alt.Scale(zero=False)),
            color=alt.Color(f"{group_col}:N"),
            tooltip=[
                alt.Tooltip(f"{group_col}:N"),
                alt.Tooltip("_stage:O", title="Stage"),
                alt.Tooltip("_val:Q", title="Mean", format=".4f"),
            ],
        )
    )
    return (lines + mean_lines).properties(height=340)


def _scatter(df, x_col, y_col, color_col, x_label, y_label, tooltip_extra=None):
    """Scatter plot with regression line per group."""
    tooltip = [
        alt.Tooltip(f"{color_col}:N"),
        alt.Tooltip(f"{x_col}:Q", format=".4f"),
        alt.Tooltip(f"{y_col}:Q", format=".4f"),
    ]
    if tooltip_extra:
        tooltip += [alt.Tooltip(f"{c}:N") for c in tooltip_extra if c in df.columns]

    points = (
        alt.Chart(df)
        .mark_circle(size=45, opacity=0.65)
        .encode(
            x=alt.X(f"{x_col}:Q", title=x_label, scale=alt.Scale(zero=False)),
            y=alt.Y(f"{y_col}:Q", title=y_label, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N"),
            tooltip=tooltip,
        )
    )
    reg = (
        alt.Chart(df)
        .transform_regression(x_col, y_col, groupby=[color_col])
        .mark_line(strokeDash=[4, 3], strokeWidth=1.8, opacity=0.8)
        .encode(
            x=alt.X(f"{x_col}:Q"),
            y=alt.Y(f"{y_col}:Q"),
            color=alt.Color(f"{color_col}:N"),
        )
    )
    return (points + reg).properties(height=330)


def _mean_with_errbar(df, x_col, y_col, color_col, y_label, lower_better=False):
    """Mean ± 1 SD bar chart."""
    grp = (
        df.groupby(x_col)[y_col]
        .agg(mean="mean", std="std", count="count")
        .reset_index()
    )
    grp["std"] = grp["std"].fillna(0)
    grp["lo"]  = grp["mean"] - grp["std"]
    grp["hi"]  = grp["mean"] + grp["std"]

    note = "  ↓ lower is better" if lower_better else ""
    bars = (
        alt.Chart(grp)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{x_col}:N", title=None,
                    sort=alt.EncodingSortField("mean",
                                               order="ascending" if lower_better else "descending"),
                    axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
            y=alt.Y("mean:Q", title=y_label + note, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{x_col}:N", legend=None),
            tooltip=[
                alt.Tooltip(f"{x_col}:N"),
                alt.Tooltip("mean:Q", title="Mean", format=".4f"),
                alt.Tooltip("std:Q",  title="± SD", format=".4f"),
                alt.Tooltip("count:Q", title="Runs"),
            ],
        )
    )
    errs = (
        alt.Chart(grp)
        .mark_errorbar()
        .encode(
            x=alt.X(f"{x_col}:N"),
            y=alt.Y("lo:Q"),
            y2=alt.Y2("hi:Q"),
        )
    )
    labels = (
        alt.Chart(grp)
        .mark_text(dy=-8, fontSize=11, fontWeight="bold")
        .encode(
            x=alt.X(f"{x_col}:N"),
            y=alt.Y("mean:Q"),
            text=alt.Text("mean:Q", format=".3f"),
        )
    )
    return (bars + errs + labels).properties(height=300)


def _delta_strip(df, val_pre, val_post, group_col, y_label="Δ Score (post − pre)"):
    """Strip plot of per-run dedup deltas, colored by direction."""
    sub = df.dropna(subset=[val_pre, val_post]).copy()
    if sub.empty:
        return None
    sub["_delta"] = sub[val_post] - sub[val_pre]
    sub["_dir"]   = sub["_delta"].apply(lambda d: "improved" if d > 1e-6 else ("unchanged" if abs(d) < 1e-6 else "worsened"))

    sub_j, cats = _jitter_df(sub, group_col, seed=7)
    tick_vals   = list(range(len(cats)))

    rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#999", strokeDash=[4, 3]).encode(y="y:Q")

    dots = (
        alt.Chart(sub_j)
        .mark_circle(size=40, opacity=0.7)
        .encode(
            x=alt.X("_jitter_x:Q", title=None,
                    scale=alt.Scale(domain=[-0.6, len(cats) - 0.4]),
                    axis=alt.Axis(values=tick_vals,
                                  labelExpr=f"[{','.join(repr(c) for c in cats)}][datum.value]",
                                  labelAngle=-30, labelFontSize=11)),
            y=alt.Y("_delta:Q", title=y_label),
            color=alt.Color("_dir:N",
                            scale=alt.Scale(
                                domain=["improved", "unchanged", "worsened"],
                                range=["#2ca02c", "#aaa", "#d62728"],
                            ),
                            legend=alt.Legend(title="Direction")),
            tooltip=[
                alt.Tooltip(f"{group_col}:N", title="Framework"),
                alt.Tooltip("_delta:Q",  title="Δ", format="+.4f"),
                alt.Tooltip("_dir:N",    title="Direction"),
            ] + ([alt.Tooltip("qbp_name:N")] if "qbp_name" in sub.columns else []),
        )
    )
    return (rule + dots).properties(height=300)


def _success_rate_chart(runs_df):
    """Stacked bar showing success vs failure rate per framework."""
    if "framework" not in runs_df.columns or "status" not in runs_df.columns:
        return None
    df = runs_df.copy()
    df["_result"] = df["status"].apply(
        lambda s: "Success" if s in ("ok", "ok_no_gold")
        else ("No Gold" if s == "ok_no_gold" else "Failed")
    )
    grp = (
        df.groupby(["framework", "_result"])
        .size()
        .reset_index(name="count")
    )
    total = grp.groupby("framework")["count"].transform("sum")
    grp["pct"] = grp["count"] / total * 100

    return (
        alt.Chart(grp)
        .mark_bar()
        .encode(
            x=alt.X("framework:N", title=None,
                    axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
            y=alt.Y("pct:Q", title="% of runs", stack="normalize"),
            color=alt.Color("_result:N",
                            scale=alt.Scale(
                                domain=["Success", "No Gold", "Failed"],
                                range=["#2ca02c", "#1f77b4", "#d62728"],
                            )),
            tooltip=[
                alt.Tooltip("framework:N"),
                alt.Tooltip("_result:N",  title="Result"),
                alt.Tooltip("count:Q",    title="Runs"),
                alt.Tooltip("pct:Q",      title="%", format=".1f"),
            ],
        )
        .properties(height=280)
    )


def _group_bar(grp_df, df_raw, group_col, y_col, y_label, lower_better=False,
               color_col=None, chart_type="Bar + Points"):
    """
    Flexible group comparison chart.  grp_df has columns [group_col, mean, std, lo, hi, count].
    df_raw is the individual-run data for point overlay.
    chart_type: one of Bar+Points | Dot | Diff from Min | Bar+Labels
    """
    color_col = color_col or group_col
    sort_ord   = alt.EncodingSortField("mean", order="ascending" if lower_better else "descending")
    note       = "  ↓ lower is better" if lower_better else ""

    x_enc = alt.X(f"{group_col}:N", sort=sort_ord, title=None,
                  axis=alt.Axis(labelAngle=-38, labelFontSize=10, labelLimit=220))
    y_enc = alt.Y("mean:Q", title=y_label + note, scale=alt.Scale(zero=False))

    tip = [
        alt.Tooltip(f"{group_col}:N", title="Group"),
        alt.Tooltip("mean:Q",  title="Mean",  format=".4f"),
        alt.Tooltip("std:Q",   title="± SD",  format=".4f"),
        alt.Tooltip("count:Q", title="Runs"),
    ]

    if chart_type == "Bar + Points":
        bars = alt.Chart(grp_df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, opacity=0.85).encode(
            x=x_enc, y=y_enc, color=alt.Color(f"{color_col}:N", legend=None), tooltip=tip)
        errs = alt.Chart(grp_df).mark_errorbar(color="#333", ticks=True).encode(
            x=x_enc, y=alt.Y("lo:Q"), y2=alt.Y2("hi:Q"))
        df_j, cats = _jitter_df(df_raw, group_col, seed=9)
        tick_vals  = list(range(len(cats)))
        pts = alt.Chart(df_j).mark_circle(size=22, opacity=0.45).encode(
            x=alt.X("_jitter_x:Q", title=None,
                    scale=alt.Scale(domain=[-0.6, len(cats) - 0.4]),
                    axis=alt.Axis(values=tick_vals,
                                  labelExpr=f"[{','.join(repr(c) for c in cats)}][datum.value]",
                                  labelAngle=-38, labelFontSize=10)),
            y=alt.Y(f"{y_col}:Q", scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N", legend=None),
            tooltip=[alt.Tooltip(f"{group_col}:N"), alt.Tooltip(f"{y_col}:Q", format=".4f")]
                   + ([alt.Tooltip("qbp_name:N")] if "qbp_name" in df_raw.columns else []),
        )
        return (bars + errs + pts).resolve_scale(x="shared").properties(height=330)

    if chart_type == "Bar + Labels":
        bars = alt.Chart(grp_df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, opacity=0.85).encode(
            x=x_enc, y=y_enc, color=alt.Color(f"{color_col}:N", legend=None), tooltip=tip)
        labels = alt.Chart(grp_df).mark_text(dy=-7, fontSize=10, fontWeight="bold").encode(
            x=x_enc, y=y_enc, text=alt.Text("mean:Q", format=".3f"))
        return (bars + labels).properties(height=330)

    if chart_type == "Dot":
        pts = alt.Chart(grp_df).mark_circle(size=140).encode(
            x=x_enc, y=y_enc,
            color=alt.Color(f"{color_col}:N", legend=None), tooltip=tip)
        errs = alt.Chart(grp_df).mark_errorbar(ticks=True).encode(
            x=x_enc, y=alt.Y("lo:Q"), y2=alt.Y2("hi:Q"),
            color=alt.Color(f"{color_col}:N", legend=None))
        return (errs + pts).properties(height=330)

    if chart_type == "Diff from Min":
        g2 = grp_df.copy()
        baseline = g2["mean"].min()
        g2["diff"] = g2["mean"] - baseline
        bars = alt.Chart(g2).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X(f"{group_col}:N", sort=sort_ord, title=None,
                    axis=alt.Axis(labelAngle=-38, labelFontSize=10, labelLimit=220)),
            y=alt.Y("diff:Q", title=f"Δ {y_label} from min"),
            color=alt.Color(f"{color_col}:N", legend=None), tooltip=tip)
        labels = alt.Chart(g2).mark_text(dy=-7, fontSize=10).encode(
            x=alt.X(f"{group_col}:N", sort=sort_ord),
            y="diff:Q", text=alt.Text("diff:Q", format="+.3f"))
        return (bars + labels).properties(height=330)

    return None   # fallback


def _facet_qbp_chart(df, group_col, y_col, y_label, max_cols=3):
    """One small bar chart per QBP, x = group, y = individual runs (mean line)."""
    if "qbp_name" not in df.columns:
        return None
    n_qbp = df["qbp_name"].nunique()
    if n_qbp < 2:
        return None

    base = (
        alt.Chart(df)
        .mark_circle(size=30, opacity=0.55)
        .encode(
            x=alt.X(f"{group_col}:N", title=None,
                    axis=alt.Axis(labelAngle=-40, labelFontSize=9, labelLimit=140)),
            y=alt.Y(f"{y_col}:Q", title=y_label, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{group_col}:N", legend=None),
            tooltip=[alt.Tooltip(f"{group_col}:N"),
                     alt.Tooltip(f"{y_col}:Q", format=".4f"),
                     alt.Tooltip("qbp_name:N")],
        )
    )
    mean_line = (
        alt.Chart(df)
        .mark_tick(size=14, thickness=3, opacity=0.9)
        .encode(
            x=alt.X(f"{group_col}:N"),
            y=alt.Y(f"mean({y_col}):Q"),
            color=alt.Color(f"{group_col}:N", legend=None),
        )
    )
    return (
        (base + mean_line)
        .facet(
            facet=alt.Facet("qbp_name:N", title=None,
                            header=alt.Header(labelFontSize=11, labelFontWeight="bold")),
            columns=min(max_cols, n_qbp),
        )
        .resolve_scale(y="independent")
    )


def _run_trend_chart(df, group_col, y_col, y_label):
    """Score vs attempt_number per group — shows warm-up or degradation effects."""
    if "attempt_number" not in df.columns:
        return None
    sub = df.dropna(subset=["attempt_number", y_col]).copy()
    if sub.empty or sub["attempt_number"].nunique() < 2:
        return None

    mean_per_attempt = (
        sub.groupby([group_col, "attempt_number"])[y_col]
        .mean()
        .reset_index(name="mean_val")
    )

    lines = (
        alt.Chart(mean_per_attempt)
        .mark_line(point=True)
        .encode(
            x=alt.X("attempt_number:Q", title="Run attempt #",
                    axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("mean_val:Q", title=y_label, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{group_col}:N"),
            tooltip=[alt.Tooltip(f"{group_col}:N"),
                     alt.Tooltip("attempt_number:Q", title="Attempt"),
                     alt.Tooltip("mean_val:Q", title="Mean", format=".4f")],
        )
    )
    band = (
        alt.Chart(sub)
        .mark_errorband(extent="stdev", opacity=0.12)
        .encode(
            x=alt.X("attempt_number:Q"),
            y=alt.Y(f"{y_col}:Q"),
            color=alt.Color(f"{group_col}:N", legend=None),
        )
    )
    return (band + lines).properties(height=300)


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — Results Dashboard
# ════════════════════════════════════════════════════════════════════════════

with tab_dashboard:

    # ── DB path + load controls ───────────────────────────────────────────
    db_row = st.columns([4, 1])
    with db_row[0]:
        dash_db = st.text_input("Database", value=results_db, key="dash_db_path",
                                label_visibility="collapsed",
                                placeholder="Path to resultsDb.sqlite")
    with db_row[1]:
        load_db_btn = st.button("🔄 Load DB", use_container_width=True, key="dash_load_btn")

    triggered = load_db_btn or st.session_state.get("dash_loaded")
    if not triggered:
        st.info("Enter a database path above and click **Load DB** to begin.", icon="📂")
        st.stop()

    if not os.path.exists(dash_db):
        st.error(f"Database not found: `{dash_db}`")
        st.stop()

    st.session_state["dash_loaded"] = True
    batches_df, runs_df = _load_db(dash_db)

    if runs_df.empty:
        st.warning("No run data found in this database.")
        st.stop()

    # ── Compact control bar: batch + filters (all in one row) ────────────
    last_bid      = st.session_state.get("last_batch_id")
    has_batch_col = "batch_id" in runs_df.columns

    with st.container():
        ctrl_cols = st.columns([2, 2, 2, 2, 2])

        # Batch selector
        with ctrl_cols[0]:
            if has_batch_col:
                all_bids    = sorted(runs_df["batch_id"].dropna().unique(), reverse=True)
                batch_opts  = ["All batches"] + list(all_bids)
                default_idx = 0
                if last_bid and last_bid in all_bids:
                    default_idx = list(all_bids).index(last_bid) + 1
                batch_choice = st.selectbox(
                    "Batch",
                    batch_opts, index=default_idx,
                    format_func=lambda x: f"⭐ {x}" if x == last_bid else x,
                    key="dash_batch_sel",
                )
                if batch_choice != "All batches":
                    runs_df = runs_df[runs_df["batch_id"] == batch_choice].copy()
            else:
                batch_choice = "All batches"

        # Dedup source
        has_dedup = (
            "node_sim_dedup" in runs_df.columns
            and runs_df["node_sim_dedup"].notna().any()
        )
        with ctrl_cols[1]:
            if has_dedup:
                metric_src = st.selectbox(
                    "Metric source",
                    ["Pre-dedup", "Post-dedup"],
                    key="dash_metric_src",
                )
            else:
                st.selectbox("Metric source", ["Pre-dedup"],
                             key="dash_metric_src_na", disabled=True)
                metric_src = "Pre-dedup"

        node_col   = "node_sim_dedup"   if metric_src == "Post-dedup" else "node_sim"
        struct_col = "struct_sim_dedup" if metric_src == "Post-dedup" else "struct_sim"
        ged_col    = "ged_dedup"        if metric_src == "Post-dedup" else "ged"

        # Row filters (successful runs only for analytics)
        ok_df      = runs_df[runs_df["status"] == "ok"].copy()
        ok_df_plot = ok_df[ok_df[node_col].notna()].copy() if not ok_df.empty else ok_df

        def _opts(col):
            return sorted(ok_df_plot[col].dropna().unique().tolist()) if col in ok_df_plot.columns else []

        with ctrl_cols[2]:
            sel_fw  = st.multiselect("Framework", _opts("framework"),
                                     default=_opts("framework"), key="dash_f_fw")
        with ctrl_cols[3]:
            sel_mdl = st.multiselect("Model",     _opts("model"),
                                     default=_opts("model"),     key="dash_f_mdl")
        with ctrl_cols[4]:
            sel_qbp = st.multiselect("QBP",       _opts("qbp_name"),
                                     default=_opts("qbp_name"), key="dash_f_qbp")

    # Apply filters
    if ok_df_plot.empty:
        st.info("No successful runs in the selected batch.")
        with st.expander("All rows including failures"):
            st.dataframe(runs_df, use_container_width=True, hide_index=True)
        st.stop()

    mask = pd.Series(True, index=ok_df_plot.index)
    if sel_fw  and "framework" in ok_df_plot.columns: mask &= ok_df_plot["framework"].isin(sel_fw)
    if sel_mdl and "model"     in ok_df_plot.columns: mask &= ok_df_plot["model"].isin(sel_mdl)
    if sel_qbp and "qbp_name"  in ok_df_plot.columns: mask &= ok_df_plot["qbp_name"].isin(sel_qbp)
    ok = ok_df_plot[mask].copy()

    if ok.empty:
        st.warning("No data matches the current filters.")
        st.stop()

    # ── Overview strip ────────────────────────────────────────────────────
    def _fmt(s): return f"{s.mean():.4f}" if s.notna().any() else "N/A"
    def _fmti(s): return f"{s.mean():.1f}" if s.notna().any() else "N/A"

    n_fw  = ok["framework"].nunique() if "framework" in ok.columns else 0
    n_qbp = ok["qbp_name"].nunique()  if "qbp_name"  in ok.columns else 0
    total_all = len(runs_df)
    total_ok  = len(ok)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Runs (filtered)", total_ok)
    m2.metric("Frameworks",  n_fw)
    m3.metric("QBPs",        n_qbp)
    m4.metric("Avg Node Sim",   _fmt(ok[node_col]))
    m5.metric("Avg Struct Sim", _fmt(ok[struct_col]))
    m6.metric("Avg GED",        _fmti(ok[ged_col]))

    st.divider()

    # ── Inner tabs ────────────────────────────────────────────────────────
    inner_tabs = [
        "📦 Distributions",
        "🔀 Group Comparison",
        "🗺️ QBP Analysis",
        "⚡ Dedup Impact",
        "🔬 Correlation & Trends",
        "📋 Statistics & Data",
    ]
    t_dist, t_group, t_qbp, t_dedup, t_corr, t_data = st.tabs(inner_tabs)

    # Pre-compute the fw_model column once, outside all tabs
    ok_base = ok.copy()
    if "framework" in ok_base.columns and "model" in ok_base.columns:
        ok_base["_fw_model"] = ok_base["framework"] + " · " + ok_base["model"]

    _color_fw = "framework" if "framework" in ok_base.columns else "model"

    # ════════════════════════════════════════════════
    # 1. DISTRIBUTIONS
    # ════════════════════════════════════════════════
    with t_dist:
        d_group = st.radio(
            "Group x-axis by",
            ["Framework", "Model", "Framework × Model"],
            horizontal=True, key="d_dist_group",
        )
        x_col_d = {
            "Framework":         "framework",
            "Model":             "model",
            "Framework × Model": "_fw_model",
        }.get(d_group, "framework")

        d_metric = st.radio(
            "Metric",
            ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
            horizontal=True, key="d_dist_metric",
        )
        _dm = {
            "Node Similarity":          (node_col,   "Node Similarity"),
            "Structure Similarity":     (struct_col, "Structure Similarity"),
            "GED (lower = better)":     (ged_col,    "GED"),
        }
        d_col, d_label = _dm[d_metric]
        d_lower = (d_metric == "GED (lower = better)")

        st.caption("Box = median + IQR + 1.5× whiskers. Dots = individual runs (hover for details).")
        st.altair_chart(
            _boxplot(ok_base, x_col_d, d_col, _color_fw, d_label,
                     tooltip_extra=["qbp_name", "model", "framework"],
                     lower_better=d_lower),
            use_container_width=True,
        )

        st.divider()
        c_rate, c_bar = st.columns(2)
        with c_rate:
            st.markdown("**Run success rate by framework**")
            filt_runs = runs_df[runs_df["framework"].isin(sel_fw)] \
                if sel_fw and "framework" in runs_df.columns else runs_df
            rc = _success_rate_chart(filt_runs)
            if rc:
                st.altair_chart(rc, use_container_width=True)
        with c_bar:
            st.markdown(f"**Mean ± 1 SD — {d_label}**")
            st.altair_chart(
                _mean_with_errbar(ok_base, "framework", d_col, "framework",
                                  d_label, lower_better=d_lower),
                use_container_width=True,
            )

    # ════════════════════════════════════════════════
    # 2. GROUP COMPARISON
    # ════════════════════════════════════════════════
    with t_group:
        st.caption(
            "Combine any dimensions into a *group*, then compare those groups. "
            "Each bar / dot shows the mean across all runs in that group."
        )

        avail_dims_gc = {k: v for k, v in
                         {"Framework": "framework", "Model": "model", "QBP": "qbp_name"}.items()
                         if v in ok_base.columns}

        gc_row = st.columns([3, 2, 2])
        with gc_row[0]:
            chosen_dims = st.multiselect(
                "Group by",
                list(avail_dims_gc.keys()),
                default=list(avail_dims_gc.keys()),
                key="d_grp_dims",
                help="Which dimensions define a group. "
                     "E.g. Framework + Model = one group per combination.",
            )
        with gc_row[1]:
            grp_metric = st.selectbox(
                "Metric",
                ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
                key="d_grp_metric",
            )
        with gc_row[2]:
            grp_chart_type = st.selectbox(
                "Chart type",
                ["Bar + Points", "Bar + Labels", "Dot", "Diff from Min"],
                key="d_grp_chart_type",
            )

        if not chosen_dims:
            st.info("Select at least one dimension above.")
        else:
            chosen_cols_gc = [avail_dims_gc[d] for d in chosen_dims]
            color_col_gc   = chosen_cols_gc[0]   # color by first chosen dim

            ok_g = ok_base.copy()
            ok_g["_group"] = ok_g[chosen_cols_gc].apply(
                lambda r: " · ".join(str(r[c]) for c in chosen_cols_gc if pd.notna(r[c])),
                axis=1,
            )

            all_groups = sorted(ok_g["_group"].unique())
            sel_groups = st.multiselect(
                "Filter groups",
                all_groups, default=all_groups, key="d_grp_filter",
                help="Leave empty to show all groups.",
            )
            ok_g = ok_g[ok_g["_group"].isin(sel_groups or all_groups)]

            _gc_col_map = {
                "Node Similarity":          (node_col,   "Node Similarity",   False),
                "Structure Similarity":     (struct_col, "Structure Similarity", False),
                "GED (lower = better)":     (ged_col,    "GED",               True),
            }
            gc_val_col, gc_y_label, gc_lower = _gc_col_map[grp_metric]

            def _grp_stats_gc(df, val_col):
                g = (df.groupby("_group")[val_col]
                     .agg(mean="mean", std="std", count="count",
                          min="min", max="max", median="median")
                     .reset_index())
                g["std"] = g["std"].fillna(0)
                g["lo"]  = g["mean"] - g["std"]
                g["hi"]  = g["mean"] + g["std"]
                if color_col_gc in df.columns:
                    mapping = df.drop_duplicates("_group").set_index("_group")[color_col_gc]
                    g[color_col_gc] = g["_group"].map(mapping)
                return g

            grp_stats_df = _grp_stats_gc(ok_g, gc_val_col)
            chart = _group_bar(grp_stats_df, ok_g, "_group", gc_val_col,
                               gc_y_label, lower_better=gc_lower,
                               color_col=color_col_gc, chart_type=grp_chart_type)
            if chart:
                st.altair_chart(chart, use_container_width=True)

            # Compact stats table
            with st.expander("📋 Group statistics table", expanded=True):
                tbl_rows = []
                for g in (sel_groups or all_groups):
                    sub = ok_g[ok_g["_group"] == g]
                    if sub.empty:
                        continue
                    tbl_rows.append({
                        "Group":       g,
                        "N":           len(sub),
                        "Mean":        round(sub[gc_val_col].mean(), 4),
                        "SD":          round(sub[gc_val_col].std(),  4),
                        "Min":         round(sub[gc_val_col].min(),  4),
                        "Median":      round(sub[gc_val_col].median(), 4),
                        "Max":         round(sub[gc_val_col].max(),  4),
                    })
                if tbl_rows:
                    st.dataframe(pd.DataFrame(tbl_rows),
                                 use_container_width=True, hide_index=True)

            # Per-QBP facet (only when QBP is not already the sole grouping dim)
            if "qbp_name" in ok_g.columns and "qbp_name" not in chosen_cols_gc \
                    and ok_g["qbp_name"].nunique() > 1:
                st.divider()
                st.markdown("**Per-QBP breakdown** — dot = run, tick = mean")
                fc = _facet_qbp_chart(ok_g, "_group", gc_val_col, gc_y_label, max_cols=3)
                if fc:
                    st.altair_chart(fc, use_container_width=True)

    # ════════════════════════════════════════════════
    # 3. QBP ANALYSIS
    # ════════════════════════════════════════════════
    with t_qbp:
        if "qbp_name" not in ok_base.columns:
            st.info("QBP name column not available in this dataset.")
        else:
            qbp_metric = st.radio(
                "Metric",
                ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
                horizontal=True, key="d_qbp_metric",
            )
            _qm = {
                "Node Similarity":          (node_col,   "Node Sim",  "greens", False),
                "Structure Similarity":     (struct_col, "Struct Sim","blues",  False),
                "GED (lower = better)":     (ged_col,    "GED",       "reds",   True),
            }
            qm_col, qm_label, qm_scheme, qm_lower = _qm[qbp_metric]

            st.markdown("**QBP × Framework — mean score heatmap**")
            st.caption("Rows sorted hardest → easiest. Hover for exact values.")
            st.altair_chart(
                _heatmap(ok_base, "framework", "qbp_name", qm_col,
                         "Framework", "QBP", qm_label, qm_scheme, qm_lower),
                use_container_width=True,
            )

            if "model" in ok_base.columns and ok_base["model"].nunique() > 1:
                st.markdown("**QBP × Model**")
                st.altair_chart(
                    _heatmap(ok_base, "model", "qbp_name", qm_col,
                             "Model", "QBP", qm_label, qm_scheme, qm_lower),
                    use_container_width=True,
                )

            st.divider()
            st.markdown("**Per-QBP distribution** *(sorted easiest → hardest)*")
            sort_qbp = (ok_base.groupby("qbp_name")[qm_col]
                        .mean()
                        .sort_values(ascending=qm_lower)
                        .index.tolist())
            qbp_box = (
                alt.Chart(ok_base)
                .mark_boxplot(extent=1.5, size=18)
                .encode(
                    y=alt.Y("qbp_name:N", title=None, sort=sort_qbp,
                            axis=alt.Axis(labelFontSize=11)),
                    x=alt.X(f"{qm_col}:Q", title=qm_label,
                             scale=alt.Scale(zero=False)),
                    color=alt.Color("framework:N") if "framework" in ok_base.columns
                          else alt.value("#4c78a8"),
                    tooltip=["qbp_name:N", "framework:N",
                             alt.Tooltip(f"{qm_col}:Q", format=".4f")],
                )
                .properties(height=max(220, len(sort_qbp) * 34 + 60))
            )
            st.altair_chart(qbp_box, use_container_width=True)

    # ════════════════════════════════════════════════
    # 4. DEDUP IMPACT
    # ════════════════════════════════════════════════
    with t_dedup:
        if not has_dedup:
            st.info(
                "No post-dedup scores found. "
                "Enable **Duplicate Handling** on an experiment card to populate this tab.",
                icon="ℹ️",
            )
        else:
            dedup_ok = ok_base.dropna(subset=["node_sim", "node_sim_dedup"]).copy()
            if dedup_ok.empty:
                st.warning("No runs have both pre and post-dedup scores.")
            else:
                dd_metric = st.radio(
                    "Metric",
                    ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
                    horizontal=True, key="d_dedup_metric",
                )
                _ddm = {
                    "Node Similarity":          ("node_sim",   "node_sim_dedup",   "Node Similarity"),
                    "Structure Similarity":     ("struct_sim", "struct_sim_dedup", "Structure Similarity"),
                    "GED (lower = better)":     ("ged",        "ged_dedup",        "GED"),
                }
                dd_pre, dd_post, dd_label = _ddm[dd_metric]

                st.markdown("**Pre → Post dedup slope chart**")
                st.caption(
                    "Thin lines = individual runs, thick lines = group mean. "
                    "Upward slope means dedup improved the score."
                )
                slope = _slope_chart(dedup_ok, dd_pre, dd_post, "framework",
                                     y_label=dd_label)
                if slope:
                    st.altair_chart(slope, use_container_width=True)

                st.divider()
                dd_col_a, dd_col_b = st.columns(2)
                with dd_col_a:
                    st.markdown("**Per-run delta** *(post − pre)*")
                    st.caption("🟢 improved · ⚫ unchanged · 🔴 worsened")
                    ds = _delta_strip(dedup_ok, dd_pre, dd_post, "framework",
                                      y_label=f"Δ {dd_label}")
                    if ds:
                        st.altair_chart(ds, use_container_width=True)

                with dd_col_b:
                    st.markdown("**Summary by framework**")
                    delta_s = (
                        dedup_ok
                        .assign(_d=dedup_ok[dd_post] - dedup_ok[dd_pre])
                        .groupby("framework")["_d"]
                        .agg(Mean="mean", SD="std", N="count")
                        .reset_index()
                    )
                    delta_s["% Improved"] = (
                        dedup_ok
                        .assign(_d=dedup_ok[dd_post] - dedup_ok[dd_pre])
                        .groupby("framework")["_d"]
                        .apply(lambda s: round((s > 1e-6).mean() * 100, 1))
                        .values
                    )
                    st.dataframe(delta_s.round(4), use_container_width=True, hide_index=True)

                    bar_dd = (
                        alt.Chart(delta_s)
                        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                        .encode(
                            x=alt.X("framework:N", title=None,
                                    axis=alt.Axis(labelAngle=-20)),
                            y=alt.Y("Mean:Q", title=f"Mean Δ {dd_label}"),
                            color=alt.condition("datum.Mean >= 0",
                                                alt.value("#2ca02c"),
                                                alt.value("#d62728")),
                            tooltip=["framework:N",
                                     alt.Tooltip("Mean:Q", format="+.4f"),
                                     alt.Tooltip("% Improved:Q")],
                        )
                        .properties(height=190)
                    )
                    zero = (alt.Chart(pd.DataFrame({"y": [0]}))
                            .mark_rule(color="#999").encode(y="y:Q"))
                    st.altair_chart(bar_dd + zero, use_container_width=True)

    # ════════════════════════════════════════════════
    # 5. CORRELATION & TRENDS
    # ════════════════════════════════════════════════
    with t_corr:
        st.markdown("**Node Similarity vs Structure Similarity**")
        st.caption(
            "Points on the diagonal = both metrics agree. "
            "Dashed lines = per-group linear fit."
        )
        sc1 = _scatter(ok_base, node_col, struct_col, _color_fw,
                       "Node Similarity", "Structure Similarity",
                       tooltip_extra=["qbp_name"])
        diag_data = pd.DataFrame({"x": [0.0, 1.0], "y": [0.0, 1.0]})
        diag = (alt.Chart(diag_data)
                .mark_line(strokeDash=[6, 4], color="#bbb", strokeWidth=1.2)
                .encode(x="x:Q", y="y:Q"))
        st.altair_chart(sc1 + diag, use_container_width=True)

        st.divider()
        st.markdown("**Node Similarity vs GED**")
        st.caption("Expect negative correlation — higher similarity should mean lower GED.")
        st.altair_chart(
            _scatter(ok_base, node_col, ged_col, _color_fw,
                     "Node Similarity", "GED", tooltip_extra=["qbp_name"]),
            use_container_width=True,
        )

        st.divider()
        st.markdown("**Run-to-run consistency — Coefficient of Variation**")
        st.caption("CV = SD / Mean × 100. Lower = more reproducible.")
        if "framework" in ok_base.columns:
            cv_rows = []
            for fw, grp in ok_base.groupby("framework"):
                for col, lbl in [(node_col, "Node Sim"),
                                 (struct_col, "Struct Sim"),
                                 (ged_col, "GED")]:
                    m = grp[col].mean()
                    cv = (grp[col].std() / m * 100) if m else 0
                    cv_rows.append({"Framework": fw, "Metric": lbl,
                                    "CV (%)": round(cv, 2)})
            cv_chart = (
                alt.Chart(pd.DataFrame(cv_rows))
                .mark_bar()
                .encode(
                    x=alt.X("Metric:N", title=None),
                    xOffset="Framework:N",
                    y=alt.Y("CV (%):Q"),
                    color=alt.Color("Framework:N"),
                    tooltip=["Framework:N", "Metric:N",
                             alt.Tooltip("CV (%):Q", format=".2f")],
                )
                .properties(height=250)
            )
            st.altair_chart(cv_chart, use_container_width=True)

        st.divider()
        st.markdown("**Run trends** — does score change across successive attempts?")
        st.caption("Useful to detect warm-up effects. Shaded band = ± 1 SD.")
        tr_cols = st.columns([2, 2, 3])
        with tr_cols[0]:
            trend_grp = st.selectbox(
                "Group by", ["Framework", "Model", "Framework × Model"],
                key="d_trend_group",
            )
        with tr_cols[1]:
            trend_metric = st.selectbox(
                "Metric",
                ["Node Similarity", "Structure Similarity", "GED"],
                key="d_trend_metric",
            )
        trend_col_x = {"Framework": "framework", "Model": "model",
                       "Framework × Model": "_fw_model"}.get(trend_grp, "framework")
        trend_col_y = {"Node Similarity": node_col, "Structure Similarity": struct_col,
                       "GED": ged_col}[trend_metric]
        tc = _run_trend_chart(ok_base, trend_col_x, trend_col_y, trend_metric)
        if tc:
            st.altair_chart(tc, use_container_width=True)
        else:
            st.info("Run trends require `attempt_number` data with ≥ 2 distinct values.")

    # ════════════════════════════════════════════════
    # 6. STATISTICS & DATA
    # ════════════════════════════════════════════════
    with t_data:
        grouped, fw_grouped = _build_grouped(ok_base, node_col, struct_col, ged_col)

        tbl_a, tbl_b = st.columns(2)
        with tbl_a:
            st.markdown("**Per (QBP × Framework × Model)**")
            st.dataframe(
                grouped.drop(columns=["group"], errors="ignore").round(4),
                use_container_width=True, hide_index=True, height=340,
            )
        with tbl_b:
            st.markdown("**Framework-level summary**")
            st.dataframe(fw_grouped.round(4),
                         use_container_width=True, hide_index=True, height=340)

        st.divider()
        with st.expander("🗄  All filtered runs — raw detail", expanded=False):
            raw_cols = [
                "batch_id", "attempt_number", "qbp_name", "framework", "model",
                "status", "elapsed_seconds",
                "node_sim", "struct_sim", "ged",
                "node_sim_dedup", "struct_sim_dedup", "ged_dedup",
                "promoai_retries", "error",
            ]
            avail_raw = [c for c in raw_cols if c in ok_base.columns]
            df_raw = ok_base[avail_raw].copy()
            if "status" in df_raw.columns:
                df_raw["status"] = df_raw["status"].map(
                    lambda s: f"{STATUS_ICON.get(s, '⚪')} {s}"
                )
            st.dataframe(df_raw.round(4), use_container_width=True,
                         height=400, hide_index=True)

        st.divider()
        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            st.download_button(
                "⬇️ Grouped stats CSV",
                data=grouped.drop(columns=["group"], errors="ignore").to_csv(index=False),
                file_name="grouped_statistics.csv", mime="text/csv",
                use_container_width=True,
                key="dl_2",
            )
        with dl2:
            st.download_button(
                "⬇️ Framework stats CSV",
                data=fw_grouped.to_csv(index=False),
                file_name="framework_statistics.csv", mime="text/csv",
                use_container_width=True,
                key="dl_3",
            )
        with dl3:
            def _sqlite_bytes(df: pd.DataFrame) -> bytes:
                with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                    tmp_path = tmp.name
                with sqlite3.connect(tmp_path) as c:
                    df.to_sql("experiment_results", c, index=False, if_exists="replace")
                with open(tmp_path, "rb") as f:
                    data_bytes = f.read()
                os.unlink(tmp_path)
                return data_bytes
            st.download_button(
                "⬇️ Filtered runs SQLite",
                data=_sqlite_bytes(ok_base),
                file_name="filtered_results.sqlite",
                mime="application/octet-stream",
                use_container_width=True,
                key="dl_4",
            )

        with st.expander("📦 All batches in this database", expanded=False):
            if not batches_df.empty:
                st.dataframe(batches_df, use_container_width=True, hide_index=True)
            else:
                st.caption("No batches table (legacy database).")

    # ════════════════════════════════════════════════
    # 1. DISTRIBUTIONS
    # ════════════════════════════════════════════════
    with t_dist:
        st.caption(
            "Box plots show median, IQR, and whiskers (1.5× IQR). "
            "Overlaid dots are individual runs — hover for details."
        )

        group_by = st.radio(
            "Group x-axis by",
            ["Framework", "Model", "Framework × Model"],
            horizontal=True, key="dist_group",
        )
        if group_by == "Framework":
            x_col_d = "framework"
        elif group_by == "Model":
            x_col_d = "model"
        else:
            ok = ok.copy()
            ok["_fw_model"] = ok.get("framework", "") + " · " + ok.get("model", "")
            x_col_d = "_fw_model"

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Node Similarity** *(higher = better)*")
            st.altair_chart(
                _boxplot(ok, x_col_d, node_col, _color_fw or x_col_d,
                         "Node Similarity", tooltip_extra=["qbp_name", "model"]),
                use_container_width=True,
            )
        with col_b:
            st.markdown("**Structure Similarity** *(higher = better)*")
            st.altair_chart(
                _boxplot(ok, x_col_d, struct_col, _color_fw or x_col_d,
                         "Structure Similarity", tooltip_extra=["qbp_name", "model"]),
                use_container_width=True,
            )

        ged_c, rate_c = st.columns(2)
        with ged_c:
            st.markdown("**Graph Edit Distance** *(lower = better)*")
            st.altair_chart(
                _boxplot(ok, x_col_d, ged_col, _color_fw or x_col_d,
                         "GED", tooltip_extra=["qbp_name", "model"], lower_better=True),
                use_container_width=True,
            )
        with rate_c:
            st.markdown("**Run success rate**")
            rate_chart = _success_rate_chart(
                runs_df[runs_df["framework"].isin(sel_fw)]
                if sel_fw and "framework" in runs_df.columns else runs_df
            )
            if rate_chart:
                st.altair_chart(rate_chart, use_container_width=True)
            else:
                st.info("Not enough data for success-rate chart.")

        st.divider()
        st.markdown("**Mean ± 1 SD by framework**")
        ba, bb, bc = st.columns(3)
        with ba:
            st.altair_chart(_mean_with_errbar(ok, "framework", node_col,
                                              "framework", "Node Similarity"),
                            use_container_width=True)
        with bb:
            st.altair_chart(_mean_with_errbar(ok, "framework", struct_col,
                                              "framework", "Structure Similarity"),
                            use_container_width=True)
        with bc:
            st.altair_chart(_mean_with_errbar(ok, "framework", ged_col,
                                              "framework", "GED", lower_better=True),
                            use_container_width=True)

    # ════════════════════════════════════════════════
    # 2. GROUP COMPARISON  ← restored + improved
    # ════════════════════════════════════════════════
    with t_group:
        st.caption(
            "Define a *group* by combining any dimensions, then compare those groups "
            "across all three metrics. Each bar/dot = mean over all runs in that group."
        )

        # ── Group builder ────────────────────────────────────────────────
        avail_dims = {
            "Framework": "framework",
            "Model":     "model",
            "QBP":       "qbp_name",
        }
        avail_dims = {k: v for k, v in avail_dims.items() if v in ok.columns}

        gc1, gc2, gc3 = st.columns([2, 2, 2])
        with gc1:
            chosen_dims = st.multiselect(
                "Group by dimensions",
                list(avail_dims.keys()),
                default=list(avail_dims.keys()),
                key="grp_dims",
                help="Select which dimensions make up a 'group'. "
                     "E.g. Framework + Model gives one group per framework-model pair.",
            )
        with gc2:
            grp_color_dim = st.selectbox(
                "Colour by",
                chosen_dims if chosen_dims else list(avail_dims.keys()),
                key="grp_color",
                help="Which dimension drives the colour encoding.",
            )
        with gc3:
            grp_chart_type = st.selectbox(
                "Chart type",
                ["Bar + Points", "Bar + Labels", "Dot", "Diff from Min"],
                key="grp_chart_type",
            )

        if not chosen_dims:
            st.info("Select at least one dimension above.")
            st.stop()

        chosen_cols  = [avail_dims[d] for d in chosen_dims]
        color_col_gc = avail_dims.get(grp_color_dim, chosen_cols[0])

        # Build group label column
        ok_g = ok.copy()
        ok_g["_group"] = ok_g[chosen_cols].apply(
            lambda r: " · ".join(str(r[c]) for c in chosen_cols if pd.notna(r[c])),
            axis=1,
        )
        ok_g["_color_dim"] = ok_g[color_col_gc].astype(str)

        all_groups = sorted(ok_g["_group"].unique())

        # Group filter
        sel_groups = st.multiselect(
            "Filter groups (leave empty = show all)",
            all_groups,
            default=all_groups,
            key="grp_filter",
        )
        ok_g = ok_g[ok_g["_group"].isin(sel_groups or all_groups)]

        if ok_g.empty:
            st.warning("No data for the selected groups.")
            st.stop()

        # ── Per-group stats ──────────────────────────────────────────────
        def _grp_stats(df, group_col, val_col):
            g = (
                df.groupby(group_col)[val_col]
                .agg(mean="mean", std="std", count="count",
                     min="min", max="max", median="median")
                .reset_index()
            )
            g["std"] = g["std"].fillna(0)
            g["lo"]  = g["mean"] - g["std"]
            g["hi"]  = g["mean"] + g["std"]
            # carry color_dim through for coloring
            if color_col_gc in df.columns:
                mapping = df.drop_duplicates("_group").set_index("_group")[color_col_gc]
                g[color_col_gc] = g[group_col].map(mapping)
            return g

        grp_node   = _grp_stats(ok_g, "_group", node_col)
        grp_struct = _grp_stats(ok_g, "_group", struct_col)
        grp_ged    = _grp_stats(ok_g, "_group", ged_col)

        # ── Charts — three metrics side by side ──────────────────────────
        st.divider()
        ch_a, ch_b = st.columns(2)
        with ch_a:
            st.markdown("**Node Similarity** *(higher = better)*")
            c = _group_bar(grp_node, ok_g, "_group", node_col,
                           "Node Similarity", color_col=color_col_gc,
                           chart_type=grp_chart_type)
            if c: st.altair_chart(c, use_container_width=True)

        with ch_b:
            st.markdown("**Structure Similarity** *(higher = better)*")
            c = _group_bar(grp_struct, ok_g, "_group", struct_col,
                           "Structure Similarity", color_col=color_col_gc,
                           chart_type=grp_chart_type)
            if c: st.altair_chart(c, use_container_width=True)

        st.markdown("**Graph Edit Distance** *(lower = better)*")
        gch_col, tbl_col = st.columns(2)
        with gch_col:
            c = _group_bar(grp_ged, ok_g, "_group", ged_col,
                           "GED", lower_better=True, color_col=color_col_gc,
                           chart_type=grp_chart_type)
            if c: st.altair_chart(c, use_container_width=True)

        with tbl_col:
            st.markdown("**Group statistics table**")
            st.caption("Mean ± SD, min / median / max, and run count per group.")
            stats_rows = []
            for g in sel_groups or all_groups:
                sub = ok_g[ok_g["_group"] == g]
                if sub.empty:
                    continue
                stats_rows.append({
                    "Group":         g,
                    "N":             len(sub),
                    "NodeSim mean":  round(sub[node_col].mean(), 4),
                    "NodeSim SD":    round(sub[node_col].std(),  4),
                    "Struct mean":   round(sub[struct_col].mean(), 4),
                    "Struct SD":     round(sub[struct_col].std(),  4),
                    "GED mean":      round(sub[ged_col].mean(), 4),
                    "GED SD":        round(sub[ged_col].std(),  4),
                })
            if stats_rows:
                st.dataframe(pd.DataFrame(stats_rows),
                             use_container_width=True, hide_index=True, height=320)

        # ── Faceted per-QBP breakdown ─────────────────────────────────────
        if "qbp_name" in ok_g.columns and ok_g["qbp_name"].nunique() > 1:
            st.divider()
            st.markdown("**Per-QBP breakdown** — one panel per QBP, x = group, dots = runs, tick = mean")
            fac_metric = st.radio(
                "Facet metric",
                ["Node Similarity", "Structure Similarity", "GED"],
                horizontal=True, key="grp_fac_metric",
            )
            fac_col = {
                "Node Similarity":      node_col,
                "Structure Similarity": struct_col,
                "GED":                  ged_col,
            }[fac_metric]
            fc = _facet_qbp_chart(ok_g, "_group", fac_col, fac_metric, max_cols=3)
            if fc:
                st.altair_chart(fc, use_container_width=True)
            else:
                st.info("Need ≥ 2 QBPs to show faceted view.")

    # ════════════════════════════════════════════════
    # 3. QBP ANALYSIS
    # ════════════════════════════════════════════════
    with t_qbp:
        st.caption(
            "Which QBPs are hardest? Which frameworks handle them best? "
            "Heatmap cells show mean score; rows sorted by difficulty."
        )

        if "qbp_name" not in ok.columns or ok["qbp_name"].nunique() < 1:
            st.info("QBP name column not available.")
        else:
            hm_metric = st.radio(
                "Heatmap metric",
                ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
                horizontal=True, key="qbp_hm_metric",
            )
            metric_map_qbp = {
                "Node Similarity":          (node_col,   "Node Sim",  "greens", False),
                "Structure Similarity":     (struct_col, "Struct Sim","blues",  False),
                "GED (lower = better)":     (ged_col,    "GED",       "reds",   True),
            }
            hm_col, hm_label, hm_scheme, hm_low = metric_map_qbp[hm_metric]

            st.markdown("**QBP × Framework heatmap**")
            st.altair_chart(
                _heatmap(ok, "framework", "qbp_name", hm_col,
                         "Framework", "QBP", hm_label, hm_scheme, hm_low),
                use_container_width=True,
            )

            # Second heatmap: QBP × Model (only if >1 model)
            if "model" in ok.columns and ok["model"].nunique() > 1:
                st.markdown("**QBP × Model heatmap**")
                st.altair_chart(
                    _heatmap(ok, "model", "qbp_name", hm_col,
                             "Model", "QBP", hm_label, hm_scheme, hm_low),
                    use_container_width=True,
                )

            st.divider()
            st.markdown("**Per-QBP Node Similarity distribution** *(sorted hardest → easiest)*")

            sort_order_qbp = (
                ok.groupby("qbp_name")[node_col]
                .mean().sort_values().index.tolist()
            )
            qbp_box = (
                alt.Chart(ok)
                .mark_boxplot(extent=1.5, size=16)
                .encode(
                    y=alt.Y("qbp_name:N", title=None, sort=sort_order_qbp,
                            axis=alt.Axis(labelFontSize=11)),
                    x=alt.X(f"{node_col}:Q", title="Node Similarity",
                             scale=alt.Scale(zero=False)),
                    color=alt.Color("framework:N") if "framework" in ok.columns
                          else alt.value("#4c78a8"),
                    tooltip=["qbp_name:N", "framework:N",
                             alt.Tooltip(f"{node_col}:Q", format=".4f")],
                )
                .properties(height=max(200, len(sort_order_qbp) * 32 + 60))
            )
            st.altair_chart(qbp_box, use_container_width=True)

    # ════════════════════════════════════════════════
    # 4. DEDUP IMPACT
    # ════════════════════════════════════════════════
    with t_dedup:
        if not has_dedup:
            st.info(
                "No post-dedup scores found. Enable **Duplicate Handling** on an "
                "experiment card and re-run to see this analysis.",
                icon="ℹ️",
            )
        else:
            dedup_ok = ok.dropna(subset=["node_sim", "node_sim_dedup"]).copy()

            if dedup_ok.empty:
                st.warning("No runs have both pre and post-dedup scores.")
            else:
                dedup_metric = st.radio(
                    "Metric",
                    ["Node Similarity", "Structure Similarity", "GED (lower = better)"],
                    horizontal=True, key="dedup_metric",
                )
                dmap = {
                    "Node Similarity":          ("node_sim",   "node_sim_dedup",   "Node Similarity"),
                    "Structure Similarity":     ("struct_sim", "struct_sim_dedup", "Structure Similarity"),
                    "GED (lower = better)":     ("ged",        "ged_dedup",        "GED"),
                }
                d_pre, d_post, d_label = dmap[dedup_metric]

                st.markdown(
                    "**Slope chart** — thin lines = individual runs, thick = group mean. "
                    "Upward slope = dedup improved the score."
                )
                slope = _slope_chart(dedup_ok, d_pre, d_post, "framework", y_label=d_label)
                if slope:
                    st.altair_chart(slope, use_container_width=True)

                st.divider()
                dcol_a, dcol_b = st.columns(2)

                with dcol_a:
                    st.markdown("**Per-run delta** *(post − pre)*")
                    st.caption("🟢 improved · ⚫ unchanged · 🔴 worsened")
                    dstrip = _delta_strip(dedup_ok, d_pre, d_post, "framework",
                                         y_label=f"Δ {d_label}")
                    if dstrip:
                        st.altair_chart(dstrip, use_container_width=True)

                with dcol_b:
                    st.markdown("**Mean Δ by framework**")
                    delta_grp = (
                        dedup_ok
                        .assign(_delta=dedup_ok[d_post] - dedup_ok[d_pre])
                        .groupby("framework")["_delta"]
                        .agg(mean_delta="mean", std_delta="std", n="count")
                        .reset_index()
                    )
                    delta_grp["% Improved"] = (
                        dedup_ok
                        .assign(_delta=dedup_ok[d_post] - dedup_ok[d_pre])
                        .groupby("framework")["_delta"]
                        .apply(lambda s: (s > 1e-6).mean() * 100)
                        .values
                    )
                    delta_grp.columns = ["Framework", "Mean Δ", "SD Δ", "N", "% Improved"]
                    st.dataframe(delta_grp.round(3), use_container_width=True, hide_index=True)

                    bar_d = (
                        alt.Chart(delta_grp)
                        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                        .encode(
                            x=alt.X("Framework:N", title=None,
                                    axis=alt.Axis(labelAngle=-20)),
                            y=alt.Y("Mean Δ:Q"),
                            color=alt.condition(
                                "datum['Mean Δ'] >= 0",
                                alt.value("#2ca02c"), alt.value("#d62728"),
                            ),
                            tooltip=["Framework:N",
                                     alt.Tooltip("Mean Δ:Q",    format="+.4f"),
                                     alt.Tooltip("% Improved:Q", format=".1f")],
                        )
                        .properties(height=200)
                    )
                    rule_d = (
                        alt.Chart(pd.DataFrame({"y": [0]}))
                        .mark_rule(color="#999")
                        .encode(y="y:Q")
                    )
                    st.altair_chart(bar_d + rule_d, use_container_width=True)

    # ════════════════════════════════════════════════
    # 5. CORRELATION & TRENDS
    # ════════════════════════════════════════════════
    with t_corr:
        sc_a, sc_b = st.columns(2)

        with sc_a:
            st.markdown("**Node Sim vs Structure Sim**")
            st.caption("Diagonal = perfect agreement. Off-diagonal = metrics disagree.")
            sc = _scatter(ok, node_col, struct_col, _color_fw or "framework",
                          "Node Similarity", "Structure Similarity",
                          tooltip_extra=["qbp_name"])
            diag_data = pd.DataFrame({"x": [0.0, 1.0], "y": [0.0, 1.0]})
            diag = (
                alt.Chart(diag_data)
                .mark_line(strokeDash=[6, 4], color="#aaa", strokeWidth=1.2)
                .encode(x="x:Q", y="y:Q")
            )
            st.altair_chart(sc + diag, use_container_width=True)

        with sc_b:
            st.markdown("**Node Sim vs GED**")
            st.caption("Expect negative correlation — higher sim should mean lower GED.")
            sc2 = _scatter(ok, node_col, ged_col, _color_fw or "framework",
                           "Node Similarity", "GED",
                           tooltip_extra=["qbp_name"])
            st.altair_chart(sc2, use_container_width=True)

        st.divider()
        st.markdown("**Coefficient of Variation — run consistency per framework**")
        st.caption("Lower CV = more reproducible results. High CV = high variance across runs.")

        if "framework" in ok.columns:
            cv_rows = []
            for fw, grp in ok.groupby("framework"):
                for col, lbl in [
                    (node_col,   "Node Sim"),
                    (struct_col, "Struct Sim"),
                    (ged_col,    "GED"),
                ]:
                    m = grp[col].mean()
                    s = grp[col].std()
                    cv = (s / m * 100) if m and m != 0 else 0
                    cv_rows.append({"Framework": fw, "Metric": lbl, "CV (%)": round(cv, 2)})

            cv_df = pd.DataFrame(cv_rows)
            cv_chart = (
                alt.Chart(cv_df)
                .mark_bar()
                .encode(
                    x=alt.X("Metric:N", title=None),
                    xOffset="Framework:N",
                    y=alt.Y("CV (%):Q"),
                    color=alt.Color("Framework:N"),
                    tooltip=["Framework:N", "Metric:N",
                             alt.Tooltip("CV (%):Q", format=".2f")],
                )
                .properties(height=260)
            )
            st.altair_chart(cv_chart, use_container_width=True)

        st.divider()
        st.markdown("**Run-to-run trends** — does score change across successive attempts?")
        st.caption(
            "Useful to detect warm-up effects (early runs scoring lower) or "
            "model drift (later runs scoring differently). "
            "Shaded band = ± 1 SD."
        )

        trend_group = st.radio(
            "Trend group by",
            ["Framework", "Model", "Framework × Model"],
            horizontal=True, key="trend_group",
        )
        if trend_group == "Framework":
            trend_col = "framework"
        elif trend_group == "Model":
            trend_col = "model"
        else:
            ok = ok.copy()
            if "_fw_model" not in ok.columns:
                ok["_fw_model"] = ok.get("framework", "") + " · " + ok.get("model", "")
            trend_col = "_fw_model"

        tr_metric = st.radio(
            "Trend metric",
            ["Node Similarity", "Structure Similarity", "GED"],
            horizontal=True, key="trend_metric",
        )
        tr_col = {
            "Node Similarity":      node_col,
            "Structure Similarity": struct_col,
            "GED":                  ged_col,
        }[tr_metric]

        trend_chart = _run_trend_chart(ok, trend_col, tr_col, tr_metric)
        if trend_chart:
            st.altair_chart(trend_chart, use_container_width=True)
        else:
            st.info(
                "Run trends need `attempt_number` data and ≥ 2 distinct attempt indices. "
                "This is available when experiments are run with the current pipeline."
            )

    # ════════════════════════════════════════════════
    # 6. STATISTICS & DATA
    # ════════════════════════════════════════════════
    with t_data:

        grouped, fw_grouped = _build_grouped(ok, node_col, struct_col, ged_col)

        tbl_a, tbl_b = st.columns(2)
        with tbl_a:
            st.markdown("**Per (QBP × Framework × Model)**")
            st.dataframe(
                grouped.drop(columns=["group"], errors="ignore").round(4),
                use_container_width=True, hide_index=True, height=340,
            )
        with tbl_b:
            st.markdown("**Framework-level summary**")
            st.dataframe(fw_grouped.round(4),
                         use_container_width=True, hide_index=True, height=340)

        st.divider()

        with st.expander("🗄  All filtered runs — raw detail", expanded=False):
            raw_cols = [
                "batch_id", "attempt_number", "qbp_name", "framework", "model",
                "status", "elapsed_seconds",
                "node_sim", "struct_sim", "ged",
                "node_sim_dedup", "struct_sim_dedup", "ged_dedup",
                "promoai_retries", "error",
            ]
            avail = [c for c in raw_cols if c in ok.columns]
            df_raw = ok[avail].copy()
            if "status" in df_raw.columns:
                df_raw["status"] = df_raw["status"].map(
                    lambda s: f"{STATUS_ICON.get(s,'⚪')} {s}"
                )
            st.dataframe(df_raw.round(4), use_container_width=True,
                         height=420, hide_index=True)

        st.divider()
        st.markdown("**Downloads**")
        dl1, dl2, dl3 = st.columns(3)

        with dl1:
            st.download_button(
                "⬇️ Grouped stats CSV",
                data=grouped.drop(columns=["group"], errors="ignore").to_csv(index=False),
                file_name="grouped_statistics.csv", mime="text/csv",
                use_container_width=True,
                key="dl_5",
            )
        with dl2:
            st.download_button(
                "⬇️ Framework stats CSV",
                data=fw_grouped.to_csv(index=False),
                file_name="framework_statistics.csv", mime="text/csv",
                use_container_width=True,
                key="dl_6",
            )
        with dl3:
            def _sqlite_bytes(df: pd.DataFrame) -> bytes:
                with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                    tmp_path = tmp.name
                with sqlite3.connect(tmp_path) as c:
                    df.to_sql("experiment_results", c, index=False, if_exists="replace")
                with open(tmp_path, "rb") as f:
                    data_bytes = f.read()
                os.unlink(tmp_path)
                return data_bytes

            st.download_button(
                "⬇️ Filtered runs SQLite",
                data=_sqlite_bytes(ok),
                file_name="filtered_results.sqlite",
                mime="application/octet-stream",
                use_container_width=True,
                key="dl_7",
            )

        with st.expander("📦 All batches in this database", expanded=False):
            if not batches_df.empty:
                st.dataframe(batches_df, use_container_width=True, hide_index=True)
            else:
                st.caption("No batches table (legacy database).")