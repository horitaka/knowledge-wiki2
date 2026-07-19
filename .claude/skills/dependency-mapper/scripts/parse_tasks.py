#!/usr/bin/env python3
"""
parse_tasks.py — tasks.md（+ impact.md）から draft plan.dag.json を生成する。

役割分担:
  - このスクリプトは「機械的に取れるもの」だけを取る:
      * タスク ID / タイトル / [P] マーカー
      * 行内に書かれたファイルパス（touches の初期値）
      * impact.md に task→files のマッピングがあれば上書き/補完
  - depends_on（論理依存）は空で出力する。ここは意味理解が要るので Claude が後段で埋める。
    → SKILL.md の手順参照。

出力はあくまで「下書き」。touches の取りこぼしは日常茶飯事なので、
Claude と人間が spec.md / plan.md を見ながら矯正する前提。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 例: "- [ ] T001 [P] Create User model in src/models/user.py"
TASK_LINE = re.compile(
    r"""^\s*[-*]\s*                     # リストマーカー
        (?:\[[ xX]\]\s*)?               # チェックボックス（任意）
        (?P<id>T\d{1,4})\b              # タスク ID: T001 など
        (?P<rest>.*)$""",
    re.VERBOSE,
)
PARALLEL_MARK = re.compile(r"\[P\]", re.IGNORECASE)

# ファイルパスらしいトークン: スラッシュを含むか、既知の拡張子で終わる。
# バッククォート内も拾う。末尾の句読点は落とす。
PATH_TOKEN = re.compile(
    r"""
    `(?P<bt>[^`]+?)`                       # `path` バッククォート優先
    |
    (?P<bare>
        (?:[\w./\-]+/)?[\w.\-]+            # ディレクトリ/ファイル
        \.(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|sql|proto|graphql|
            json|ya?ml|toml|css|scss|html|md|sh|prisma|tf|cs|swift|c|cpp|h|hpp)
    )
    """,
    re.VERBOSE,
)


def looks_like_path(tok: str) -> bool:
    tok = tok.strip().strip(".,;:()[]<>\"'")
    if not tok:
        return False
    if "/" in tok:
        return True
    return bool(re.search(r"\.\w{1,6}$", tok))


def extract_paths(text: str) -> list[str]:
    found: list[str] = []
    for m in PATH_TOKEN.finditer(text):
        tok = (m.group("bt") or m.group("bare") or "").strip()
        tok = tok.strip(".,;:()[]<>\"'` ")
        if tok and looks_like_path(tok) and tok not in found:
            found.append(tok)
    return found


def strip_paths_for_title(text: str) -> str:
    """タイトル用に 'in <path>' などのファイル記述をざっくり除去。"""
    t = PARALLEL_MARK.sub("", text)
    t = re.sub(r"\bin\s+`?[\w./\-]+`?", "", t)  # "in src/x.py"
    t = re.sub(r"[`]", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" -–—:,")


def parse_tasks_md(text: str) -> list[dict]:
    tasks: list[dict] = []
    for raw in text.splitlines():
        m = TASK_LINE.match(raw)
        if not m:
            continue
        tid = m.group("id")
        rest = m.group("rest")
        touches = extract_paths(rest)
        title = strip_paths_for_title(rest)
        tasks.append(
            {
                "id": tid,
                "title": title or tid,
                "parallelizable_hint": bool(PARALLEL_MARK.search(rest)),
                "depends_on": [],  # ← 論理依存。Claude が後で埋める。
                "touches": touches,  # ← 物理依存の材料。取りこぼしは要矯正。
                "notes": "",
            }
        )
    return tasks


def parse_impact_md(text: str) -> dict[str, list[str]]:
    """impact.md から task_id -> [files] を可能な範囲で抽出する。

    対応する書式（ゆるく複数対応）:
      1) Markdown テーブル: | T004 | src/a.py, src/b.py |
      2) 箇条書き:          - T004: src/a.py, src/b.py
                            - T004 -> `src/a.py`, `src/b.py`
    """
    mapping: dict[str, list[str]] = {}

    # テーブル行 / 箇条書き行の両対応: 行のどこかに Txxx があれば、その行のパスを集める
    for raw in text.splitlines():
        idm = re.search(r"\bT\d{1,4}\b", raw)
        if not idm:
            continue
        # ID より後ろ（同一行）のパスを対象にする
        after = raw[idm.end() :]
        paths = extract_paths(after)
        if paths:
            mapping.setdefault(idm.group(0), [])
            for p in paths:
                if p not in mapping[idm.group(0)]:
                    mapping[idm.group(0)].append(p)
    return mapping


def merge_impact(tasks: list[dict], impact: dict[str, list[str]]) -> None:
    by_id = {t["id"]: t for t in tasks}
    for tid, files in impact.items():
        t = by_id.get(tid)
        if not t:
            continue
        for f in files:
            if f not in t["touches"]:
                t["touches"].append(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="tasks.md -> draft plan.dag.json")
    ap.add_argument("--tasks", required=True, help="specs/<id>/tasks.md")
    ap.add_argument("--impact", help="specs/<id>/impact.md（任意）")
    ap.add_argument("--out", required=True, help="出力 plan.dag.json")
    ap.add_argument("--story-id", default="", help="ストーリー ID（メタ情報）")
    args = ap.parse_args()

    tasks_text = Path(args.tasks).read_text(encoding="utf-8")
    tasks = parse_tasks_md(tasks_text)
    if not tasks:
        print(
            "[parse_tasks] 警告: tasks.md からタスクを1件も抽出できませんでした。"
            "行頭が '- [ ] T001 ...' 形式か確認してください。",
            file=sys.stderr,
        )

    if args.impact and Path(args.impact).exists():
        impact = parse_impact_md(Path(args.impact).read_text(encoding="utf-8"))
        merge_impact(tasks, impact)

    story_id = args.story_id or Path(args.tasks).parent.name

    dag = {
        "story_id": story_id,
        "generated_by": "dependency-mapper/parse_tasks.py",
        "schema": "plan.dag.json/v1",
        "note": "depends_on は論理依存のみ（空なら未付与）。物理依存は touches から scheduler が算出。",
        "tasks": tasks,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n_no_files = sum(1 for t in tasks if not t["touches"])
    print(f"[parse_tasks] {len(tasks)} タスクを抽出 -> {out}")
    if n_no_files:
        print(
            f"[parse_tasks] うち {n_no_files} 件は touches が空です。"
            "impact.md / spec を見て Claude が補完してください。"
        )
    print(
        "[parse_tasks] 次: Claude が depends_on（論理依存）を付与し、"
        "validate_dag.py で検証してください。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
