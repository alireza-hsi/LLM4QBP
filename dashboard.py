import streamlit as st
import pandas as pd
import sqlite3
import altair as alt
import io
import tempfile

st.title("Experiment Results Dashboard")

# Load data
conn = sqlite3.connect("resultsDb.sqlite")
df = pd.read_sql("SELECT * FROM experiment_results", conn)
conn.close()

# Remove rows with null values in any of the score columns
df = df.dropna(subset=['node_similarity', 'structure_similarity', 'graph_edit_distance'])

# Extract just the filename from the gold_bpmn_path for grouping
df['gold_bpmn_name'] = df['gold_bpmn_path'].apply(lambda x: x.split('/')[-1] if isinstance(x, str) else x)

# Pre-grouped for sidebar options (before filtering)
pre_grouped = df.groupby(['qbp_name', 'framework', 'model', 'gold_bpmn_name']).size().reset_index()

# Sidebar filters (add gold_bpmn_name)
qbp_names = st.sidebar.multiselect(
    "QBP Name",
    options=pre_grouped['qbp_name'].unique(),
    default=pre_grouped['qbp_name'].unique()
)
frameworks = st.sidebar.multiselect(
    "Framework",
    options=pre_grouped['framework'].unique(),
    default=pre_grouped['framework'].unique()
)
models = st.sidebar.multiselect(
    "Model",
    options=pre_grouped['model'].unique(),
    default=pre_grouped['model'].unique()
)
gold_bpmn_names = st.sidebar.multiselect(
    "Gold BPMN",
    options=pre_grouped['gold_bpmn_name'].unique(),
    default=pre_grouped['gold_bpmn_name'].unique()
)

# Filter the original DataFrame based on sidebar selections
df_filtered = df[
    df['qbp_name'].isin(qbp_names) &
    df['framework'].isin(frameworks) &
    df['model'].isin(models) &
    df['gold_bpmn_name'].isin(gold_bpmn_names)
]

# Grouped statistics (now includes gold_bpmn_name)
grouped = df_filtered.groupby(['qbp_name', 'framework', 'model', 'gold_bpmn_name']).agg(
    runs=('id', 'count'),
    node_sim_min=('node_similarity', 'min'),
    node_sim_max=('node_similarity', 'max'),
    node_sim_mean=('node_similarity', 'mean'),
    node_sim_median=('node_similarity', 'median'),
    struct_sim_min=('structure_similarity', 'min'),
    struct_sim_max=('structure_similarity', 'max'),
    struct_sim_mean=('structure_similarity', 'mean'),
    struct_sim_median=('structure_similarity', 'median'),
    ged_min=('graph_edit_distance', 'min'),
    ged_max=('graph_edit_distance', 'max'),
    ged_mean=('graph_edit_distance', 'mean'),
    ged_median=('graph_edit_distance', 'median'),
).reset_index()

# Framework-level statistics
framework_grouped = df_filtered.groupby(['framework']).agg(
    runs=('id', 'count'),
    node_sim_min=('node_similarity', 'min'),
    node_sim_max=('node_similarity', 'max'),
    node_sim_mean=('node_similarity', 'mean'),
    node_sim_median=('node_similarity', 'median'),
    struct_sim_min=('structure_similarity', 'min'),
    struct_sim_max=('structure_similarity', 'max'),
    struct_sim_mean=('structure_similarity', 'mean'),
    struct_sim_median=('structure_similarity', 'median'),
    ged_min=('graph_edit_distance', 'min'),
    ged_max=('graph_edit_distance', 'max'),
    ged_mean=('graph_edit_distance', 'mean'),
    ged_median=('graph_edit_distance', 'median'),
).reset_index()

# Add a group label column for plotting (now includes gold_bpmn_name)
grouped['group'] = (
    grouped['qbp_name'] + " | " +
    grouped['framework'] + " | " +
    grouped['model'] + " | " +
    grouped['gold_bpmn_name']
)

# Show statistics table
st.subheader("Grouped Statistics Table")
st.dataframe(grouped)

# Show framework-level statistics table
st.subheader("Framework-Level Statistics Table")
st.dataframe(framework_grouped)

