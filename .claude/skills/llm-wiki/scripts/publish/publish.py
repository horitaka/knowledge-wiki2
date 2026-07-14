#!/usr/bin/env python3
"""wiki/ 配下のページを Confluence Cloud へ publish するための決定論的スクリプト。

references/publish.md の仕様に対応する。重要な制約: このスクリプトは Atlassian MCP の
ツール（createConfluencePage / updateConfluencePage）を**自分では呼び出せない**。
MCPツールを呼べるのはClaude Code agent（LLM）だけであり、Pythonプロセスからは呼べない。

そのため役割を分割する。
- `configure`: 初回publish前に、公開先space・親ページIDを設定ファイル
              （publish_config.json）へ記録する（1リポジトリ=1スペース=1親ページ配下という前提）。
              ユーザーからの指定が必要な値。
- `plan`     : 対象ページ・フォルダを走査し、create/update/skip/blocked を判定してdry-run結果を
              表示する（sync_state.jsonへの書き込みは行わない。読むだけ）。
              wiki/entities 等のディレクトリはConfluence側にも対応するフォルダページとして
              作られ、その配下にリポジトリのフォルダ構造を再現する。
- `record`   : agentがMCPツールを呼んでpage-idを得た**後**に、その結果を
              sync_state.json （フォルダページ・コンテンツページ共通）と、コンテンツページ
              本体のfrontmatter（confluence_idのみ）へ書き戻す（本文・他のフィールドは
              一切書き換えない）。

公開フロー: ingest → git commit → （初回のみ）`configure` → `plan`（dry-run） →
人の承認（HOTL③） → agentがMCP発火（フォルダページ→配下ページの順） →
呼び出しごとに `record` → agentが wiki/log.md に結果を追記。
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

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SYNC_STATE = SCRIPT_DIR / "sync_state.json"
DEFAULT_PLAN_OUT = SCRIPT_DIR / "plan.json"
DEFAULT_CONFIG = SCRIPT_DIR / "publish_config.json"


@dataclass
class Page:
    path: Path  # repo-root相対
    fields: dict
    fm_lines: list[str] | None
    body: str
    raw_text: str


@dataclass
class FolderItem:
    key: str  # ディレクトリ名（例: "entities"）
    title: str
    action: str  # create_folder | exists
    confluence_id: str | None


@dataclass
class Item:
    path: str
    title: str | None
    action: str  # create | update | skip_unchanged | skip_draft | blocked
    confluence_id: str | None
    parent_key: str | None  # 配下フォルダ名。overview等はNone（親ページ直下）
    parent_confluence_id: str | None  # 未作成フォルダの場合はNone
    content_hash: str
    previous_hash: str | None
    size_bytes: int
    violations: list[str] = field(default_factory=list)
    body: str = ""


def folder_sync_key(dirname: str) -> str:
    return f"wiki/{dirname}"


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


def save_sync_state(path: Path, sync_state: dict) -> None:
    path.write_text(json.dumps(sync_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, space: str, root_page_id: str) -> None:
    payload = {
        "space": space,
        "root_page_id": root_page_id,
        "configured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parent_key_for(page: Page) -> str | None:
    parts = page.path.parts  # 例: ('wiki', 'entities', 'x.md') / ('wiki', 'overview.md')
    if len(parts) == 3:
        return parts[1]
    return None  # overview.md 等、wiki/ 直下のページは親ページ直下


def build_folders(pages: list[Page], sync_state: dict) -> list[FolderItem]:
    dirnames = sorted({parent_key_for(p) for p in pages if parent_key_for(p) is not None})
    folders = []
    for dirname in dirnames:
        existing = sync_state.get(folder_sync_key(dirname))
        if existing and existing.get("confluence_id"):
            folders.append(FolderItem(dirname, dirname, "exists", existing["confluence_id"]))
        else:
            folders.append(FolderItem(dirname, dirname, "create_folder", None))
    return folders


def build_item(page: Page, sync_state: dict, root_page_id: str) -> Item:
    path_str = page.path.as_posix()
    title = page.fields.get("title")
    status = page.fields.get("status")
    body = page.body
    size_bytes = len(body.encode("utf-8"))
    new_hash = content_hash(title or "", body)
    violations = check_constraints(body, size_bytes)

    p_key = parent_key_for(page)
    if p_key is None:
        parent_confluence_id = root_page_id
    else:
        folder_state = sync_state.get(folder_sync_key(p_key))
        parent_confluence_id = folder_state.get("confluence_id") if folder_state else None

    existing = sync_state.get(path_str)
    previous_hash = existing.get("content_hash") if existing else None

    fm_confluence_id = page.fields.get("confluence_id")
    existing_id = existing.get("confluence_id") if existing else None

    if fm_confluence_id and existing_id and fm_confluence_id != existing_id:
        violations.append(
            f"frontmatterのconfluence_id（{fm_confluence_id}）とsync_state.json（{existing_id}）が不一致。手動で確認が必要"
        )

    confluence_id = fm_confluence_id or existing_id

    if status == "draft":
        return Item(path_str, title, "skip_draft", confluence_id, p_key, parent_confluence_id, new_hash, previous_hash, size_bytes, violations, body)

    if violations:
        return Item(path_str, title, "blocked", confluence_id, p_key, parent_confluence_id, new_hash, previous_hash, size_bytes, violations, body)

    if confluence_id:
        action = "skip_unchanged" if previous_hash == new_hash else "update"
    else:
        action = "create"

    return Item(path_str, title, action, confluence_id, p_key, parent_confluence_id, new_hash, previous_hash, size_bytes, violations, body)


def run_plan(wiki_dir: Path, repo_root: Path, sync_state_path: Path, root_page_id: str) -> tuple[list[FolderItem], list[Item]]:
    pages = collect_publishable_pages(wiki_dir, repo_root)
    sync_state = load_sync_state(sync_state_path)
    folders = build_folders(pages, sync_state)
    items = [build_item(page, sync_state, root_page_id) for page in pages]
    return folders, items


def format_plan_report(config: dict, folders: list[FolderItem], items: list[Item]) -> str:
    lines = []
    lines.append(f"space={config['space']} root_page_id={config['root_page_id']}")
    lines.append("")

    counts: dict[str, int] = {}
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1

    folders_to_create = [f for f in folders if f.action == "create_folder"]
    if folders_to_create:
        lines.append("## folders（配下ページより先に作成すること。親=root_page_id）")
        for f in folders_to_create:
            lines.append(f"- {f.key} (folder)")
        lines.append("")

    order = ["blocked", "create", "update", "skip_unchanged", "skip_draft"]
    summary = " / ".join(f"{a}:{counts.get(a, 0)}" for a in order)
    lines.append(f"pages: {summary}")
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
                parent_desc = item.parent_confluence_id or "(この回のfolder作成後に確定)"
                lines.append(f"- {item.path} -> parent={item.parent_key or 'root'}({parent_desc}) ({item.size_bytes}B)")
        lines.append("")

    if counts.get("update"):
        lines.append("## update（内容変更あり）")
        for item in items:
            if item.action == "update":
                lines.append(
                    f"- {item.path} -> page_id={item.confluence_id} "
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


def write_plan_json(config: dict, folders: list[FolderItem], items: list[Item], out_path: Path) -> None:
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "space": config["space"],
        "root_page_id": config["root_page_id"],
        "folders": [
            {
                "key": f.key,
                "title": f.title,
                "action": f.action,
                "confluence_id": f.confluence_id,
                "parent_confluence_id": config["root_page_id"],
            }
            for f in folders
        ],
        "items": [
            {
                "path": item.path,
                "title": item.title,
                "action": item.action,
                "confluence_id": item.confluence_id,
                "parent_key": item.parent_key,
                "parent_confluence_id": item.parent_confluence_id,
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


def cmd_configure(args: argparse.Namespace) -> int:
    existing = load_config(args.config)

    if existing and not args.force:
        conflicting = (
            (args.space and args.space != existing.get("space"))
            or (args.root_page_id and args.root_page_id != existing.get("root_page_id"))
        )
        if conflicting:
            print(
                "既にpublish設定が存在します（変更するには --force が必要です）:\n"
                f"  現在: space={existing.get('space')} root_page_id={existing.get('root_page_id')}\n"
                f"  指定: space={args.space or '(変更なし)'} root_page_id={args.root_page_id or '(変更なし)'}\n"
                "注意: root_page_id/space を変更しても、既存に作成済みのフォルダ・ページの"
                "sync_state.jsonエントリは自動移行されない。",
                file=sys.stderr,
            )
            return 1

    new_space = args.space or existing.get("space")
    new_root = args.root_page_id or existing.get("root_page_id")

    if not new_space or not new_root:
        print(
            "space と root-page-id の両方が必要です（--space <SPACEKEY> --root-page-id <親ページID>）。",
            file=sys.stderr,
        )
        return 1

    save_config(args.config, new_space, new_root)
    print(f"publish設定を保存しました: space={new_space} root_page_id={new_root} ({args.config})")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    wiki_dir = args.wiki_dir.resolve()
    if not wiki_dir.is_dir():
        print(f"wikiディレクトリが見つかりません: {wiki_dir}", file=sys.stderr)
        return 1
    repo_root = wiki_dir.parent

    config = load_config(args.config)
    if not config.get("space") or not config.get("root_page_id"):
        print(
            "publish未設定です。space（Confluenceスペースキー）と root_page_id（公開先の親ページID）が"
            f"設定されていません（{args.config}）。\n"
            "ユーザーに確認のうえ、以下を実行してください:\n"
            "  python3 scripts/publish/publish.py configure --space <SPACEKEY> --root-page-id <親ページID>",
            file=sys.stderr,
        )
        return 2

    folders, items = run_plan(wiki_dir, repo_root, args.sync_state, config["root_page_id"])
    print(format_plan_report(config, folders, items))

    if args.out:
        write_plan_json(config, folders, items, args.out)
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
    sync_state = load_sync_state(args.sync_state)

    if args.folder:
        if args.folder not in DIR_TYPE_MAP:
            print(
                f"未知のfolder名です: {args.folder}（有効な値: {', '.join(sorted(DIR_TYPE_MAP))}）",
                file=sys.stderr,
            )
            return 1
        key = folder_sync_key(args.folder)
        sync_state[key] = {
            "confluence_id": args.confluence_id,
            "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        save_sync_state(args.sync_state, sync_state)
        print(f"記録しました: folder={args.folder} -> confluence_id={args.confluence_id}")
        return 0

    wiki_dir = args.wiki_dir.resolve()
    repo_root = wiki_dir.parent
    page_path = (repo_root / args.page).resolve() if not args.page.is_absolute() else args.page
    if not page_path.exists():
        print(f"ページが見つかりません: {page_path}", file=sys.stderr)
        return 1

    page = load_page(page_path, repo_root)
    new_hash = content_hash(page.fields.get("title") or "", page.body)

    updated_text = set_frontmatter_fields(page.raw_text, {"confluence_id": args.confluence_id})
    page_path.write_text(updated_text, encoding="utf-8")

    sync_state[page.path.as_posix()] = {
        "confluence_id": args.confluence_id,
        "content_hash": new_hash,
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    save_sync_state(args.sync_state, sync_state)

    print(f"記録しました: {page.path.as_posix()} -> confluence_id={args.confluence_id}")
    print("(wiki/log.mdへのpublishエントリ追記は別途agentが行うこと)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    configure_p = sub.add_parser(
        "configure",
        help="初回publish前に space・root_page_id（親ページID）を publish_config.json へ保存する",
    )
    configure_p.add_argument("--space", type=str, default=None, help="公開先Confluenceスペースキー")
    configure_p.add_argument("--root-page-id", type=str, default=None, help="配下にwikiを再現する親ページのConfluence page-id")
    configure_p.add_argument("--force", action="store_true", help="既存設定と異なる値への変更を許可する")
    configure_p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    configure_p.set_defaults(func=cmd_configure)

    plan_p = sub.add_parser("plan", help="dry-run: フォルダ/create/update/skip/blockedを判定して表示する（状態は書き換えない）")
    plan_p.add_argument("--wiki-dir", type=Path, default=Path("wiki"))
    plan_p.add_argument("--sync-state", type=Path, default=DEFAULT_SYNC_STATE)
    plan_p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    plan_p.add_argument("--out", type=str, default=str(DEFAULT_PLAN_OUT), help="agent向けの詳細plan（本文含むJSON）の出力先。空文字で無効化")
    plan_p.set_defaults(func=cmd_plan)

    record_p = sub.add_parser("record", help="agentがMCP発火後に、page-idをsync_state.json（と該当すればfrontmatter）へ書き戻す")
    record_target = record_p.add_mutually_exclusive_group(required=True)
    record_target.add_argument("--page", type=Path, help="対象ページのパス（repo-root相対 or 絶対パス）")
    record_target.add_argument("--folder", type=str, help="対象フォルダ名（例: entities）。フォルダページ作成の記録用")
    record_p.add_argument("--confluence-id", type=str, required=True)
    record_p.add_argument("--wiki-dir", type=Path, default=Path("wiki"))
    record_p.add_argument("--sync-state", type=Path, default=DEFAULT_SYNC_STATE)
    record_p.set_defaults(func=cmd_record)

    args = parser.parse_args()
    if args.command == "plan":
        args.out = Path(args.out) if args.out else None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
