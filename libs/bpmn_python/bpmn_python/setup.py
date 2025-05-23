from setuptools import setup

setup(
    name="bpmn_python",
    version="0.0.18",
    py_modules=[
        "bpmn_diagram_exception",
        "bpmn_diagram_export",
        "bpmn_diagram_import",
        "bpmn_diagram_layouter",
        "bpmn_diagram_metrics",
        "bpmn_diagram_rep",
        "bpmn_diagram_visualizer",
        "bpmn_import_utils",
        "bpmn_process_csv_export",
        "bpmn_process_csv_import",
        "bpmn_python_consts",
        "diagram_layout_metrics",
        "grid_cell_class"
    ],
    description="Vendored, patched bpmn_python",
)