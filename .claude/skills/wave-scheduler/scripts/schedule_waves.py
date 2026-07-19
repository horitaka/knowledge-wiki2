#!/usr/bin/env python3
"""
schedule_waves.py — plan.dag.json を Agent teams で実行できる形に変換する。

`--mode wave`（既定・モードA）: discrete な wave（層）に分割する。
`--mode dag`（モードB）: ファイル重複を疑似 depends_on エッジに変換し、1本の DAG として
                          一括登録できる形にする。wave分けはしない。

共通の制約は 2 つ:
  1) 論理依存（depends_on）: 依存タスクが完了するまで着手できない
  2) 物理依存（touches の重複）: 同じファイルを触るタスクは同時に走らせない

--- モードA（wave） ---
アルゴリズム: 貪欲なリストスケジューリング
  - ready = 依存が全て解決済みの未スケジュールタスク
  - 優先度 = 下流に連なるタスク数（クリティカルパス上のものを先に流す）
  - ready を優先度順に見て、幅上限 & ファイル非重複を満たす限り同一 wave に詰める
  - 詰め切れなかったものは次 wave へ（= 物理依存を設計段階で直列化）
wave間の同期は agent teams のタスク依存機構（depends_on）には委ねない。公式ドキュメントが
"Task status can lag" と明記する通り、完了マーク漏れが下流タスクを永久にブロックしうるため、
wave境界の直列化は引き続き人間 / lead 主導で行う。agent teams に委ねるのは wave 内（依存も
ファイル重複もない）タスク群の並列実行だけ。

--- モードB（dag） ---
アルゴリズム: 優先度考慮トポロジカル順 + ファイル重複の鎖状直列化
  - 論理依存だけを見た優先度考慮トポロジカル順 (order) を1本作る
  - order を先頭から見て、同じファイルに触れるタスクは「直前にそのファイルを触ったタスク」
    への疑似 depends_on エッジ1本だけを追加する（all-pairsではなく鎖状。order に沿った
    forward edgeしか作らないので循環は生じない）
  - 論理依存＋疑似依存を合成した1本のDAGを、wave分けせず丸ごと TaskCreate で登録する前提
  - wave境界というHOTLチェックポイントが失われる代わりに、`TeammateIdle` / `TaskCompleted`
    hookで完了主張の妥当性を機械チェックすることを前提とする（完了マーク漏れで下流が
    永久ブロックされる既知の制限への対策。§7参照）

出力:
  モードA: waves.json（機械可読）＋ waves.md（teammate 割り当て表）＋ handoff.md（wave単位の
           引き渡しプロンプト、任意）
  モードB: waves.json（拡張DAG＋疑似エッジ一覧）＋ waves.md（レビュー用一覧）＋ handoff.md
           （一括登録プロンプト、任意）

注記: 外部スクリプトから ~/.claude/tasks/{team-name}/ に直接タスクを書き込む公式サポート
された経路は存在しない（TaskCreate は lead が呼ぶツール）。そのため両モードとも「登録」は
lead への自然言語プロンプト（handoff.md）という形を取る。
"""

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------- load & guard
def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def guard(tasks: list[dict]) -> None:
    """scheduler 単体でも壊れた DAG を弾く（自己完結のための最小チェック）。"""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep not in ids:
                sys.exit(
                    f"[schedule_waves] 未定義依存: {t['id']} -> {dep}。"
                    "先に dependency-mapper/validate_dag.py を通してください。"
                )
    # 循環検出（DFS）
    graph = {t["id"]: list(t.get("depends_on", [])) for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in graph}

    def dfs(u, stack):
        color[u] = GRAY
        for v in graph[u]:
            if color[v] == GRAY:
                sys.exit("[schedule_waves] 循環依存: " + " -> ".join(stack[stack.index(v) :] + [v]))
            if color[v] == WHITE:
                dfs(v, stack + [v])
        color[u] = BLACK

    for i in graph:
        if color[i] == WHITE:
            dfs(i, [i])


# ---------------------------------------------------------------- metrics
def transitive_dependents(tasks: list[dict]) -> dict[str, int]:
    """各タスクに「下流に連なる（自分を依存に持つ）タスク総数」を与える。"""
    children: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for dep in t.get("depends_on", []):
            children[dep].append(t["id"])

    memo: dict[str, set[str]] = {}

    def desc(u: str) -> set[str]:
        if u in memo:
            return memo[u]
        acc: set[str] = set()
        for c in children[u]:
            acc.add(c)
            acc |= desc(c)
        memo[u] = acc
        return acc

    return {t["id"]: len(desc(t["id"])) for t in tasks}


