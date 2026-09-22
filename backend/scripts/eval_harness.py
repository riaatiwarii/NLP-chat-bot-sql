"""
Plan-correctness eval harness for the NL-to-SQL pipeline.

Purpose: catch regressions/hallucinations in the LLM-generated plan (wrong intent,
wrong dimension, missing filters, HALLUCINATED filters the user never asked for)
systematically instead of one-off manual spot checks. Also the AB-testing harness:
run the same dataset against different OLLAMA_RESPONSE_MODEL values and diff results.

Grades plan SEMANTICS (intent/dimension/filters), not exact SQL text, because SQL
text can vary while still being correct.

Usage:
    python scripts/eval_harness.py                          # uses config default model
    python scripts/eval_harness.py --model sqlcoder:15b      # AB test a different model
    python scripts/eval_harness.py --dataset path/to.jsonl
    python scripts/eval_harness.py --out results_run1.json   # save full results for diffing
"""
import sys
import os
import json
import argparse
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.config import config


def load_dataset(path: str) -> list[dict]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _cols_lower(filters: list[dict]) -> dict:
    """column_lower -> value (str) from a plan's filters list."""
    out = {}
    for f in filters or []:
        if isinstance(f, dict) and f.get("column"):
            out[f["column"].lower()] = str(f.get("value", ""))
    return out


def grade_case(plan: dict, expect: dict) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_failure_reasons)."""
    if not isinstance(plan, dict):
        return False, ["no plan was generated (abstention or crash)"]

    failures = []
    select_cols = [str(c).lower() for c in (plan.get("select_columns") or [])]
    group_by = [str(c).lower() for c in (plan.get("group_by") or [])]
    filters = plan.get("filters") or []
    filter_cols = {str(f.get("column", "")).lower() for f in filters if isinstance(f, dict)}
    filter_vals = _cols_lower(filters)

    if "intent" in expect and (plan.get("intent") or "").upper() != expect["intent"].upper():
        failures.append(f"intent: expected {expect['intent']}, got {plan.get('intent')}")

    if "select_columns_any_of" in expect:
        wanted = [w.lower() for w in expect["select_columns_any_of"]]
        if not any(w in select_cols or w in group_by for w in wanted):
            failures.append(f"select_columns/group_by: expected one of {expect['select_columns_any_of']}, got select={plan.get('select_columns')} group_by={plan.get('group_by')}")

    if "forbidden_select_columns" in expect:
        bad = [w.lower() for w in expect["forbidden_select_columns"]]
        hit = [c for c in select_cols if c in bad]
        if hit:
            failures.append(f"select_columns contained forbidden column(s): {hit}")

    if "required_filter_columns" in expect:
        for col in expect["required_filter_columns"]:
            if col.lower() not in filter_cols:
                failures.append(f"missing required filter on column '{col}' (filters were: {filters})")

    if "forbidden_filter_columns" in expect:
        bad = [w.lower() for w in expect["forbidden_filter_columns"]]
        hit = [c for c in filter_cols if c in bad]
        if hit:
            failures.append(f"HALLUCINATED filter(s) not asked for: {hit} (filters were: {filters})")

    if "required_filter_values" in expect:
        for col, val in expect["required_filter_values"].items():
            actual = filter_vals.get(col.lower())
            if actual is None:
                failures.append(f"missing required filter '{col}'={val}")
            elif val.lower() not in actual.lower() and actual.lower() not in val.lower():
                failures.append(f"filter '{col}' expected value containing '{val}', got '{actual}'")

    if "group_by_is_date" in expect:
        if bool(plan.get("group_by_is_date")) != expect["group_by_is_date"]:
            failures.append(f"group_by_is_date: expected {expect['group_by_is_date']}, got {plan.get('group_by_is_date')}")

    if "limit" in expect:
        if plan.get("limit") != expect["limit"]:
            failures.append(f"limit: expected {expect['limit']}, got {plan.get('limit')}")

    return (len(failures) == 0), failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Override OLLAMA_RESPONSE_MODEL for this run (AB testing)")
    parser.add_argument("--dataset", default=os.path.join(os.path.dirname(__file__), "..", "app", "data", "eval_dataset.jsonl"))
    parser.add_argument("--out", default=None, help="Write full per-case results JSON here")
    args = parser.parse_args()

    if args.model:
        config.OLLAMA_RESPONSE_MODEL = args.model
        print(f"[EVAL] Overriding plan-generation model -> {args.model}", flush=True)

    from app.data_service import DataService
    from app.pipeline.orchestrator import PipelineOrchestrator

    ds = DataService()
    orch = PipelineOrchestrator(db_engine=ds.engine if ds.use_sql_server else None, data_service=ds)

    cases = load_dataset(args.dataset)
    results = []
    passed_count = 0

    print(f"\n{'='*90}\nRunning {len(cases)} eval cases against model: {orch.plan_generator.ollama_model}\n{'='*90}\n", flush=True)

    for case in cases:
        t0 = time.time()
        try:
            resp = orch.process_query(case["query"], session_id=f"eval-{case['id']}")
            plan = resp.get("plan")
            error = None
        except Exception as e:
            plan = None
            error = str(e)
        elapsed = time.time() - t0

        passed, failures = grade_case(plan, case.get("expect", {})) if error is None else (False, [f"EXCEPTION: {error}"])
        passed_count += int(passed)

        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {case['id']} ({elapsed:.1f}s): {case['query']!r}", flush=True)
        if not passed:
            for f in failures:
                print(f"       - {f}", flush=True)
            print(f"       plan: {json.dumps(plan)}", flush=True)

        results.append({
            "id": case["id"], "query": case["query"], "passed": passed,
            "failures": failures, "plan": plan, "elapsed_s": round(elapsed, 2)
        })

    total = len(cases)
    print(f"\n{'='*90}\nRESULT: {passed_count}/{total} passed ({100*passed_count/total:.1f}%)\n{'='*90}", flush=True)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "model": orch.plan_generator.ollama_model,
                "passed": passed_count, "total": total,
                "results": results
            }, f, indent=2, default=str)
        print(f"Full results written to {args.out}", flush=True)

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
