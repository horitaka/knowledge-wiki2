#!/usr/bin/env python3
"""
validate_dag.py — plan.dag.json を検証し、物理衝突を可視化する。

チェック内容:
  [hard]  存在しないタスクを depends_on が参照していないか（dangling ref）
  [hard]  depends_on に循環が無いか（cycle）
  [hard]  自己依存が無いか
  [warn]  touches が空のタスク（衝突判定不能 → 直列化リスク）
  [info]  物理衝突ペア（同一ファイルを触る = 同一 wave に置けない組）

hard エラーがあれば exit 1。scheduler にかける前の門番。
"""

import argparse
import json
from itertools import combinations
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_cycles(tasks: list[dict]) -> list[list[str]]:
    """DFS で循環を検出。見つかった閉路を（先頭→…→先頭）で返す。"""
    graph = {t["id"]: list(t.get("depends_on", [])) for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in graph}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, []):
            if v not in graph:
                continue  # dangling は別チェックで扱う
            if color[v] == GRAY:
                i = stack.index(v)
                cycles.append(stack[i:] + [v])
            elif color[v] == WHITE:
                dfs(v)
        stack.pop()
        color[u] = BLACK

    for tid in graph:
        if color[tid] == WHITE:
            dfs(tid)
    return cycles


def physical_conflicts(tasks: list[dict]) -> list[tuple[str, str, list[str]]]:
    out = []
    for a, b in combinations(tasks, 2):
        shared = sorted(set(a.get("touches", [])) & set(b.get("touches", [])))
        if shared:
            out.append((a["id"], b["id"], shared))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="plan.dag.json を検証")
    ap.add_argument("dag", help="plan.dag.json")
    ap.add_argument("--quiet", action="store_true", help="info/warn を抑制")
    args = ap.parse_args()

    data = load(args.dag)
    tasks = data.get("tasks", [])
    ids = {t["id"] for t in tasks}
    hard_errors: list[str] = []
    warnings: list[str] = []

    dup = [tid for tid in ids if sum(1 for t in tasks if t["id"] == tid) > 1]
    if dup:
        hard_errors.append(f"重複タスク ID: {sorted(set(dup))}")

    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep == t["id"]:
                hard_errors.append(f"自己依存: {t['id']} が自分自身に依存")
            elif dep not in ids:
                hard_errors.append(f"未定義依存: {t['id']} -> {dep}（そんなタスクは無い）")

    for cyc in find_cycles(tasks):
        hard_errors.append("循環依存: " + " -> ".join(cyc))

    for t in tasks:
        if not t.get("touches"):
            warnings.append(
                f"{t['id']}「{t.get('title', '')}」: touches が空 "
                "（ファイル未特定＝衝突判定できず、安全側で直列化されがち）"
            )

    conflicts = physical_conflicts(tasks)

    # ---- レポート出力 ----
    print(f"=== validate_dag: {data.get('story_id', '?')} / {len(tasks)} tasks ===")

    if hard_errors:
        print("\n[HARD ERRORS] scheduler に渡す前に修正が必要:")
        for e in hard_errors:
            print(f"  ✗ {e}")

    if not args.quiet and warnings:
        print("\n[WARN]")
        for w in warnings:
            print(f"  ! {w}")

    if not args.quiet:
        print(
            f"\n[物理衝突] 同一ファイルを触るペア: {len(conflicts)} 組"
            "（同じ wave には入れられない = scheduler が別 wave に分離）"
        )
        for a, b, shared in conflicts:
            print(f"  ⚡ {a} ↔ {b}  : {', '.join(shared)}")

    if hard_errors:
        print("\n結果: NG（hard error あり）")
        return 1
    print("\n結果: OK — wave-scheduler にかけられます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