def logical_earliest_wave(tasks: list[dict]) -> dict[str, int]:
    """論理依存だけを見たときの最早 wave（1-indexed）。物理制約による遅延の基準線。"""
    by_id = {t["id"]: t for t in tasks}
    memo: dict[str, int] = {}

    def depth(u: str) -> int:
        if u in memo:
            return memo[u]
        deps = by_id[u].get("depends_on", [])
        memo[u] = 1 if not deps else 1 + max(depth(d) for d in deps)
        return memo[u]

    return {t["id"]: depth(t["id"]) for t in tasks}


# ---------------------------------------------------------------- scheduler
def schedule(tasks: list[dict], max_teammates: int) -> list[list[str]]:
    by_id = {t["id"]: t for t in tasks}
    prio = transitive_dependents(tasks)
    scheduled: set[str] = set()
    waves: list[list[str]] = []

    remaining = [t["id"] for t in tasks]
    while remaining:
        ready = [
            tid
            for tid in remaining
            if all(d in scheduled for d in by_id[tid].get("depends_on", []))
        ]
        # 優先度高い順（下流が多い）→ 同点は ID 昇順で安定化
        ready.sort(key=lambda x: (-prio[x], x))

        wave: list[str] = []
        files_in_wave: set[str] = set()
        for tid in ready:
            if len(wave) >= max_teammates:
                break
            touches = set(by_id[tid].get("touches", []))
            if touches & files_in_wave:
                continue  # 物理衝突 → この wave には入れない（次 wave へ回す）
            wave.append(tid)
            files_in_wave |= touches

        if not wave:  # 論理上あり得ないが安全弁
            sys.exit(f"[schedule_waves] スケジュール停止（残: {remaining}）。DAG を確認。")

        waves.append(wave)
        scheduled.update(wave)
        remaining = [tid for tid in remaining if tid not in scheduled]
    return waves


# ---------------------------------------------------------------- render
def build_output(dag: dict, waves: list[list[str]], max_teammates: int) -> dict:
    by_id = {t["id"]: t for t in dag["tasks"]}
    earliest = logical_earliest_wave(dag["tasks"])
    wave_of = {tid: i + 1 for i, w in enumerate(waves) for tid in w}

    wave_objs = []
    delayed_by_physical = []
    for i, w in enumerate(waves, start=1):
        assignments = {f"teammate-{j + 1}": tid for j, tid in enumerate(w)}
        files = sorted({f for tid in w for f in by_id[tid].get("touches", [])})
        wave_objs.append(
            {
                "wave": i,
                "tasks": w,
                "assignments": assignments,
                "files": files,
                "width": len(w),
            }
        )
        for tid in w:
            if wave_of[tid] > earliest[tid]:
                delayed_by_physical.append(
                    {
                        "id": tid,
                        "logical_earliest": earliest[tid],
                        "scheduled": wave_of[tid],
                    }
                )

    return {
        "story_id": dag.get("story_id", ""),
        "generated_by": "wave-scheduler/schedule_waves.py",
        "max_teammates": max_teammates,
        "summary": {
            "total_tasks": len(dag["tasks"]),
            "total_waves": len(waves),
            "max_parallel_width": max((len(w) for w in waves), default=0),
            "delayed_by_file_conflict_or_width": len(delayed_by_physical),
        },
        "delayed_tasks": delayed_by_physical,
        "waves": wave_objs,
    }