# Download button for grouped statistics
st.download_button(
    label="Download grouped statistics as CSV",
    data=grouped.to_csv(index=False),
    file_name="experiment_grouped_statistics.csv",
    mime="text/csv"
)

# Download button for framework-level statistics
st.download_button(
    label="Download framework-level statistics as CSV",
    data=framework_grouped.to_csv(index=False),
    file_name="experiment_framework_statistics.csv",
    mime="text/csv"
)

# Download filtered data as a new SQLite database
def get_sqlite_bytes(filtered_df):
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        with sqlite3.connect(tmp.name) as conn:
            filtered_df.to_sql('experiment_results', conn, index=False, if_exists='replace')
        tmp.seek(0)
        return io.BytesIO(tmp.read())

sqlite_bytes = get_sqlite_bytes(df_filtered)
st.download_button(
    label="Download filtered data as SQLite DB",
    data=sqlite_bytes,
    file_name="filtered_experiment_results.sqlite",
    mime="application/octet-stream"
)

# --- Grouped (per QBP/model/gold_bpmn_name) chart functions ---
def altair_grouped_bar_chart(metric, y_label):
    chart = alt.Chart(grouped).mark_bar().encode(
        x=alt.X('group:N', sort=None, title="Group"),
        y=alt.Y(f'{metric}:Q', title=y_label),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_grouped_dot_chart(metric, y_label):
    min_val = grouped[metric].min()
    max_val = grouped[metric].max()
    margin = (max_val - min_val) * 0.1 if max_val > min_val else 0.01
    chart = alt.Chart(grouped).mark_circle(size=200).encode(
        x=alt.X('group:N', sort=None, title="Group"),
        y=alt.Y(f'{metric}:Q', title=y_label, scale=alt.Scale(domain=[min_val - margin, max_val + margin])),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_grouped_diff_chart(metric, y_label):
    baseline = grouped[metric].min()
    grouped['diff'] = grouped[metric] - baseline
    chart = alt.Chart(grouped).mark_bar().encode(
        x=alt.X('group:N', sort=None, title="Group"),
        y=alt.Y('diff:Q', title=f"{y_label} (Difference from Min)"),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_grouped_bar_chart_with_labels(metric, y_label):
    bar = alt.Chart(grouped).mark_bar().encode(
        x=alt.X('framework:N', sort=None, title="Framework"),
        xOffset='qbp_name:N',  # <-- Add this for grouped bars
        y=alt.Y(f'{metric}:Q', title=y_label),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    )
    text = alt.Chart(grouped).mark_text(
        align='center',
        baseline='bottom',
        dy=-2,
        fontSize=13
    ).encode(
        x=alt.X('framework:N', sort=None),
        xOffset='qbp_name:N',  # <-- Add this for grouped bars
        y=alt.Y(f'{metric}:Q'),
        text=alt.Text(f'{metric}:Q', format='.2f')
    )
    chart = (bar + text).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_grouped_stacked_bar_chart_with_labels(metric, y_label):
    bar = alt.Chart(grouped).mark_bar().encode(
        x=alt.X('framework:N', sort=None, title="Framework"),
        y=alt.Y(f'{metric}:Q', title=y_label),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    )
    text = alt.Chart(grouped).mark_text(
        align='center',
        baseline='middle',
        fontSize=13,
        color='black'  # This sets the text color to black
    ).encode(
        x=alt.X('framework:N', sort=None),
        y=alt.Y(f'{metric}:Q', stack='zero'),
        text=alt.Text(f'{metric}:Q', format='.2f')
    )
    chart = (bar + text).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)
    
def show_grouped_metric(metric, y_label, chart_type):
    if chart_type == "Bar":
        altair_grouped_bar_chart(metric, y_label)
    elif chart_type == "Bar (with Value Labels)":
        altair_grouped_bar_chart_with_labels(metric, y_label)
    elif chart_type == "Stacked Bar (with Value Labels)":
        altair_grouped_stacked_bar_chart_with_labels(metric, y_label)
    elif chart_type == "Dot":
        altair_grouped_dot_chart(metric, y_label)
    elif chart_type == "Difference from Min":
        altair_grouped_diff_chart(metric, y_label)
# --- Framework-level chart functions ---
def altair_framework_bar_chart(metric, y_label):
    chart = alt.Chart(framework_grouped).mark_bar().encode(
        x=alt.X('framework:N', sort=None, title="Framework"),
        y=alt.Y(f'{metric}:Q', title=y_label),
        color=alt.Color('framework:N', legend=alt.Legend(title="Framework"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_framework_dot_chart(metric, y_label):
    min_val = framework_grouped[metric].min()
    max_val = framework_grouped[metric].max()
    margin = (max_val - min_val) * 0.1 if max_val > min_val else 0.01
    chart = alt.Chart(framework_grouped).mark_circle(size=200).encode(
        x=alt.X('framework:N', sort=None, title="Framework"),
        y=alt.Y(f'{metric}:Q', title=y_label, scale=alt.Scale(domain=[min_val - margin, max_val + margin])),
        color=alt.Color('framework:N', legend=alt.Legend(title="Framework"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def altair_framework_diff_chart(metric, y_label):
    baseline = framework_grouped[metric].min()
    framework_grouped['diff'] = framework_grouped[metric] - baseline
    chart = alt.Chart(framework_grouped).mark_bar().encode(
        x=alt.X('framework:N', sort=None, title="Framework"),
        y=alt.Y('diff:Q', title=f"{y_label} (Difference from Min)"),
        color=alt.Color('framework:N', legend=alt.Legend(title="Framework"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

def show_framework_metric(metric, y_label, chart_type):
    if chart_type == "Bar":
        altair_framework_bar_chart(metric, y_label)
    elif chart_type == "Dot":
        altair_framework_dot_chart(metric, y_label)
    elif chart_type == "Difference from Min":
        altair_framework_diff_chart(metric, y_label)

chart_types = ["Bar", "Bar (with Value Labels)", "Stacked Bar (with Value Labels)", "Dot", "Difference from Min"]



# --- Grouped (per QBP/model/gold_bpmn_name) charts with selector ---
st.subheader("Node Similarity Mean")
grouped_node_chart_type = st.selectbox(
    "Select visualization type for Node Similarity Mean (Grouped)",
    chart_types,
    key="grouped_node_chart_type"
)
show_grouped_metric('node_sim_mean', 'Node Similarity Mean', grouped_node_chart_type)

st.subheader("Structure Similarity Mean")
grouped_struct_chart_type = st.selectbox(
    "Select visualization type for Structure Similarity Mean (Grouped)",
    chart_types,
    key="grouped_struct_chart_type"
)
show_grouped_metric('struct_sim_mean', 'Structure Similarity Mean', grouped_struct_chart_type)

st.subheader("Graph Edit Distance Mean")
grouped_ged_chart_type = st.selectbox(
    "Select visualization type for Graph Edit Distance Mean (Grouped)",
    chart_types,
    key="grouped_ged_chart_type"
)
show_grouped_metric('ged_mean', 'Graph Edit Distance Mean', grouped_ged_chart_type)

# --- Framework-level charts with selector ---
st.subheader("Framework-Level Node Similarity Mean")
node_chart_type = st.selectbox(
    "Select visualization type for Node Similarity Mean",
    chart_types,
    key="node_chart_type"
)
show_framework_metric('node_sim_mean', 'Node Similarity Mean', node_chart_type)

st.subheader("Framework-Level Structure Similarity Mean")
struct_chart_type = st.selectbox(
    "Select visualization type for Structure Similarity Mean",
    chart_types,
    key="struct_chart_type"
)
show_framework_metric('struct_sim_mean', 'Structure Similarity Mean', struct_chart_type)

st.subheader("Framework-Level Graph Edit Distance Mean")
ged_chart_type = st.selectbox(
    "Select visualization type for Graph Edit Distance Mean",
    chart_types,
    key="ged_chart_type"
)
show_framework_metric('ged_mean', 'Graph Edit Distance Mean', ged_chart_type)