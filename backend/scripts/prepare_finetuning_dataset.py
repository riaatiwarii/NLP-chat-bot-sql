#!/usr/bin/env python
"""
Manual Fine-Tuning Dataset Exporter Script
STRICTLY A STANDALONE MANUAL CLI TOOL — NEVER CALLED AUTOMATICALLY BY THE BACKEND PIPELINE.

Converts collected feedback records from backend/app/data/feedback_dataset.jsonl into:
1. Supervised Fine-Tuning (SFT) dataset (jsonl) for LoRA / bitsandbytes / peft / axolotl.
2. Direct Preference Optimization (DPO) preference dataset (jsonl) for trl.

Checks that feedback_dataset.jsonl contains at least MIN_EXAMPLES (default 300) before proceeding.
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Force UTF-8 output encoding for Windows command line compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import config

def main():
    parser = argparse.ArgumentParser(description="Prepare SFT & DPO datasets from collected pipeline feedback.")
    parser.add_argument("--min-examples", type=int, default=config.MIN_FINETUNING_EXAMPLES,
                        help=f"Minimum required feedback examples (default: {config.MIN_FINETUNING_EXAMPLES})")
    parser.add_argument("--input-file", type=str, default=str(config.FEEDBACK_DATASET_PATH),
                        help="Path to feedback_dataset.jsonl input log file")
    parser.add_argument("--output-dir", type=str, default=str(config.DATA_DIR / "finetuning_export"),
                        help="Directory to save generated SFT and DPO dataset JSONL files")
    parser.add_argument("--force", action="store_true", help="Bypass minimum examples check")

    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)

    print("=" * 70)
    print(" MANUAL FINE-TUNING DATASET PREPARATION TOOL")
    print("=" * 70)

    if not input_path.exists():
        print(f"[X] Error: Feedback dataset log file does not exist at '{input_path}'")
        print("    The system is currently in the data-collection phase. Run queries and collect feedback first.")
        sys.exit(1)

    # Read and parse feedback dataset records
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Count valid SQL correction / positive examples
    valid_examples = [r for r in records if r.get("type") in ["logic_correction", "positive_feedback"] and r.get("correct_SQL")]
    count = len(valid_examples)

    print(f"Collected Examples Count : {count}")
    print(f"Required Minimum Threshold: {args.min_examples}")

    if count < args.min_examples and not args.force:
        print("\n[!] ABORTING DATASET PREPARATION:")
        print(f"    feedback_dataset.jsonl contains {count} valid examples, which is below the threshold of {args.min_examples}.")
        print("    We are currently in the data-collection phase. Continue collecting production queries & analyst feedback.")
        print("    (To override this check for testing, pass the '--force' flag).")
        sys.exit(1)

    print("\n[+] Minimum example threshold satisfied or forced! Formatting SFT & DPO datasets...")
    output_dir.mkdir(parents=True, exist_ok=True)

    sft_file = output_dir / "sft_dataset.jsonl"
    dpo_file = output_dir / "dpo_dataset.jsonl"

    sft_count = 0
    dpo_count = 0

    with open(sft_file, "w", encoding="utf-8") as f_sft, open(dpo_file, "w", encoding="utf-8") as f_dpo:
        for rec in valid_examples:
            question = rec.get("question", "")
            correct_sql = rec.get("correct_SQL", "")
            wrong_sql = rec.get("wrong_SQL", "")

            # SFT Format
            sft_entry = {
                "instruction": "Convert the following natural language query into valid executable SQL.",
                "input": question,
                "output": f"```sql\n{correct_sql}\n```"
            }
            f_sft.write(json.dumps(sft_entry) + "\n")
            sft_count += 1

            # DPO Format
            if wrong_sql and wrong_sql != correct_sql:
                dpo_entry = {
                    "prompt": f"Convert the query to SQL: {question}",
                    "chosen": correct_sql,
                    "rejected": wrong_sql
                }
                f_dpo.write(json.dumps(dpo_entry) + "\n")
                dpo_count += 1

    print(f"\n[+] DATASET PREPARATION COMPLETE!")
    print(f"    SFT Dataset Saved ({sft_count} examples): {sft_file}")
    print(f"    DPO Dataset Saved ({dpo_count} preference pairs): {dpo_file}")
    print(f"    Target Model: {config.OLLAMA_MODEL}")
    print("    Fine-tuning wrapper framework: peft + bitsandbytes (4-bit LoRA) & trl / axolotl")
    print("=" * 70)

if __name__ == "__main__":
    main()
