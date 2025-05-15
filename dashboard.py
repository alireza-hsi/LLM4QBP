import streamlit as st
import pandas as pd
import sqlite3
import altair as alt

st.title("Experiment Results Dashboard")

# Load data
conn = sqlite3.connect("experiment_results.sqlite")
df = pd.read_sql("SELECT * FROM experiment_results", conn)
conn.close()

# Remove rows with null values in any of the score columns
df = df.dropna(subset=['node_similarity', 'structure_similarity', 'graph_edit_distance'])

# Extract just the filename from the gold_bpmn_path for grouping
df['gold_bpmn_name'] = df['gold_bpmn_path'].apply(lambda x: x.split('/')[-1] if isinstance(x, str) else x)

# Grouped statistics (now includes gold_bpmn_name)
grouped = df.groupby(['qbp_name', 'framework', 'model', 'gold_bpmn_name']).agg(
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

# Sidebar filters (add gold_bpmn_name)
qbp_names = st.sidebar.multiselect("QBP Name", options=grouped['qbp_name'].unique(), default=grouped['qbp_name'].unique())
frameworks = st.sidebar.multiselect("Framework", options=grouped['framework'].unique(), default=grouped['framework'].unique())
models = st.sidebar.multiselect("Model", options=grouped['model'].unique(), default=grouped['model'].unique())
gold_bpmn_names = st.sidebar.multiselect("Gold BPMN", options=grouped['gold_bpmn_name'].unique(), default=grouped['gold_bpmn_name'].unique())

# Filter the grouped DataFrame
filtered = grouped[
    grouped['qbp_name'].isin(qbp_names) &
    grouped['framework'].isin(frameworks) &
    grouped['model'].isin(models) &
    grouped['gold_bpmn_name'].isin(gold_bpmn_names)
]

# Add a group label column for plotting (now includes gold_bpmn_name)
filtered['group'] = (
    filtered['qbp_name'] + " | " +
    filtered['framework'] + " | " +
    filtered['model'] + " | " +
    filtered['gold_bpmn_name']
)

# Show statistics table
st.subheader("Grouped Statistics Table")
st.dataframe(filtered)

# Download button
st.download_button(
    label="Download statistics as CSV",
    data=filtered.to_csv(index=False),
    file_name="experiment_statistics.csv",
    mime="text/csv"
)

# Bar charts for means only, colored by QBP
def altair_bar_chart(metric, y_label):
    chart = alt.Chart(filtered).mark_bar().encode(
        x=alt.X('group:N', sort=None, title="Group"),
        y=alt.Y(f'{metric}:Q', title=y_label),
        color=alt.Color('qbp_name:N', legend=alt.Legend(title="QBP Name"))
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

st.subheader("Node Similarity Mean")
altair_bar_chart('node_sim_mean', 'Node Similarity Mean')

st.subheader("Structure Similarity Mean")
altair_bar_chart('struct_sim_mean', 'Structure Similarity Mean')

st.subheader("Graph Edit Distance Mean")
altair_bar_chart('ged_mean', 'Graph Edit Distance Mean')