def render_md(out: dict, dag: dict) -> str:
    by_id = {t["id"]: t for t in dag["tasks"]}
    s = out["summary"]
    lines: list[str] = []
    lines.append(f"# 実装順プラン（waves） — {out['story_id']}")
    lines.append("")
    lines.append(
        "> `wave-scheduler` 出力。各 wave は「依存が全て解決済み・"
        "かつ互いにファイル非重複」なタスク群。wave 内は並列、wave 間は直列。"
    )
    lines.append("")
    lines.append("## サマリ")
    lines.append("")
    lines.append(f"- タスク総数: **{s['total_tasks']}**")
    lines.append(f"- wave 数（直列段数）: **{s['total_waves']}**")
    lines.append(
        f"- 最大並列幅: **{s['max_parallel_width']}** / teammate 上限 {out['max_teammates']}"
    )
    lines.append(
        f"- 物理制約で後ろ倒しになったタスク: **{s['delayed_by_file_conflict_or_width']}** 件"
        "（同一ファイル衝突 or 幅上限による直列化。ここがマージ地獄の未然防止分）"
    )
    lines.append("")

    for w in out["waves"]:
        lines.append(f"## Wave {w['wave']}  （並列 {w['width']} 本）")
        lines.append("")
        lines.append("| teammate | task | タイトル | touches |")
        lines.append("|---|---|---|---|")
        for mate, tid in w["assignments"].items():
            t = by_id[tid]
            files = ", ".join(f"`{f}`" for f in t.get("touches", [])) or "—"
            lines.append(f"| {mate} | {tid} | {t.get('title', '')} | {files} |")
        lines.append("")
        if w["files"]:
            lines.append(
                "<sub>この wave が触る全ファイル（重複なし）: "
                + ", ".join(f"`{f}`" for f in w["files"])
                + "</sub>"
            )
            lines.append("")

    if out["delayed_tasks"]:
        lines.append("## 物理制約で直列化されたタスク")
        lines.append("")
        lines.append(
            "論理依存だけなら早く着手できたが、ファイル重複 or 幅上限で後ろ倒しになったもの。"
            "= このスケジューラが *設計段階で* マージ衝突を潰した箇所。"
        )
        lines.append("")
        lines.append("| task | 論理上の最早 wave | 実際の wave |")
        lines.append("|---|---|---|")
        for d in out["delayed_tasks"]:
            lines.append(f"| {d['id']} | wave {d['logical_earliest']} | wave {d['scheduled']} |")
        lines.append("")

    lines.append("## 実行メモ")
    lines.append("")
    lines.append(
        "- 各 wave の切れ目が **HOTL の監視ポイント**（`◎` ではなく `△`：暴走時のみ介入）。"
    )
    lines.append(
        "- wave 単位で agent teams + worktree を起動。teammate 数は wave の並列幅に合わせる。"
    )
    lines.append("- 規模が上がったら headless `claude -p` の driver に本表をそのまま食わせる。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- handoff to agent teams
def render_handoff(out: dict, dag: dict) -> str:
    """
    wave 単位で agent teams の lead にそのまま貼り付けられる指示ブロックを生成する。

    設計方針（なぜ wave 境界の同期は自動化しないか）:
      - wave 内のタスクは schedule() の時点で「論理依存が全て解決済み・かつファイル非重複」
        であることが保証されている。したがって wave 内に限っては、依存関係の指定なしで
        TaskCreate に一括登録して構わない。ここだけが agent teams に安全に委譲できる部分。
      - wave 間の同期は agent teams のタスク依存機構（depends_on）には委ねない。
        公式ドキュメントの Limitations は "Task status can lag: teammates sometimes fail
        to mark tasks as completed, which blocks dependent tasks" と明記しており、
        完了マークの付け忘れが下流タスクを永久にブロックしうる。wave 境界の直列化は
        これまで通り人間 / lead が「次の wave を流す」ことで明示的に担保する。
      - 加えて、外部スクリプトから ~/.claude/tasks/{team-name}/ に直接タスクを書き込む
        公式サポートされた経路は存在しない（TaskCreate は lead が呼ぶツール）。
        そのため「登録」は lead に自然言語で指示する形を取る。
    """
    by_id = {t["id"]: t for t in dag["tasks"]}
    blocks: list[str] = []
    for w in out["waves"]:
        lines = []
        lines.append(f"### Wave {w['wave']} 引き渡しプロンプト（lead にそのまま貼る）")
        lines.append("")
        lines.append(
            f"agent team を使って（subagent ではなく agent team でお願いします）、"
            f"次の {w['width']} 件を並列実装してください。"
        )
        lines.append("")
        lines.append(
            f"1. TaskCreate で {w['width']} 件のタスクを登録する（wave-scheduler が設計段階で"
            "依存関係・ファイル重複を解消済みのため depends_on の指定は不要）。"
        )
        lines.append(f"2. teammate を {w['width']} 名 spawn し、下記の1件ずつを割り当てる。")
        lines.append(
            "3. 各 teammate は「実装 → テスト実行 → green になるまで修正 → PR 作成」を回す。"
            "担当外のファイルには触らないこと。"
        )
        lines.append(
            "4. 全 teammate が完了するまで、lead 自身は実装作業をせず、進捗の同期・"
            "詰まった teammate への steering に専念すること。"
        )
        lines.append("")
        for mate, tid in w["assignments"].items():
            t = by_id[tid]
            files = ", ".join(t.get("touches", [])) or "(なし)"
            lines.append(f"- **{mate}** ← `{tid}`: {t.get('title', '')}")
            lines.append(f"  - touches: {files}")
            if t.get("description"):
                lines.append(f"  - 詳細: {t['description']}")
        lines.append("")
        lines.append(
            f"> このwaveの全teammateが完了・マージされるまで、Wave {w['wave'] + 1} の指示は"
            "流さないでください（wave境界がHOTLの監視ポイントです。完了マークの付け忘れに"
            "注意し、実際の完了は人間が目視で確認すること）。"
        )
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


# ==================================================================
# モードB: DAG 一括登録
# ==================================================================
def priority_topo_order(tasks: list[dict], prio: dict[str, int]) -> list[str]:
    """
    論理依存（depends_on）だけを見た、優先度考慮済みのトポロジカル順（Kahn法）。
    ready集合の中から「下流に連なるタスクが多い順」に確定していく（schedule()と同じ優先度基準）。
    この順序に沿ってしか疑似エッジを張らないため、後段の build_synthetic_dag() は
    構造的に循環を作らない。
    """
    by_id = {t["id"]: t for t in tasks}
    indeg = {t["id"]: len(t.get("depends_on", [])) for t in tasks}
    children: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for d in t.get("depends_on", []):
            children[d].append(t["id"])

    ready = [tid for tid, deg in indeg.items() if deg == 0]
    order: list[str] = []
    while ready:
        ready.sort(key=lambda x: (-prio[x], x))
        tid = ready.pop(0)
        order.append(tid)
        for c in children[tid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)

    if len(order) != len(tasks):
        # guard() を先に通している前提だが、二重の安全弁として残す
        missing = set(by_id) - set(order)
        sys.exit(f"[schedule_waves] トポロジカル順の構築に失敗（循環の疑い）: {missing}")
    return order


def build_synthetic_dag(
    tasks: list[dict], order: list[str]
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """
    論理依存＋ファイル重複由来の疑似依存を合成した depends_on を返す。

    ファイル重複は all-pairs ではなく「直前にそのファイルを触ったタスク」への単一エッジに
    圧縮する。＝ 同じファイルを触るタスク群を order 通りの一本の鎖として直列化する
    （最小限のエッジ数で衝突を防げる。3タスクが同じファイルを触るなら 2エッジで足りる）。
    order は priority_topo_order() の出力で、全ての疑似エッジがこの順で「前→後」にしか
    向かないことが保証されているため、合成後も DAG のまま（循環が生じない）。
    """
    by_id = {t["id"]: t for t in tasks}
    augmented: dict[str, list[str]] = {tid: list(by_id[tid].get("depends_on", [])) for tid in order}
    synthetic: list[tuple[str, str]] = []

    last_touch: dict[str, str] = {}
    for tid in order:
        touches = by_id[tid].get("touches", [])
        add_from: list[str] = []
        for f in touches:
            prev = last_touch.get(f)
            if prev is not None and prev != tid and prev not in augmented[tid]:
                add_from.append(prev)
            last_touch[f] = tid
        for prev in add_from:
            augmented[tid].append(prev)
            synthetic.append((prev, tid))

    return augmented, synthetic


def theoretical_levels(order: list[str], augmented: dict[str, list[str]]) -> list[list[str]]:
    """
    合成済み DAG から「参考情報としての理論上の並列度」を見積もる層分解。
    モードBでは実行順序を強制する目的では使わない（teammate は共有タスクリストから
    自己組織的に claim するため、実際の並びはランタイムの claim 状況次第で変わる）。
    レビュー時の「最大何本くらい並列になりそうか」の目安として waves.md 相当の情報を出す。
    """
    remaining = set(order)
    scheduled: set[str] = set()
    levels: list[list[str]] = []
    while remaining:
        ready = sorted(tid for tid in remaining if all(d in scheduled for d in augmented[tid]))
        if not ready:
            sys.exit("[schedule_waves] 理論レベル分解が停止（循環の可能性、guard()を確認）")
        levels.append(ready)
        scheduled.update(ready)
        remaining -= set(ready)
    return levels


def build_dag_output(
    dag: dict,
    tasks: list[dict],
    order: list[str],
    augmented: dict[str, list[str]],
    synthetic: list[tuple[str, str]],
    max_teammates_hint: int,
) -> dict:
    by_id = {t["id"]: t for t in tasks}
    levels = theoretical_levels(order, augmented)
    synthetic_by_to: dict[str, list[str]] = {}
    for f, t in synthetic:
        synthetic_by_to.setdefault(t, []).append(f)

    return {
        "story_id": dag.get("story_id", ""),
        "generated_by": "wave-scheduler/schedule_waves.py --mode dag",
        "mode": "dag",
        "max_teammates_hint": max_teammates_hint,
        "summary": {
            "total_tasks": len(tasks),
            "logical_edges": sum(len(t.get("depends_on", [])) for t in tasks),
            "synthetic_edges_added": len(synthetic),
            "theoretical_depth": len(levels),
            "theoretical_max_width": max((len(lv) for lv in levels), default=0),
        },
        "order": order,
        "tasks": [
            {
                "id": tid,
                "title": by_id[tid].get("title", ""),
                "touches": by_id[tid].get("touches", []),
                "depends_on": augmented[tid],
                "synthetic_depends_on": synthetic_by_to.get(tid, []),
            }
            for tid in order
        ],
        "synthetic_edges": [{"from": f, "to": t} for f, t in synthetic],
        "theoretical_levels": levels,
    }


def render_dag_md(out: dict) -> str:
    s = out["summary"]
    lines: list[str] = []
    lines.append(f"# 実装順プラン（DAG一括登録・モードB） — {out['story_id']}")
    lines.append("")
    lines.append(
        "> `wave-scheduler --mode dag` 出力。wave分割はせず、論理依存＋ファイル重複由来の"
        "疑似依存を合成した1本のDAGを、そのまま Agent teams に一括登録する前提の資料。"
    )
    lines.append("")
    lines.append("## サマリ")
    lines.append("")
    lines.append(f"- タスク総数: **{s['total_tasks']}**")
    lines.append(f"- 論理依存エッジ数: **{s['logical_edges']}**")
    lines.append(
        f"- ファイル重複から追加した疑似依存エッジ数: **{s['synthetic_edges_added']}**"
        "（モードAの「物理制約で直列化されたタスク」に相当。ここが人間が目視で"
        "妥当性を確認するポイント）"
    )
    lines.append(
        f"- 参考: 理論上の最大並列幅 **{s['theoretical_max_width']}** / 段数 "
        f"**{s['theoretical_depth']}**（実行順序を強制するものではなく、"
        "spawnするteammate数の目安）"
    )
    lines.append("")
    lines.append("## タスク一覧（登録順 = 優先度考慮済みトポロジカル順）")
    lines.append("")
    lines.append("| task | タイトル | touches | depends_on（論理＋疑似） | うち疑似 |")
    lines.append("|---|---|---|---|---|")
    for t in out["tasks"]:
        files = ", ".join(f"`{f}`" for f in t["touches"]) or "—"
        deps = ", ".join(f"`{d}`" for d in t["depends_on"]) or "—"
        synth = ", ".join(f"`{d}`" for d in t["synthetic_depends_on"]) or "—"
        lines.append(f"| {t['id']} | {t['title']} | {files} | {deps} | {synth} |")
    lines.append("")

    if out["synthetic_edges"]:
        lines.append("## ファイル重複から追加された疑似依存（レビュー対象）")
        lines.append("")
        lines.append(
            "論理上は無関係だが、同じファイルを触るために追加で直列化したペア。"
            "「本当にこの順で直列化してよいか」をここで確認する。"
        )
        lines.append("")
        lines.append("| from（先に完了させる） | to（あとで着手） |")
        lines.append("|---|---|")
        for e in out["synthetic_edges"]:
            lines.append(f"| {e['from']} | {e['to']} |")
        lines.append("")

    lines.append("## 実行メモ")
    lines.append("")
    lines.append(
        "- wave境界という明示的なHOTLチェックポイントは無い。代わりに `TeammateIdle` / "
        "`TaskCompleted` hook で完了主張の妥当性を機械チェックすること"
        "（完了マーク漏れで下流が永久ブロックされる既知の制限への対策）。"
    )
    lines.append(
        f"- teammate は目安 **{out['max_teammates_hint']}** 名程度から spawn し、"
        "共有タスクリストから自己組織的に claim させる。"
    )
    lines.append("")
    return "\n".join(lines)


def render_dag_handoff(out: dict) -> str:
    """DAG全体を一括で lead に渡すための単一プロンプト（wave単位に分割しない）。"""
    lines: list[str] = []
    lines.append("### DAG一括登録プロンプト（lead にそのまま貼る・モードB）")
    lines.append("")
    lines.append(
        f"以下の {out['summary']['total_tasks']} 件のタスクを、記載した depends_on の通りに "
        "TaskCreate で**まとめて**登録してください（wave分けはしません）。登録が終わったら "
        f"teammate を {out['max_teammates_hint']} 名 spawn し、共有タスクリストから "
        "自己組織的にタスクを claim させてください。"
    )
    lines.append("")
    for t in out["tasks"]:
        deps = ", ".join(f"`{d}`" for d in t["depends_on"]) or "(依存なし)"
        files = ", ".join(t["touches"]) or "(なし)"
        lines.append(f"- `{t['id']}`: {t['title']}")
        lines.append(f"  - depends_on: {deps}")
        lines.append(f"  - touches: {files}")
    lines.append("")
    lines.append(
        "> 完了マークの付け忘れで下流タスクが永久にブロックされることがあります。"
        "`TeammateIdle` hook で「claim中のタスクが実は完了しているのに未マークでないか」を、"
        "`TaskCompleted` hook で「完了主張時にテストがgreenかどうか」を機械チェックしてください。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(
        description="plan.dag.json -> waves（モードA）/ DAG一括登録（モードB）"
    )
    ap.add_argument("dag", help="plan.dag.json")
    ap.add_argument(
        "--mode",
        choices=["wave", "dag"],
        default="wave",
        help="wave=discreteなwaveに分割（既定・モードA） / dag=疑似依存を合成し一括登録（モードB）",
    )
    ap.add_argument(
        "--max-teammates",
        type=int,
        default=5,
        help="モードA: 1 wave あたりの並列上限（既定 5、推奨 3〜5）。"
        "モードB: spawnするteammate数の目安（強制はしない）",
    )
    ap.add_argument("--out-md", help="waves.md 出力先")
    ap.add_argument("--out-json", help="waves.json 出力先")
    ap.add_argument(
        "--out-prompts",
        help="agent teams 引き渡し用プロンプト（handoff.md）の出力先",
    )
    args = ap.parse_args()

    if args.max_teammates < 1:
        sys.exit("[schedule_waves] --max-teammates は 1 以上。")
    if not (3 <= args.max_teammates <= 5):
        print(
            f"[schedule_waves] 注記: teammate={args.max_teammates}。"
            "元ガイドの推奨は 3〜5（トークンが teammate 数に線形、実験段階）。",
            file=sys.stderr,
        )

    dag = load(args.dag)
    tasks = dag.get("tasks", [])
    if not tasks:
        sys.exit("[schedule_waves] タスクが空です。")
    guard(tasks)

    if args.mode == "wave":
        waves = schedule(tasks, args.max_teammates)
        out = build_output(dag, waves, args.max_teammates)

        s = out["summary"]
        print(
            f"[schedule_waves] mode=wave: {s['total_tasks']} tasks -> {s['total_waves']} waves "
            f"(最大並列 {s['max_parallel_width']}, 物理直列化 {s['delayed_by_file_conflict_or_width']}件)"
        )
        for w in out["waves"]:
            print(f"  Wave {w['wave']}: {', '.join(w['tasks'])}")

        md_text = render_md(out, dag)
        prompt_text = render_handoff(out, dag)
    else:  # dag
        prio = transitive_dependents(tasks)
        order = priority_topo_order(tasks, prio)
        augmented, synthetic = build_synthetic_dag(tasks, order)
        out = build_dag_output(dag, tasks, order, augmented, synthetic, args.max_teammates)

        s = out["summary"]
        print(
            f"[schedule_waves] mode=dag: {s['total_tasks']} tasks, "
            f"論理エッジ {s['logical_edges']} + 疑似エッジ {s['synthetic_edges_added']} "
            f"(参考: 理論最大並列幅 {s['theoretical_max_width']}, 段数 {s['theoretical_depth']})"
        )

        md_text = render_dag_md(out)
        prompt_text = render_dag_handoff(out)

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[schedule_waves] -> {args.out_json}")
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(md_text, encoding="utf-8")
        print(f"[schedule_waves] -> {args.out_md}")
    if args.out_prompts:
        Path(args.out_prompts).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_prompts).write_text(prompt_text, encoding="utf-8")
        print(f"[schedule_waves] -> {args.out_prompts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
