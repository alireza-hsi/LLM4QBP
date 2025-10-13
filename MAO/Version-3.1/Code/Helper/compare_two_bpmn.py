import os
from bpmn_compare_similarity import CompareBPMN

# Paths to your .bpmn files
bpmn_file_1 = "/Users/alireza/Desktop/DTI/Thesis/code experiments/Similarity_BPMN/BPMNs for test/QBP_1_.bpmn"
bpmn_file_2 = "/Users/alireza/Desktop/DTI/Thesis/code experiments/Similarity_BPMN/BPMNs for test/QBP1_v1_Take12_changeName.bpmn"

# Create an instance of the comparison class
comparator = CompareBPMN(export_csv=False, export_excel=False)

# Run the comparison and capture all results
node_sim, structure_sim, graph_edit_distance = comparator.calculate_similarity(bpmn_file_1, bpmn_file_2)

# Extract file names from paths for a cleaner display
file1 = os.path.basename(bpmn_file_1)
file2 = os.path.basename(bpmn_file_2)

# Final formatted output with an extra row for Graph Edit Distance
print("\n===================================")
print("      BPMN Similarity Results      ")
print("===================================")
print(f"Files Compared:        '{file1}' vs. '{file2}'")
print(f"Node Similarity:       {node_sim:.3f}")
print(f"Structure Similarity:  {structure_sim:.3f}")
print(f"Graph Edit Distance:   {graph_edit_distance}")
print("===================================\n")
