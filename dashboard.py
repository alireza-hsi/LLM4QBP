"""
Lightweight experiment results dashboard (standalone).

Run:  streamlit run dashboard.py

Batch selection, metric source (pre- vs post-dedup), distributions and bar charts with
configurable grouping (framework, model, QBP, gold BPMN, batch, …), heatmaps, optional
dedup views, and exports.
"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

# ── Page ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Experiment Results",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_DB = "resultsDb.sqlite"


def _available_dimensions(ok: pd.DataFrame, has_batch: bool) -> list[tuple[str, str]]:
    """(label, column_name) for grouping dimensions present in `ok`."""
    opts: list[tuple[str, str]] = []
    if "framework" in ok.columns:
        opts.append(("Framework", "framework"))
    if "model" in ok.columns:
        opts.append(("Model (LLM)", "model"))
    if "qbp_name" in ok.columns:
        opts.append(("QBP", "qbp_name"))
    if "gold_bpmn_name" in ok.columns:
        opts.append(("Gold BPMN", "gold_bpmn_name"))
    if "framework" in ok.columns and "model" in ok.columns:
        opts.append(("Framework × Model", "_fw_model"))
    if has_batch and "batch_id" in ok.columns:
        opts.append(("Batch", "batch_id"))
    return opts


# ── DB loading (aligned with streamlit_runner) ───────────────────────────────

def _normalise_runs(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "node_similarity": "node_sim",
        "structure_similarity": "struct_sim",
        "graph_edit_distance": "ged",
        "gold_bpmn_path": "gold_bpmn",
        "generated_bpmn_path": "generated_bpmn",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "status" not in df.columns:
        df["status"] = "ok"
    if "gold_bpmn" in df.columns:
        df["gold_bpmn_name"] = df["gold_bpmn"].apply(
            lambda x: os.path.basename(x) if isinstance(x, str) else x
        )
    else:
        df["gold_bpmn_name"] = None
    return df


def _load_db(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
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


def _build_grouped(
    ok_df: pd.DataFrame, node_col: str, struct_col: str, ged_col: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    group_keys = [k for k in ("qbp_name", "framework", "model", "gold_bpmn_name") if k in ok_df.columns]

    def _agg(by):
        return ok_df.groupby(by).agg(
            runs=("status", "count"),
            node_sim_mean=(node_col, "mean"),
            node_sim_median=(node_col, "median"),
            struct_sim_mean=(struct_col, "mean"),
            struct_sim_median=(struct_col, "median"),
            ged_mean=(ged_col, "mean"),
            ged_median=(ged_col, "median"),
        ).reset_index()

    if not group_keys:
        grouped = pd.DataFrame()
    else:
        grouped = _agg(group_keys)
        grouped["group"] = grouped.apply(
            lambda r: " | ".join(str(r[k]) for k in group_keys if pd.notna(r.get(k))),
            axis=1,
        )
    fw_grouped = _agg(["framework"]) if "framework" in ok_df.columns else pd.DataFrame()
    return grouped, fw_grouped


# ── Charts (subset from streamlit_runner) ───────────────────────────────────

def _jitter_df(df: pd.DataFrame, group_col: str, seed: int = 42) -> tuple[pd.DataFrame, list]:
    rng = np.random.default_rng(seed)
    cats = sorted(df[group_col].dropna().unique())
    cat_idx = {c: i for i, c in enumerate(cats)}
    df = df.copy()
    df["_jitter_x"] = df[group_col].map(cat_idx) + rng.uniform(-0.25, 0.25, len(df))
    return df, cats


def _boxplot(df, x_col, y_col, color_col, y_label, tooltip_extra=None, lower_better=False):
    tooltip = [
        alt.Tooltip(f"{x_col}:N"),
        alt.Tooltip(f"{y_col}:Q", format=".4f"),
    ]
    if tooltip_extra:
        tooltip += [alt.Tooltip(f"{c}:N") for c in tooltip_extra if c in df.columns]
    df_j, cats = _jitter_df(df, x_col)
    tick_vals = list(range(len(cats)))
    note = "  ↓ lower is better" if lower_better else ""
    box = (
        alt.Chart(df)
        .mark_boxplot(extent=1.5, size=38, outliers=True)
        .encode(
            x=alt.X(
                f"{x_col}:N",
                title=None,
                sort=cats,
                axis=alt.Axis(labelAngle=-30, labelFontSize=11),
            ),
            y=alt.Y(f"{y_col}:Q", title=y_label + note, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N", legend=None),
        )
    )
    dots = (
        alt.Chart(df_j)
        .mark_circle(size=28, opacity=0.55)
        .encode(
            x=alt.X(
                "_jitter_x:Q",
                title=None,
                scale=alt.Scale(domain=[-0.6, len(cats) - 0.4]),
                axis=alt.Axis(
                    values=tick_vals,
                    labelExpr=f"[{','.join(repr(c) for c in cats)}][datum.value]",
                    labelAngle=-30,
                    labelFontSize=11,
                ),
            ),
            y=alt.Y(f"{y_col}:Q", scale=alt.Scale(zero=False)),
            color=alt.Color(f"{color_col}:N"),
            tooltip=tooltip,
        )
    )
    return (box + dots).resolve_scale(x="shared").properties(height=320)


def _group_label_series(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """One label per row from ordered columns (e.g. Framework · Model · QBP)."""

    def one_row(r: pd.Series) -> str:
        parts: list[str] = []
        for c in cols:
            if c not in r.index:
                continue
            v = r[c]
            if pd.isna(v):
                continue
            parts.append(str(v))
        return " · ".join(parts) if parts else "(empty)"

    return df.apply(one_row, axis=1)


def _compute_group_stats(
    df: pd.DataFrame, group_cols: list[str], val_col: str, color_by_col: str | None
) -> pd.DataFrame:
    """Aggregate mean ± SD per combined group; optional hue column for bars."""
    d = df.copy()
    d["_group"] = _group_label_series(d, group_cols)
    agg = (
        d.groupby("_group", as_index=False)
        .agg(mean=(val_col, "mean"), std=(val_col, "std"), count=(val_col, "count"))
    )
    agg["std"] = agg["std"].fillna(0)
    agg["lo"] = agg["mean"] - agg["std"]
    agg["hi"] = agg["mean"] + agg["std"]
    if color_by_col and color_by_col in d.columns:
        first = d.groupby("_group", as_index=False).first()
        cmap = dict(zip(first["_group"].astype(str), first[color_by_col].astype(str)))
        agg["_bar_color"] = agg["_group"].astype(str).map(cmap)
    return agg


def _grouped_mean_bar_chart(
    stats: pd.DataFrame, y_label: str, lower_better: bool, use_color: bool
):
    """Vertical bars: mean ± 1 SD, optional color by `_bar_color`."""
    if stats.empty:
        return None
    sort_ord = alt.EncodingSortField("mean", order="ascending" if lower_better else "descending")
    note = "  ↓ lower is better" if lower_better else ""
    x_enc = alt.X(
        "_group:N",
        sort=sort_ord,
        title="Group",
        axis=alt.Axis(labelAngle=-35, labelFontSize=10, labelLimit=260),
    )
    y_enc = alt.Y("mean:Q", title=y_label + note, scale=alt.Scale(zero=False))
    if use_color and "_bar_color" in stats.columns and stats["_bar_color"].notna().any():
        color_enc = alt.Color("_bar_color:N", legend=alt.Legend(title="Color"))
    else:
        color_enc = alt.value("#4c78a8")
    bars = (
        alt.Chart(stats)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=x_enc,
            y=y_enc,
            color=color_enc,
            tooltip=[
                alt.Tooltip("_group:N", title="Group"),
                alt.Tooltip("mean:Q", title="Mean", format=".4f"),
                alt.Tooltip("std:Q", title="± SD", format=".4f"),
                alt.Tooltip("count:Q", title="Runs"),
            ],
        )
    )
    err_base = dict(
        x=alt.X("_group:N", sort=sort_ord),
        y=alt.Y("lo:Q"),
        y2=alt.Y2("hi:Q"),
    )
    if use_color and "_bar_color" in stats.columns and stats["_bar_color"].notna().any():
        errs = alt.Chart(stats).mark_errorbar().encode(**err_base, color=alt.Color("_bar_color:N"))
    else:
        errs = alt.Chart(stats).mark_errorbar().encode(**err_base)
    labels = (
        alt.Chart(stats)
        .mark_text(dy=-8, fontSize=10, fontWeight="bold")
        .encode(
            x=alt.X("_group:N", sort=sort_ord),
            y=y_enc,
            text=alt.Text("mean:Q", format=".3f"),
        )
    )
    n = len(stats)
    h = min(520, max(260, 28 * n))
    return (bars + errs + labels).properties(height=h)


def _heatmap(df, x_col, y_col, val_col, x_label, y_label, val_label, scheme="greens", lower_better=False):
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
            x=alt.X(f"{x_col}:N", title=x_label, axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
            y=alt.Y(
                f"{y_col}:N",
                title=y_label,
                sort=alt.EncodingSortField(
                    "mean_val", order="ascending" if lower_better else "descending"
                ),
            ),
            color=alt.Color(
                "mean_val:Q",
                title=val_label,
                scale=alt.Scale(scheme=scheme, reverse=lower_better, zero=False),
                legend=alt.Legend(format=".3f"),
            ),
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
            y=alt.Y(
                f"{y_col}:N",
                sort=alt.EncodingSortField(
                    "mean_val", order="ascending" if lower_better else "descending"
                ),
            ),
            text=alt.Text("mean_val:Q", format=".3f"),
            color=alt.condition(
                "datum.mean_val > 0.7" if not lower_better else "datum.mean_val < 50",
                alt.value("white"),
                alt.value("#333"),
            ),
        )
    )
    return (rect + text).properties(height=max(200, len(grp[y_col].unique()) * 35 + 40))


def _slope_chart(df, val_pre, val_post, group_col, y_label="Score"):
    needed = [val_pre, val_post, group_col]
    sub = df.dropna(subset=needed).copy()
    if sub.empty:
        return None
    sub["_run_id"] = sub.index.astype(str)
    label_pre, label_post = "Pre-dedup", "Post-dedup"
    long = pd.concat(
        [
            sub[[group_col, "_run_id", val_pre]].rename(columns={val_pre: "_val"}).assign(_stage=label_pre),
            sub[[group_col, "_run_id", val_post]].rename(columns={val_post: "_val"}).assign(_stage=label_post),
        ]
    ).reset_index(drop=True)
    stage_order = [label_pre, label_post]
    lines = (
        alt.Chart(long)
        .mark_line(opacity=0.25, strokeWidth=1.2)
        .encode(
            x=alt.X("_stage:O", sort=stage_order, title=None, axis=alt.Axis(labelFontSize=12)),
            y=alt.Y("_val:Q", title=y_label, scale=alt.Scale(zero=False)),
            color=alt.Color(f"{group_col}:N"),
            detail="_run_id:N",
        )
    )
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
    return (lines + mean_lines).properties(height=300)


def _delta_strip(df, val_pre, val_post, group_col, y_label="Δ (post − pre)"):
    sub = df.dropna(subset=[val_pre, val_post]).copy()
    if sub.empty:
        return None
    sub["_delta"] = sub[val_post] - sub[val_pre]
    sub["_dir"] = sub["_delta"].apply(
        lambda d: "improved" if d > 1e-6 else ("unchanged" if abs(d) < 1e-6 else "worsened")
    )
    sub_j, cats = _jitter_df(sub, group_col, seed=7)
    tick_vals = list(range(len(cats)))
    rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#999", strokeDash=[4, 3]).encode(y="y:Q")
    dots = (
        alt.Chart(sub_j)
        .mark_circle(size=40, opacity=0.7)
        .encode(
            x=alt.X(
                "_jitter_x:Q",
                title=None,
                scale=alt.Scale(domain=[-0.6, len(cats) - 0.4]),
                axis=alt.Axis(
                    values=tick_vals,
                    labelExpr=f"[{','.join(repr(c) for c in cats)}][datum.value]",
                    labelAngle=-30,
                    labelFontSize=11,
                ),
            ),
            y=alt.Y("_delta:Q", title=y_label),
            color=alt.Color(
                "_dir:N",
                scale=alt.Scale(
                    domain=["improved", "unchanged", "worsened"],
                    range=["#2ca02c", "#aaa", "#d62728"],
                ),
                legend=alt.Legend(title="Direction"),
            ),
            tooltip=[
                alt.Tooltip(f"{group_col}:N", title="Framework"),
                alt.Tooltip("_delta:Q", title="Δ", format="+.4f"),
                alt.Tooltip("_dir:N", title="Direction"),
            ]
            + ([alt.Tooltip("qbp_name:N")] if "qbp_name" in sub.columns else []),
        )
    )
    return (rule + dots).properties(height=260)


def _sqlite_bytes(filtered_df: pd.DataFrame, table_name: str) -> io.BytesIO:
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        with sqlite3.connect(tmp.name) as sconn:
            filtered_df.to_sql(table_name, sconn, index=False, if_exists="replace")
        tmp.seek(0)
        return io.BytesIO(tmp.read())


# ── App ─────────────────────────────────────────────────────────────────────

st.title("Experiment results")
st.caption("High-level view: batches, similarity metrics, and exports. Charts use **successful** runs with scores.")

sidebar = st.sidebar
sidebar.header("Data source")
db_path = sidebar.text_input("SQLite database", value=DEFAULT_DB)
if sidebar.button("Load database", type="primary"):
    st.session_state["dash_db_loaded"] = True
    st.session_state["dash_db_path"] = db_path

if not st.session_state.get("dash_db_loaded"):
    st.info("Set the database path in the sidebar and click **Load database**.")
    st.stop()

path = st.session_state.get("dash_db_path", db_path)
if not os.path.exists(path):
    st.error(f"Database not found: `{path}`")
    st.stop()

batches_df, runs_df = _load_db(path)
if runs_df.empty:
    st.warning("No run rows found.")
    st.stop()

has_batch = "batch_id" in runs_df.columns
has_dedup = "node_sim_dedup" in runs_df.columns and runs_df["node_sim_dedup"].notna().any()

sidebar.header("Scope")
if has_batch:
    bids = sorted(runs_df["batch_id"].dropna().unique(), reverse=True)
    batch_opts = ["All batches"] + [str(b) for b in bids]
    last = st.session_state.get("last_batch_id")
    default_i = 0
    if last and str(last) in batch_opts:
        default_i = batch_opts.index(str(last))
    batch_choice = sidebar.selectbox("Batch", batch_opts, index=min(default_i, len(batch_opts) - 1))
    if batch_choice != "All batches":
        runs_df = runs_df[runs_df["batch_id"].astype(str) == batch_choice].copy()
else:
    batch_choice = "All batches"

if has_dedup:
    metric_src = sidebar.radio("Metric source", ["Pre-dedup", "Post-dedup"], horizontal=True)
else:
    metric_src = "Pre-dedup"
    sidebar.caption("Post-dedup scores not present in this database.")

node_col = "node_sim_dedup" if metric_src == "Post-dedup" else "node_sim"
struct_col = "struct_sim_dedup" if metric_src == "Post-dedup" else "struct_sim"
ged_col = "ged_dedup" if metric_src == "Post-dedup" else "ged"

ok_df = runs_df[runs_df["status"] == "ok"].copy()
ok_plot = ok_df[ok_df[node_col].notna()].copy() if not ok_df.empty else ok_df


def _opts(col: str):
    return sorted(ok_plot[col].dropna().unique().tolist()) if col in ok_plot.columns else []


sidebar.header("Filters (successful runs)")
sel_fw = sidebar.multiselect("Framework", _opts("framework"), default=_opts("framework"))
sel_mdl = sidebar.multiselect("Model", _opts("model"), default=_opts("model"))
sel_qbp = sidebar.multiselect("QBP", _opts("qbp_name"), default=_opts("qbp_name"))

if ok_plot.empty:
    st.info("No successful runs with similarity scores for the current metric source.")
    with st.expander("All rows (including failures)"):
        st.dataframe(runs_df, use_container_width=True, hide_index=True)
    st.stop()

mask = pd.Series(True, index=ok_plot.index)
if sel_fw and "framework" in ok_plot.columns:
    mask &= ok_plot["framework"].isin(sel_fw)
if sel_mdl and "model" in ok_plot.columns:
    mask &= ok_plot["model"].isin(sel_mdl)
if sel_qbp and "qbp_name" in ok_plot.columns:
    mask &= ok_plot["qbp_name"].isin(sel_qbp)
ok = ok_plot[mask].copy()

if ok.empty:
    st.warning("Nothing matches the current filters.")
    st.stop()

if "framework" in ok.columns and "model" in ok.columns:
    ok["_fw_model"] = ok["framework"].astype(str) + " · " + ok["model"].astype(str)


def _fmt(s: pd.Series) -> str:
    return f"{s.mean():.4f}" if s.notna().any() else "N/A"


def _fmti(s: pd.Series) -> str:
    return f"{s.mean():.1f}" if s.notna().any() else "N/A"


n_fw = ok["framework"].nunique() if "framework" in ok.columns else 0
n_qbp = ok["qbp_name"].nunique() if "qbp_name" in ok.columns else 0

m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric("Successful runs", len(ok))
m2.metric("Total in scope", len(runs_df))
m3.metric("Frameworks", n_fw)
m4.metric("QBPs", n_qbp)
m5.metric("Avg node sim", _fmt(ok[node_col]))
m6.metric("Avg struct sim", _fmt(ok[struct_col]))
m7.metric("Avg GED", _fmti(ok[ged_col]))

st.caption(f"Batch: **{batch_choice}** · Metrics: **{metric_src}**")

tab_overview, tab_compare, tab_data = st.tabs(["Overview", "Compare (bars)", "Data & export"])

dim_opts = _available_dimensions(ok, has_batch and "batch_id" in ok.columns)
dim_labels = [lbl for lbl, _ in dim_opts]
dim_map = dict(dim_opts)
_default_dims = [x for x in ("Framework", "Model (LLM)") if x in dim_labels] or (dim_labels[:1] if dim_labels else [])

# ── Tab: Overview ──────────────────────────────────────────────────────────
with tab_overview:
    st.markdown("### Distribution (box plot)")
    st.caption(
        "Combine dimensions into one category per bar position (e.g. QBP · Model · Framework). "
        "Color can follow any column below."
    )
    row_a = st.columns([2, 1, 1])
    with row_a[0]:
        ov_dims = st.multiselect(
            "Group by (order = label order)",
            dim_labels,
            default=_default_dims,
            key="ov_dims",
            help="Select one or more: each unique combination becomes one group on the x-axis.",
        )
    with row_a[1]:
        ov_metric = st.selectbox(
            "Metric",
            ["Node similarity", "Structure similarity", "GED (lower is better)"],
            key="ov_met",
        )
    with row_a[2]:
        color_choices_ov = ["(single color)"] + [lbl for lbl in dim_labels if dim_map[lbl] in ok.columns]
        _ov_ci = 1 if len(color_choices_ov) > 1 else 0
        ov_color_lbl = st.selectbox(
            "Color points by",
            color_choices_ov,
            index=_ov_ci,
            key="ov_color",
            help="Which column drives point color (often Model or Framework).",
        )
    ov_cols = [dim_map[l] for l in ov_dims if l in dim_map]
    if not ov_cols:
        st.warning("Select at least one grouping dimension.")
    else:
        dm = {
            "Node similarity": (node_col, "Node similarity", False),
            "Structure similarity": (struct_col, "Structure similarity", False),
            "GED (lower is better)": (ged_col, "GED", True),
        }
        yc, ylab, lower = dm[ov_metric]
        ok_box = ok.copy()
        ok_box["_group"] = _group_label_series(ok_box, ov_cols)
        if ov_color_lbl == "(single color)":
            color_d = ov_cols[0]
        else:
            color_d = dim_map[ov_color_lbl]
        st.caption("Box = median and quartiles; points = individual runs.")
        st.altair_chart(
            _boxplot(
                ok_box,
                "_group",
                yc,
                color_d,
                ylab,
                tooltip_extra=["qbp_name", "model", "framework"],
                lower_better=lower,
            ),
            use_container_width=True,
        )

    if "qbp_name" in ok.columns and "framework" in ok.columns:
        st.divider()
        st.markdown("**QBP × framework** (mean score)")
        hm_metric = st.radio(
            "Heatmap metric",
            ["Node similarity", "Structure similarity", "GED"],
            horizontal=True,
            key="hm_met",
        )
        hm = {
            "Node similarity": (node_col, "Node sim", "greens", False),
            "Structure similarity": (struct_col, "Struct sim", "blues", False),
            "GED": (ged_col, "GED", "reds", True),
        }
        hcol, hlab, hscheme, hlower = hm[hm_metric]
        st.altair_chart(
            _heatmap(ok, "framework", "qbp_name", hcol, "Framework", "QBP", hlab, hscheme, hlower),
            use_container_width=True,
        )

    if has_dedup:
        st.divider()
        st.subheader("Dedup impact (pre vs post)")
        st.caption("Uses runs that have both pre- and post-dedup scores. Independent of “metric source” above.")
        dedup_ok = ok.dropna(subset=["node_sim", "node_sim_dedup"]).copy()
        if dedup_ok.empty:
            st.info("No overlapping pre/post dedup scores in the filtered data.")
        else:
            dd_pick = st.selectbox(
                "Metric",
                ["Node similarity", "Structure similarity", "GED"],
                key="dd_met",
            )
            dd_map = {
                "Node similarity": ("node_sim", "node_sim_dedup", "Node similarity"),
                "Structure similarity": ("struct_sim", "struct_sim_dedup", "Structure similarity"),
                "GED": ("ged", "ged_dedup", "GED"),
            }
            pre_c, post_c, dd_lab = dd_map[dd_pick]
            c_a, c_b = st.columns(2)
            with c_a:
                st.markdown("**Pre → post** (lines = runs, thick = mean)**")
                sl = _slope_chart(dedup_ok, pre_c, post_c, "framework", y_label=dd_lab)
                if sl:
                    st.altair_chart(sl, use_container_width=True)
            with c_b:
                st.markdown("**Per-run delta** (post − pre)")
                ds = _delta_strip(dedup_ok, pre_c, post_c, "framework", y_label=f"Δ {dd_lab}")
                if ds:
                    st.altair_chart(ds, use_container_width=True)

# ── Tab: Compare (bars) ────────────────────────────────────────────────────
with tab_compare:
    st.markdown("### Mean ± 1 SD (bar chart)")
    st.caption(
        "Same grouping idea as the box plot: pick dimensions, metric, and optional bar color. "
        "Narrow groups with the filter if the x-axis gets crowded."
    )
    b1, b2, b3 = st.columns([2, 1, 1])
    with b1:
        bar_dims = st.multiselect(
            "Group by (order = label order)",
            dim_labels,
            default=_default_dims,
            key="bar_dims",
        )
    with b2:
        bar_metric = st.selectbox(
            "Metric",
            ["Node similarity", "Structure similarity", "GED (lower is better)"],
            key="bar_met",
        )
    with b3:
        color_choices_b = ["(single color)"] + [lbl for lbl in dim_labels if dim_map[lbl] in ok.columns]
        _bi = 1 if len(color_choices_b) > 1 else 0
        bar_color_lbl = st.selectbox(
            "Color bars by",
            color_choices_b,
            index=_bi,
            key="bar_color",
        )
    bar_cols = [dim_map[l] for l in bar_dims if l in dim_map]
    if not bar_cols:
        st.warning("Select at least one grouping dimension.")
    else:
        bm = {
            "Node similarity": (node_col, "Node similarity", False),
            "Structure similarity": (struct_col, "Structure similarity", False),
            "GED (lower is better)": (ged_col, "GED", True),
        }
        b_val, b_ylab, b_lower = bm[bar_metric]
        ok_bar = ok.copy()
        ok_bar["_group"] = _group_label_series(ok_bar, bar_cols)
        all_groups = sorted(ok_bar["_group"].unique().tolist())
        sel_groups = st.multiselect(
            "Show groups",
            all_groups,
            default=all_groups,
            key="bar_groups",
            help="Hide categories you do not need on the x-axis.",
        )
        ok_bar = ok_bar[ok_bar["_group"].isin(sel_groups or all_groups)]
        if ok_bar.empty:
            st.warning("No rows left after the group filter.")
        else:
            color_by_c = None if bar_color_lbl == "(single color)" else dim_map[bar_color_lbl]
            use_hue = color_by_c is not None
            stats_df = _compute_group_stats(ok_bar, bar_cols, b_val, color_by_c)
            ch = _grouped_mean_bar_chart(stats_df, b_ylab, b_lower, use_hue)
            if ch:
                st.altair_chart(ch, use_container_width=True)
            st.markdown("**Aggregated values**")
            show_s = stats_df.copy()
            if "_bar_color" in show_s.columns:
                show_s = show_s.rename(columns={"_bar_color": "color"})
            num_cols = show_s.select_dtypes(include=["number"]).columns
            show_s[num_cols] = show_s[num_cols].round(4)
            st.dataframe(show_s, use_container_width=True, hide_index=True)

# ── Tab: Data & export ───────────────────────────────────────────────────────
with tab_data:
    grouped, fw_grouped = _build_grouped(ok, node_col, struct_col, ged_col)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "Grouped stats (CSV)",
            data=grouped.drop(columns=["group"], errors="ignore").to_csv(index=False),
            file_name="grouped_statistics.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "Framework stats (CSV)",
            data=fw_grouped.to_csv(index=False),
            file_name="framework_statistics.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            "Filtered runs (SQLite)",
            data=_sqlite_bytes(ok, "runs"),
            file_name="filtered_runs.sqlite",
            mime="application/octet-stream",
            use_container_width=True,
        )

    with st.expander("Raw successful runs (filtered)", expanded=False):
        show_raw = [
            "batch_id",
            "attempt_number",
            "qbp_name",
            "framework",
            "model",
            "status",
            "elapsed_seconds",
            "node_sim",
            "struct_sim",
            "ged",
            "node_sim_dedup",
            "struct_sim_dedup",
            "ged_dedup",
            "error",
        ]
        avail = [c for c in show_raw if c in ok.columns]
        raw_view = ok[avail].copy()
        sort_cols = [c for c in ("timestamp", "id") if c in raw_view.columns]
        if sort_cols:
            raw_view = raw_view.sort_values(sort_cols, ascending=[False] * len(sort_cols))
        st.dataframe(raw_view, use_container_width=True, hide_index=True)

    with st.expander("Batches in this file", expanded=False):
        if not batches_df.empty:
            st.dataframe(batches_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No `batches` table (legacy database).")
