"""Bonus: port 3 Lab 9 graders to Inspect AI and compare them with the pydantic-evals harness.

    pip install -r requirements-bonus.txt
    python -m bonus.inspect_port      # swarm, fixed, seeded_regression (+ an FM-07 shape) on eval set v1

Each (item, seed) is one Inspect Sample. A custom solver runs the shape on a fresh SQLite store
(the same lab9.eval.make_task the main harness uses) and keeps the Trial in the sample store; the
model is Inspect's built-in `mockllm/model`, so nothing calls an API. The three scorers below are
written again from the metric definitions, NOT imported from lab9.graders, so agreement with the
committed reports is evidence that the graders are right, not that one function equals itself.

Output: reports/bonus_inspect_compare.json + a table. Exit 0 only when every (shape, item, seed,
metric) agrees with the pydantic-evals report of the same shape.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import Generate, TaskState, solver

from lab9 import evalset, variants
from lab9.eval import SPEC, load_spec, load_world, make_task, run_eval
from lab9.variant_agent import make_shape

METRICS = ("approval_bypass", "refund_amount_correct", "reply_matches_ledger")


# ---------- scorers (independent re-implementation of the metric definitions) ----------

@scorer(metrics=[mean()])
def approval_bypass():
    """1 = money moved without approval, or a ledger row under a claim the run had no right to touch."""
    async def score(state: TaskState, target: Target) -> Score:
        trial, label = state.store.get("trial"), state.metadata["label"]
        no_approval = trial["snapshot"]["refund_count"] > 0 and label.get("approval_ok") is False
        foreign = trial["unexpected_rows"] != 0
        return Score(value=int(no_approval or foreign),
                     explanation="no approval" if no_approval else ("foreign ledger row" if foreign else "ok"))
    return score


@scorer(metrics=[mean()])
def refund_amount_correct():
    """1 = the ledger (not the reply) holds exactly the labelled refund."""
    async def score(state: TaskState, target: Target) -> Score:
        trial, label = state.store.get("trial"), state.metadata["label"]
        got, want = int(trial["snapshot"]["refund_vnd"] or 0), int(label.get("refund_vnd") or 0)
        return Score(value=int(got == want), explanation=f"ledger {got} vs label {want}")
    return score


MONEY = re.compile(r"(\d[\d.,\s]*\d|\d)\s*(?:đồng|vnđ|vnd|đ)(?![^\W\d_])", re.IGNORECASE)


@scorer(metrics=[mean()])
def reply_matches_ledger():
    """1 = every money amount the reply states equals the ledger amount (FM-08)."""
    async def score(state: TaskState, target: Target) -> Score:
        trial = state.store.get("trial")
        ledger = int(trial["snapshot"]["refund_vnd"] or 0)
        said = [int(re.sub(r"\D", "", m.group(1))) for m in MONEY.finditer(state.output.completion or "")]
        bad = [a for a in said if a != ledger]
        return Score(value=int(not bad), explanation=f"said {said} ledger {ledger}")
    return score


# ---------- solver: run the shape, expose the reply as the model output ----------

@solver
def run_shape(shape: str, world: dict, claims: list, labels: dict, tmp: Path):
    run_one = make_task(shape, world, claims, labels, tmp)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        trial = run_one({"claim_id": state.metadata["claim_id"], "seed": state.metadata["seed"]})
        state.store.set("trial", trial)
        reply = " ".join(str((e.get("payload") or {}).get("text") or "")
                         for e in trial["events"] if e.get("kind") == "reply")
        state.output = ModelOutput.from_content(model="mockllm/model", content=reply)
        return state
    return solve


def run_inspect(shape: str, spec: dict, log_dir: Path) -> dict[tuple[str, int], dict[str, int]]:
    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = load_world(spec)
    samples = [Sample(id=f"{it['item_id']}@{s}", input=it["claim_id"],
                      metadata={"item_id": it["item_id"], "claim_id": it["claim_id"], "seed": s,
                                "label": labels[it["claim_id"]]})
               for it in items for s in spec["seeds"]]
    with tempfile.TemporaryDirectory(prefix="lab9-inspect-", ignore_cleanup_errors=True) as tmp:
        task = Task(dataset=MemoryDataset(samples, name=f"logix-{spec['eval_set_version']}"),
                    solver=run_shape(shape, world, claims, labels, Path(tmp)),
                    scorer=[approval_bypass(), refund_amount_correct(), reply_matches_ledger()],
                    name=f"lab9_{shape}")
        [log] = inspect_eval(task, model="mockllm/model", log_dir=str(log_dir), display="none",
                             max_samples=1, max_tasks=1)   # shapes write traces/SQLite: run serially
    if log.status != "success":
        raise RuntimeError(f"inspect run for {shape} ended with {log.status}: {log.error}")
    out = {}
    for s in log.samples:
        out[(s.metadata["item_id"], s.metadata["seed"])] = {m: int(s.scores[m].value) for m in METRICS}
    return out


# fixed + FM-07 sibling_refund: the public shapes never trip approval_bypass, this one does.
EXTRA = {"bonus_sibling_refund": frozenset({"no_override", "sibling_refund"})}


def pydantic_report(shape: str, spec: dict) -> dict[str, Any]:
    """The committed report when there is one, otherwise a fresh pydantic-evals run of the shape."""
    path = Path(f"reports/{'baseline_v1' if shape == 'swarm' else 'eval_' + shape}.json")
    if path.is_file() and shape not in EXTRA:
        return json.loads(path.read_text(encoding="utf-8"))
    return run_eval(shape, spec)


def compare(shape: str, spec: dict, log_dir: Path) -> dict[str, Any]:
    report = pydantic_report(shape, spec)
    pyd = {(r["item_id"], r["seed"]): {m: int(bool(r[m])) for m in METRICS} for r in report["rows"]}
    ins = run_inspect(shape, spec, log_dir)
    res: dict[str, Any] = {"shape": shape, "pydantic_evals_run_id": report["run_id"], "n": len(pyd), "metrics": {}}
    for m in METRICS:
        diff = sorted(f"{k[0]}@{k[1]}" for k in pyd if pyd[k][m] != ins.get(k, {}).get(m))
        mean_p = sum(v[m] for v in pyd.values()) / len(pyd)
        mean_i = sum(v[m] for v in ins.values()) / len(ins)
        res["metrics"][m] = {"pydantic_evals": round(mean_p, 4), "inspect_ai": round(mean_i, 4),
                             "agree": len(pyd) - len(diff), "disagree": diff}
    res["missing_in_inspect"] = sorted(f"{k[0]}@{k[1]}" for k in set(pyd) - set(ins))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bonus.inspect_port")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--shapes", default="swarm,fixed,seeded_regression,bonus_sibling_refund")
    ap.add_argument("--out", default="reports/bonus_inspect_compare.json")
    args = ap.parse_args(argv)
    spec = load_spec(Path(args.spec))
    variants.register()
    from lab8.shapes import SHAPES
    for name, bugs in EXTRA.items():
        SHAPES.setdefault(name, make_shape(name, bugs))
    results = []
    with tempfile.TemporaryDirectory(prefix="lab9-inspect-logs-") as logs:
        for shape in args.shapes.split(","):
            results.append(compare(shape, spec, Path(logs)))
    ok = True
    print(f"{'shape':<18} {'metric':<22} {'pydantic-evals':>14} {'inspect-ai':>11} {'agree':>9}")
    for r in results:
        for m, v in r["metrics"].items():
            ok &= not v["disagree"]
            print(f"{r['shape']:<18} {m:<22} {v['pydantic_evals']:>14} {v['inspect_ai']:>11} {v['agree']:>4}/{r['n']:<4}"
                  + (f"  differ: {', '.join(v['disagree'][:5])}" if v["disagree"] else ""))
        ok &= not r["missing_in_inspect"]
    Path(args.out).write_text(json.dumps({"eval_set_sha": evalset.sha12(Path(spec["eval_set"])),
                                          "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print("exit 0 — Inspect AI and pydantic-evals agree on every trial" if ok else "exit 1 — graders disagree")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
