#!/usr/bin/env python3
"""
bootstrap_worktree.py — wave-scheduler が出す waves.json を読み、指定した wave の
各タスクぶん git worktree を作成し、.env のコピー・`uv sync`・スモークチェックまでを
一括実行する。並列実装パイプライン工程6（agent teams + worktree 実装）の前段。

やること:
  1) base ブランチ（既定 main）を fetch し、その最新コミットから新規ブランチ + worktree を作成
  2) repo root の .env を worktree にコピー（無ければ警告のみ、致命的エラーにしない）
  3) worktree 内で `uv sync` を実行し、依存関係を構築
  4) スモークチェック（既定 `uv run pytest --collect-only -q`）で import 崩れがないか確認

やらないこと:
  - 実装そのもの・PR作成・マージ・worktree の削除（それぞれ別の関心事）
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    branch: str
    worktree_path: Path


@dataclass(frozen=True)
class StepResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    branch: str
    worktree_path: Path
    worktree: StepResult
    env_copy: StepResult
    uv_sync: StepResult
    smoke: StepResult

    @property
    def ok(self) -> bool:
        return all(s.ok for s in (self.worktree, self.env_copy, self.uv_sync, self.smoke))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def slugify(text: str) -> str:
    """ASCII 英数字だけを残した slug を作る。

    タイトルが日本語など非ASCIIのみで構成される場合は空文字になり、
    呼び出し側（build_branch_name）がタスクIDのみのブランチ名にフォールバックする。
    """
    keep = [c.lower() if c.isascii() and c.isalnum() else "-" for c in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def load_titles(dag_path: Path | None) -> dict[str, str]:
    """dependency-mapper が出す plan.dag.json の title からタスクID→タイトルを引く。

    plan.dag.json のスキーマはリポジトリ非依存（dependency-mapper スキル共通の出力形式）
    なので、ここではリポジトリ固有のディレクトリ構成やファイル命名規則を一切前提にしない。
    """
    if dag_path is None or not dag_path.is_file():
        return {}
    data = json.loads(dag_path.read_text(encoding="utf-8"))
    return {t["id"]: t.get("title", "") for t in data.get("tasks", [])}


def build_branch_name(task_id: str, title: str, prefix: str) -> str:
    slug = slugify(title)
    if slug:
        return f"{prefix}{task_id.lower()}-{slug}"
    return f"{prefix}{task_id.lower()}"


def fetch_base(repo_root: Path, base: str) -> StepResult:
    result = run(["git", "fetch", "origin", base], cwd=repo_root)
    if result.returncode == 0:
        return StepResult(True, f"origin/{base} を fetch 済み")
    return StepResult(
        False,
        f"fetch 失敗（{result.stderr.strip()[:200]}）。ローカルの {base} で分岐します",
    )


def resolve_base_ref(repo_root: Path, base: str, fetch_ok: bool) -> str:
    if fetch_ok:
        check = run(["git", "rev-parse", "--verify", f"origin/{base}"], cwd=repo_root)
        if check.returncode == 0:
            return f"origin/{base}"
    return base


def create_worktree(
    repo_root: Path,
    branch: str,
    path: Path,
    base_ref: str,
    dry_run: bool,
    force: bool,
) -> StepResult:
    if path.exists():
        if force:
            remove = run(["git", "worktree", "remove", "--force", str(path)], cwd=repo_root)
            if remove.returncode != 0:
                return StepResult(
                    False, f"既存 worktree の削除に失敗: {remove.stderr.strip()[:200]}"
                )
        else:
            return StepResult(True, f"既存 worktree を再利用: {path}（--force で作り直せます）")

    if dry_run:
        return StepResult(True, f"[dry-run] git worktree add -b {branch} {path} {base_ref}")

    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(["git", "worktree", "add", "-b", branch, str(path), base_ref], cwd=repo_root)
    if result.returncode == 0:
        return StepResult(True, f"{base_ref} から作成: {path}")
    return StepResult(False, result.stderr.strip()[:300])


def copy_env(repo_root: Path, worktree_path: Path, env_file: str, dry_run: bool) -> StepResult:
    src = repo_root / env_file
    if not src.is_file():
        return StepResult(False, f"{env_file} が repo root に無い（スキップ、手動配置が必要）")
    dst = worktree_path / env_file
    if dry_run:
        return StepResult(True, f"[dry-run] {src} -> {dst}")
    shutil.copy2(src, dst)
    return StepResult(True, f"{env_file} をコピー: {dst}")


def run_uv_sync(worktree_path: Path, skip: bool, dry_run: bool) -> StepResult:
    if skip:
        return StepResult(True, "スキップ（--no-sync）")
    if dry_run:
        return StepResult(True, "[dry-run] uv sync")
    result = run(["uv", "sync"], cwd=worktree_path)
    if result.returncode == 0:
        return StepResult(True, "uv sync 完了")
    return StepResult(False, result.stderr.strip()[:300])


def run_smoke(worktree_path: Path, smoke_cmd: str, skip: bool, dry_run: bool) -> StepResult:
    if skip:
        return StepResult(True, "スキップ（--no-smoke）")
    if dry_run:
        return StepResult(True, f"[dry-run] {smoke_cmd}")
    result = run(smoke_cmd.split(), cwd=worktree_path)
    if result.returncode == 0:
        return StepResult(True, "スモークチェック OK")
    return StepResult(False, (result.stderr or result.stdout).strip()[:300])


def bootstrap_one(
    repo_root: Path,
    spec: TaskSpec,
    base_ref: str,
    env_file: str,
    skip_sync: bool,
    skip_smoke: bool,
    smoke_cmd: str,
    dry_run: bool,
    force: bool,
) -> TaskResult:
    wt = create_worktree(repo_root, spec.branch, spec.worktree_path, base_ref, dry_run, force)
    if not wt.ok:
        blocked = StepResult(False, "worktree 作成失敗のためスキップ")
        return TaskResult(
            spec.task_id, spec.branch, spec.worktree_path, wt, blocked, blocked, blocked
        )

    env_result = copy_env(repo_root, spec.worktree_path, env_file, dry_run)
    sync_result = run_uv_sync(spec.worktree_path, skip_sync, dry_run)
    smoke_result = run_smoke(
        spec.worktree_path, smoke_cmd, skip_smoke or not sync_result.ok, dry_run
    )
    return TaskResult(
        spec.task_id, spec.branch, spec.worktree_path, wt, env_result, sync_result, smoke_result
    )


def load_task_ids(waves_json: Path, wave: int, task_id: str | None) -> list[str]:
    data = json.loads(waves_json.read_text(encoding="utf-8"))
    for w in data.get("waves", []):
        if w["wave"] == wave:
            ids = list(w["tasks"])
            if task_id:
                if task_id not in ids:
                    msg = f"task {task_id} は wave {wave} に含まれません（{ids}）"
                    sys.exit(f"[bootstrap_worktree] {msg}")
                return [task_id]
            return ids
    sys.exit(f"[bootstrap_worktree] wave {wave} が waves.json に見つかりません")


def print_report(results: list[TaskResult]) -> None:
    print()
    print(f"{'task':<6}{'branch':<32}{'worktree':<10}{'env':<10}{'uv sync':<10}{'smoke':<10}")
    for r in results:

        def mark(s: StepResult) -> str:
            return "OK" if s.ok else "NG"

        print(
            f"{r.task_id:<6}{r.branch:<32}{mark(r.worktree):<10}"
            f"{mark(r.env_copy):<10}{mark(r.uv_sync):<10}{mark(r.smoke):<10}"
        )
    print()
    for r in results:
        for label, step in (
            ("worktree", r.worktree),
            ("env", r.env_copy),
            ("uv sync", r.uv_sync),
            ("smoke", r.smoke),
        ):
            if not step.ok:
                print(f"  [{r.task_id}/{label}] {step.detail}")

    failed = [r.task_id for r in results if not r.ok]
    if failed:
        print(f"\n[bootstrap_worktree] 失敗: {failed}")
    else:
        print(f"\n[bootstrap_worktree] 全 {len(results)} worktree の準備完了")


def main() -> int:
    ap = argparse.ArgumentParser(description="wave 単位で worktree の環境構築を行う")
    ap.add_argument("--waves-json", type=Path, help="wave-scheduler が出力した waves.json")
    ap.add_argument("--wave", type=int, help="対象の wave 番号（--waves-json とセット）")
    ap.add_argument("--task-id", help="wave 内の特定タスクだけやり直したい場合に指定")
    ap.add_argument("--branch", help="waves.json を使わない ad-hoc モード：worktree のブランチ名")
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    ap.add_argument("--base", default="main", help="分岐元ブランチ（既定 main）")
    ap.add_argument("--worktrees-dir", type=Path, default=None, help="既定: ../<repo名>-worktrees")
    ap.add_argument(
        "--dag",
        type=Path,
        default=None,
        help="dependency-mapper が出力した plan.dag.json（あればタスクのtitleからブランチ名に"
        "slugを付与する。無ければタスクIDのみのブランチ名になる）",
    )
    ap.add_argument("--branch-prefix", default="fix/")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--smoke-cmd", default="uv run pytest --collect-only -q")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="既存 worktree を削除して作り直す")
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    if not (repo_root / ".git").exists():
        sys.exit(f"[bootstrap_worktree] {repo_root} は git repo のルートではありません")

    worktrees_dir = args.worktrees_dir or (repo_root.parent / f"{repo_root.name}-worktrees")
    dag_path = (repo_root / args.dag).resolve() if args.dag else None
    titles = load_titles(dag_path)

    if args.branch:
        ad_hoc = True
        task_ids: list[str] = [args.branch]
    elif args.waves_json and args.wave:
        ad_hoc = False
        task_ids = load_task_ids(args.waves_json, args.wave, args.task_id)
    else:
        sys.exit(
            "[bootstrap_worktree] --waves-json と --wave の組、または --branch のどちらかが必要です"
        )

    fetch_result = fetch_base(repo_root, args.base)
    print(f"[bootstrap_worktree] {fetch_result.detail}")
    base_ref = resolve_base_ref(repo_root, args.base, fetch_result.ok)

    specs: list[TaskSpec] = []
    if ad_hoc:
        branch = args.branch
        specs.append(TaskSpec(branch, branch, worktrees_dir / slugify(branch)))
    else:
        for tid in task_ids:
            branch = build_branch_name(tid, titles.get(tid, ""), args.branch_prefix)
            specs.append(TaskSpec(tid, branch, worktrees_dir / branch.split("/")[-1]))

    results = [
        bootstrap_one(
            repo_root,
            spec,
            base_ref,
            args.env_file,
            args.no_sync,
            args.no_smoke,
            args.smoke_cmd,
            args.dry_run,
            args.force,
        )
        for spec in specs
    ]

    print_report(results)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
