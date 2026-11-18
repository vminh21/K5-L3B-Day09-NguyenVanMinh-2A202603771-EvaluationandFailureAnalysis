"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. metric values must be finite numbers (NaN < min is False: a naive gate passes it)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v}")

    # 2. grader crashes must not silently drop out of the mean
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    for m in graded:
        missing = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if r.get(m) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) with no value for {m} (e.g. {missing[0]})")

    # 3. coverage: every (item, seed) of the baseline exactly once, and the manifest agrees
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    want_n = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want_n}")
    if len(set(pairs)) != len(pairs):
        problems.append(f"{len(pairs) - len(set(pairs))} duplicated (item, seed) row(s)")
    if set(pairs) != base_pairs:
        lost, extra = base_pairs - set(pairs), set(pairs) - base_pairs
        problems.append(f"(item, seed) set differs from baseline: {len(lost)} missing, {len(extra)} extra")
    if man.get("items") != bman.get("items") or sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"manifest {man.get('items')} items / seeds {man.get('seeds')} != baseline "
                        f"{bman.get('items')} items / seeds {bman.get('seeds')}")

    # 4. reported metrics must be what the rows say (a hand-edited headline number)
    for m in graded:
        reported = (pr.get("metrics") or {}).get(m)
        vals = [r[m] for r in rows if r.get(m) is not None]
        if reported is None or not vals or (isinstance(reported, float) and not math.isfinite(reported)):
            continue
        actual = sum(vals) if m in SAFETY_COUNTS else sum(vals) / len(vals)
        if abs(float(reported) - actual) > 1e-3:
            problems.append(f"metric {m} reported {reported} but rows give {actual:.4f}")
    # ... including the per-item reliability numbers (pass_5, pass_at_k, pass_hat_k) built from pass_rate
    by_item: dict = {}
    for r in rows:
        if r.get("pass_rate") is not None:
            by_item.setdefault(r.get("item_id"), []).append(bool(r["pass_rate"]))
    for k, reported in (pr.get("metrics") or {}).items():
        if not by_item or not isinstance(reported, (int, float)) or not math.isfinite(reported):
            continue
        if k == "pass_5":
            actual = sum(all(v) for v in by_item.values()) / len(by_item)
        elif k.startswith(("pass_at_", "pass_hat_")) and k.rsplit("_", 1)[1].isdigit():
            kk, fn = int(k.rsplit("_", 1)[1]), (stats.pass_at_k if k.startswith("pass_at_") else stats.pass_hat_k)
            if min(len(v) for v in by_item.values()) < kk:
                continue
            actual = sum(fn(len(v), sum(v), kk) for v in by_item.values()) / len(by_item)
        else:
            continue
        if abs(float(reported) - actual) > 1e-3:
            problems.append(f"metric {k} reported {reported} but rows give {actual:.4f}")

    # 5. slice tags are the baseline's (moving an item out of a slice hides its regression)
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in base_tags and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline on {len(moved)} item(s): {', '.join(moved[:5])}")

    # 6. ratchet: on the same eval-set version a spec may only get stricter
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += ratchet(spec, base_spec)
    return problems


SAFETY_COUNTS = ("secret_leak", "approval_bypass")   # aggregated as counts in lab9.eval.aggregate


def _looser(new: dict, old: dict, what: str) -> list[str]:
    """Compare one metric/slice entry against the base one; return how the new one is looser."""
    out = []
    nt, ot = new.get("threshold", new), old.get("threshold", old)
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{what}: blocking -> non-blocking")
    if old.get("kind") and new.get("kind") != old.get("kind"):
        out.append(f"{what}: kind {old.get('kind')} -> {new.get('kind')}")
    for key in ("max", "max_increase"):
        if key in ot and (key not in nt or nt[key] > ot[key]):
            out.append(f"{what}: {key} {ot[key]} -> {nt.get(key, 'removed')}")
    if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
        out.append(f"{what}: min {ot['min']} -> {nt.get('min', 'removed')}")
    if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
        out.append(f"{what}: no_significant_drop dropped")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    problems: list[str] = []
    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        if m["id"] not in new_m:
            problems.append(f"ratchet: metric {m['id']} removed")
        else:
            problems += [f"ratchet: {p}" for p in _looser(new_m[m["id"]], m, m["id"])]
    new_s = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        key = (s.get("name"), s.get("metric"))
        if key not in new_s:
            problems.append(f"ratchet: slice {key[0]}/{key[1]} removed")
        else:
            problems += [f"ratchet: {p}" for p in _looser(new_s[key], s, f"slice {key[0]}/{key[1]}")]
    if set(base_spec.get("seeds") or []) - set(spec.get("seeds") or []):
        problems.append(f"ratchet: seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    old_k, new_k = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if new_k.get("confidence", 0.95) > old_k.get("confidence", 0.95):
        problems.append(f"ratchet: bootstrap confidence {old_k.get('confidence', 0.95)} -> {new_k.get('confidence')} (wider CI)")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "slice has no rows in PR"   # an empty slice cannot be shown safe
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        label = "ok" if verdict == "ok" else ("BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
