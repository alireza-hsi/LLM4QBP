import os

from duplicateHandling import remove_safe_duplicates


BASE_DIR = "/Users/alireza/Downloads/QBP-dedup-test/HF LLM Output bpm and svg"


def main() -> None:
    for filename in os.listdir(BASE_DIR):
        if not filename.lower().endswith(".bpmn"):
            continue

        input_path = os.path.join(BASE_DIR, filename)
        output_name = f"{os.path.splitext(filename)[0]}_dedupv4.bpmn"
        output_path = os.path.join(BASE_DIR, output_name)

        cleaned_path = remove_safe_duplicates(input_path, output_path)
        print(f"Deduplicated BPMN written to: {cleaned_path}")


if __name__ == "__main__":
    main()