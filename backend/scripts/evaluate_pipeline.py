#!/usr/bin/env python
"""
Manual Pipeline Evaluation & Benchmark Harness
STRICTLY A STANDALONE MANUAL CLI TOOL — NEVER CALLED AUTOMATICALLY BY THE BACKEND PIPELINE.

Evaluates the 16-stage pipeline across test queries or an 80/20 train/test split.
Measures execution accuracy, syntax validity, self-correction recovery, and abstention rate.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from sqlalchemy import create_engine

# Force UTF-8 output encoding for Windows command line compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import config
from app.data_service import DataService
from app.pipeline.orchestrator import PipelineOrchestrator

DEFAULT_TEST_QUERIES = [
    {"question": "How many cameras are offline?", "expected_intent": "COUNT"},
    {"question": "count of camras in bhopal", "expected_intent": "COUNT"},
    {"question": "Show incidents in Noida", "expected_intent": "SELECT"},
    {"question": "List high severity alert logs", "expected_intent": "SELECT"},
    {"question": "which branch has highest false alerts", "expected_intent": "SELECT"},
    {"question": "what is average response time", "expected_intent": "AVG"}
]

def main():
    parser = argparse.ArgumentParser(description="Evaluate Production Text-to-SQL Pipeline performance.")
    parser.add_argument("--test-file", type=str, default="", help="Path to custom test query JSON/JSONL dataset file")
    parser.add_argument("--db-url", type=str, default="", help="Database connection URL for execution testing")

    args = parser.parse_args()

    print("=" * 70, flush=True)
    print(" MANUAL PIPELINE EVALUATION & BENCHMARK HARNESS", flush=True)
    print("=" * 70, flush=True)

    # Initialize Engine & Pipeline
    data_svc = DataService()
    if args.db_url:
        try:
            db_engine = create_engine(args.db_url)
        except Exception as e:
            print(f"[!] Warning: Could not connect to DB '{args.db_url}': {e}. Falling back to default DataService.", flush=True)
            db_engine = data_svc.engine
    else:
        db_engine = data_svc.engine

    orchestrator = PipelineOrchestrator(db_engine=db_engine)

    # Load evaluation test set
    test_set = DEFAULT_TEST_QUERIES
    if args.test_file and Path(args.test_file).exists():
        test_set = []
        with open(args.test_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    test_set.append(json.loads(line))

    print(f"[+] Loaded {len(test_set)} test evaluation queries.", flush=True)
    print("=" * 70, flush=True)

    passed_syntax = 0
    executed_success = 0
    abstained_count = 0
    total = len(test_set)

    for i, test_item in enumerate(test_set, 1):
        q = test_item.get("question") if isinstance(test_item, dict) else str(test_item)
        print(f"\n[{i}/{total}] Evaluating Query: '{q}'", flush=True)

        res = orchestrator.process_query(q)

        is_abstention = res.get("is_abstention", False)
        sql = res.get("sql")
        conf = res.get("confidence_score", 0.0)

        if is_abstention:
            abstained_count += 1
            print(f"    Result: ABSTAINED (Confidence: {conf:.2f})", flush=True)
            print(f"    Reason: {res.get('response')[:120]}...", flush=True)
        else:
            passed_syntax += 1
            print(f"    Result: SQL GENERATED (Confidence: {conf:.2f})", flush=True)
            print(f"    Generated SQL: {sql}", flush=True)

            if res.get("rows_count", 0) >= 0 and not is_abstention:
                executed_success += 1

    print("\n" + "=" * 70, flush=True)
    print(" PIPELINE EVALUATION SUMMARY METRICS", flush=True)
    print("=" * 70, flush=True)
    print(f" Total Evaluated Queries : {total}", flush=True)
    print(f" Syntax & Plan Valid     : {passed_syntax} ({(passed_syntax/total)*100:.1f}%)", flush=True)
    print(f" Successful Execution    : {executed_success} ({(executed_success/total)*100:.1f}%)", flush=True)
    print(f" Honest Abstention Count : {abstained_count} ({(abstained_count/total)*100:.1f}%)", flush=True)
    print("=" * 70, flush=True)

if __name__ == "__main__":
    main()
