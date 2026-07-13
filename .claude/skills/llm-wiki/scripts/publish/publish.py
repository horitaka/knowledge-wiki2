#!/usr/bin/env python3
"""wiki/ 配下のページを Confluence Cloud へ publish するための決定論的スクリプト。

references/publish.md の仕様に対応する。重要な制約: このスクリプトは Atlassian MCP の
ツール（createConfluencePage / updateConfluencePage）を**自分では呼び出せない**。
MCPツールを呼べるのはClaude Code agent（LLM）だけであり、Pythonプロセスからは呼べない。

そのため役割を分割する。
- `plan`  : 対象ページを走査し、create/update/skip/blocked を判定してdry-run結果を表示する
            （sync_state.jsonへの書き込みは行わない。読むだけ）
- `record`: agentがMCPツールを呼んでpage-idを得た**後**に、その結果を
            sync_state.json とページ本体のfrontmatter（confluence_id/confluence_space）へ
            書き戻す（本文・他のフィールドは一切書き換えない）

公開フロー: ingest → git commit → `plan`（dry-run） → 人の承認（HOTL③） →
agentがMCP発火 → 各ページごとに `record` → agentが wiki/log.md に結果を追記。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FRONTMATTER_DELIM = "---"
DIR_TYPE_MAP = {
    "entities": "entity",
    "concepts": "concept",
    "decisions": "decision",
    "open_questions": "open_question",
    "summaries": "summary",
}
VALID_TYPES = set(DIR_TYPE_MAP.values()) | {"overview"}

SIZE_LIMIT_BYTES = 50 * 1024  # references/publish.md: 目安50KB未満
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")

DEFAULT_SYNC_STATE = Path(__file__).resolve().parent / "sync_state.json"
DEFAULT_PLAN_OUT = Path(__file__).resolve().parent / "plan.json"


@dataclass
class Page:
    path: Path  # repo-root相対
    fields: dict
    fm_lines: list[str] | None
    body: str
    raw_text: str


@dataclass
class Item:
    path: str
    title: str | None
    action: str  # create | update | skip_unchanged | skip_draft | blocked
    confluence_id: str | None
    confluence_space: str | None
    content_hash: str
    previous_hash: str | None
    size_bytes: int
    violations: list[str] = field(default_factory=list)
    body: str = ""


def expected_type_for(path: Path, wiki_dir: Path) -> str | None:
    rel = path.relative_to(wiki_dir)
    if len(rel.parts) == 2:
        return DIR_TYPE_MAP.get(rel.parts[0])
    if rel.name == "overview.md":
        return "overview"
    return None  # index.md / log.md は公開対象外（内部ルーティング/監査ログ）


def split_frontmatter(text: str) -> tuple[list[str] | None, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            return lines[1:i], "\n".join(lines[i + 1 :])
    return None, text


def parse_frontmatter_fields(fm_lines: list[str]) -> dict:
    fields: dict = {}
    i, n = 0, len(fm_lines)
    while i < n:
        line = fm_lines[i]
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fields[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner else []
            i += 1
        elif value == "":
            items = []
            j = i + 1
            while j < n and re.match(r"^\s*-\s+\S", fm_lines[j]):
                items.append(re.sub(r"^\s*-\s+", "", fm_lines[j]).strip())
                j += 1
            fields[key] = items if items else None
            i = j if items else i + 1
        else:
            fields[key] = value
            i += 1
    return fields


def load_page(path: Path, repo_root: Path) -> Page:
    raw_text = path.read_text(encoding="utf-8")
    fm_lines, body = split_frontmatter(raw_text)
    fields = parse_frontmatter_fields(fm_lines) if fm_lines is not None else {}
    return Page(
        path=path.relative_to(repo_root),
        fields=fields,
        fm_lines=fm_lines,
        body=body,
        raw_text=raw_text,
    )


def collect_publishable_pages(wiki_dir: Path, repo_root: Path) -> list[Page]:
    pages = []
    for p in sorted(wiki_dir.rglob("*.md")):
        if expected_type_for(p, wiki_dir) is None:
            continue  # index.md / log.md
        page = load_page(p, repo_root)
        if page.fields.get("type") not in VALID_TYPES:
            continue  # frontmatter不正はlintの仕事。publishはスキップするだけ
        pages.append(page)
    return pages


def content_hash(title: str, body: str) -> str:
    digest = hashlib.sha256(f"{title}\n{body}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def check_constraints(body: str, size_bytes: int) -> list[str]:
    violations = []
    if size_bytes >= SIZE_LIMIT_BYTES:
        violations.append(
            f"本文サイズが{size_bytes}バイトで上限目安{SIZE_LIMIT_BYTES}バイトを超過（MCP呼び出しがタイムアウトする恐れ）"
        )
    if IMAGE_RE.search(body):
        violations.append("画像の埋め込み（![alt](path)）を検出。テキストのみ公開の方針に反する（参照リンクに置き換える）")
    return violations


def load_sync_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_item(page: Page, sync_state: dict, default_space: str | None) -> Item:
    path_str = page.path.as_posix()
    title = page.fields.get("title")
    status = page.fields.get("status")
    body = page.body
    size_bytes = len(body.encode("utf-8"))
    new_hash = content_hash(title or "", body)
    violations = check_constraints(body, size_bytes)

    existing = sync_state.get(path_str)
    previous_hash = existing.get("content_hash") if existing else None

    fm_confluence_id = page.fields.get("confluence_id")
    fm_confluence_space = page.fields.get("confluence_space")
    existing_id = existing.get("confluence_id") if existing else None
    existing_space = existing.get("confluence_space") if existing else None

    if fm_confluence_id and existing_id and fm_confluence_id != existing_id:
        violations.append(
            f"frontmatterのconfluence_id（{fm_confluence_id}）とsync_state.json（{existing_id}）が不一致。手動で確認が必要"
        )

    confluence_id = fm_confluence_id or existing_id
    confluence_space = fm_confluence_space or existing_space or default_space

    if status == "draft":
        return Item(path_str, title, "skip_draft", confluence_id, confluence_space, new_hash, previous_hash, size_bytes, violations, body)

    if violations:
        return Item(path_str, title, "blocked", confluence_id, confluence_space, new_hash, previous_hash, size_bytes, violations, body)

    if confluence_id:
        if previous_hash == new_hash:
            action = "skip_unchanged"
        else:
            action = "update"
    else:
        if not confluence_space:
            violations.append("confluence_spaceが未指定（新規作成には --default-space かページfrontmatterのconfluence_spaceが必要）")
            return Item(path_str, title, "blocked", confluence_id, confluence_space, new_hash, previous_hash, size_bytes, violations, body)
        action = "create"

    return Item(path_str, title, action, confluence_id, confluence_space, new_hash, previous_hash, size_bytes, violations, body)


def run_plan(wiki_dir: Path, repo_root: Path, sync_state_path: Path, default_space: str | None) -> list[Item]:
    pages = collect_publishable_pages(wiki_dir, repo_root)
    sync_state = load_sync_state(sync_state_path)
    return [build_item(page, sync_state, default_space) for page in pages]


def format_plan_report(items: list[Item]) -> str:
    lines = []
    counts: dict[str, int] = {}
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1

    order = ["blocked", "create", "update", "skip_unchanged", "skip_draft"]
    summary = " / ".join(f"{a}:{counts.get(a, 0)}" for a in order)
    lines.append(f"publish plan: {summary}")
    lines.append("")

    if counts.get("blocked"):
        lines.append("## blocked（要対応。承認前にこれらを解消すること）")
        for item in items:
            if item.action == "blocked":
                lines.append(f"- {item.path}")
                for v in item.violations:
                    lines.append(f"    - {v}")
        lines.append("")

    if counts.get("create"):
        lines.append("## create（新規公開）")
        for item in items:
            if item.action == "create":
                lines.append(f"- {item.path} -> space={item.confluence_space} ({item.size_bytes}B)")
        lines.append("")

    if counts.get("update"):
        lines.append("## update（内容変更あり）")
        for item in items:
            if item.action == "update":
                lines.append(
                    f"- {item.path} -> page_id={item.confluence_id} space={item.confluence_space} "
                    f"({item.previous_hash} -> {item.content_hash})"
                )
        lines.append("")

    if counts.get("skip_unchanged"):
        lines.append(f"## skip_unchanged（変化なし、{counts['skip_unchanged']}件）")
        for item in items:
            if item.action == "skip_unchanged":
                lines.append(f"- {item.path}")
        lines.append("")

    if counts.get("skip_draft"):
        lines.append(f"## skip_draft（status: draftのため対象外、{counts['skip_draft']}件）")
        for item in items:
            if item.action == "skip_draft":
                lines.append(f"- {item.path}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_plan_json(items: list[Item], out_path: Path) -> None:
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "items": [
            {
                "path": item.path,
                "title": item.title,
                "action": item.action,
                "confluence_id": item.confluence_id,
                "confluence_space": item.confluence_space,
                "content_hash": item.content_hash,
                "previous_hash": item.previous_hash,
                "size_bytes": item.size_bytes,
                "violations": item.violations,
                "body": item.body,
            }
            for item in items
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_plan(args: argparse.Namespace) -> int:
    wiki_dir = args.wiki_dir.resolve()
    if not wiki_dir.is_dir():
        print(f"wikiディレクトリが見つかりません: {wiki_dir}", file=sys.stderr)
        return 1
    repo_root = wiki_dir.parent

    items = run_plan(wiki_dir, repo_root, args.sync_state, args.default_space)
    print(format_plan_report(items))

    if args.out:
        write_plan_json(items, args.out)
        print(f"(agent向け詳細plan（本文含む）を書き出し: {args.out})")

    return 1 if any(item.action == "blocked" for item in items) else 0


def set_frontmatter_fields(raw_text: str, updates: dict) -> str:
    fm_lines, body = split_frontmatter(raw_text)
    if fm_lines is None:
        raise ValueError("frontmatterブロックが存在しないページはrecordできない")

    new_lines: list[str] = []
    seen = set()
    for line in fm_lines:
        m = re.match(r"^(\w+):\s*.*$", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            new_lines.append(f"{key}: {updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}: {value}")

    return "\n".join([FRONTMATTER_DELIM, *new_lines, FRONTMATTER_DELIM]) + "\n" + body


def cmd_record(args: argparse.Namespace) -> int:
    wiki_dir = args.wiki_dir.resolve()
    repo_root = wiki_dir.parent
    page_path = (repo_root / args.page).resolve() if not args.page.is_absolute() else args.page
    if not page_path.exists():
        print(f"ページが見つかりません: {page_path}", file=sys.stderr)
        return 1

    page = load_page(page_path, repo_root)
    new_hash = content_hash(page.fields.get("title") or "", page.body)

    updated_text = set_frontmatter_fields(
        page.raw_text,
        {"confluence_id": args.confluence_id, "confluence_space": args.confluence_space},
    )
    page_path.write_text(updated_text, encoding="utf-8")

    sync_state = load_sync_state(args.sync_state)
    sync_state[page.path.as_posix()] = {
        "confluence_id": args.confluence_id,
        "confluence_space": args.confluence_space,
        "content_hash": new_hash,
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    args.sync_state.write_text(json.dumps(sync_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"記録しました: {page.path.as_posix()} -> confluence_id={args.confluence_id} space={args.confluence_space}")
    print("(wiki/log.mdへのpublishエントリ追記は別途agentが行うこと)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="dry-run: create/update/skip/blockedを判定して表示する（状態は書き換えない）")
    plan_p.add_argument("--wiki-dir", type=Path, default=Path("wiki"))
    plan_p.add_argument("--sync-state", type=Path, default=DEFAULT_SYNC_STATE)
    plan_p.add_argument("--default-space", type=str, default=None, help="新規作成ページのconfluence_spaceの既定値（frontmatter未指定時に使用）")
    plan_p.add_argument("--out", type=str, default=str(DEFAULT_PLAN_OUT), help="agent向けの詳細plan（本文含むJSON）の出力先。空文字で無効化")
    plan_p.set_defaults(func=cmd_plan)

    record_p = sub.add_parser("record", help="agentがMCP発火後に、page-idをsync_state.jsonとfrontmatterへ書き戻す")
    record_p.add_argument("--page", type=Path, required=True, help="対象ページのパス（repo-root相対 or 絶対パス）")
    record_p.add_argument("--confluence-id", type=str, required=True)
    record_p.add_argument("--confluence-space", type=str, required=True)
    record_p.add_argument("--wiki-dir", type=Path, default=Path("wiki"))
    record_p.add_argument("--sync-state", type=Path, default=DEFAULT_SYNC_STATE)
    record_p.set_defaults(func=cmd_record)

    args = parser.parse_args()
    if args.command == "plan":
        args.out = Path(args.out) if args.out else None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
