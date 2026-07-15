#!/usr/bin/env python3
"""Teams CSV / 自由記述テキスト（txt / md）-> 正規化markdown。

CSVは message_id/parent_message_id を使いスレッド復元・発言者特定を行う確定実装。
入力カラム定義は docs/llm-wiki.md §7.3 / references/ingest.md を参照。

txt/md は人手でコピー&ペースト・転記されたチャットログを想定し、CSVが前提とする
message_id/parent_message_id を持たないため、スレッド復元・発言者ごとの構造抽出は
行わない。frontmatterを付与して本文をそのままラップするだけの決定論的パススルー
とし、決定・未解決の論点・非公式な知見の抽出はHOTL②でのLLM/人の判断に委ねる
（references/ingest.md「Teamsチャットの特性」参照）。

判断（要約・矛盾検出等）は行わない。構造の正規化のみ。
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TRUE_VALUES = {"true", "1", "yes", "y"}
REQUIRED_COLUMNS = ["message_id", "parent_message_id", "timestamp", "author_name", "body"]


@dataclass
class Message:
    message_id: str
    parent_message_id: str
    timestamp: str
    author_name: str
    author_email: str
    body: str
    channel_or_chat: str
    mentions: str
    message_type: str
    has_attachment: bool
    children: list["Message"] = field(default_factory=list)
    parent_missing: bool = False

    def sort_key(self):
        return parse_timestamp(self.timestamp)


def parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def load_messages(csv_path: Path) -> list[Message]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"必須カラムが不足しています: {missing}（実際のカラム: {reader.fieldnames}）")

        messages = []
        for row in reader:
            message_type = (row.get("message_type") or "message").strip()
            if message_type.lower() == "system":
                continue
            messages.append(
                Message(
                    message_id=(row.get("message_id") or "").strip(),
                    parent_message_id=(row.get("parent_message_id") or "").strip(),
                    timestamp=(row.get("timestamp") or "").strip(),
                    author_name=(row.get("author_name") or "").strip(),
                    author_email=(row.get("author_email") or "").strip(),
                    body=(row.get("body") or "").strip(),
                    channel_or_chat=(row.get("channel_or_chat") or "").strip(),
                    mentions=(row.get("mentions") or "").strip(),
                    message_type=message_type,
                    has_attachment=(row.get("has_attachment") or "").strip().lower() in TRUE_VALUES,
                )
            )
        return messages


def build_threads(messages: list[Message]) -> list[Message]:
    by_id = {m.message_id: m for m in messages if m.message_id}
    roots = []
    for m in messages:
        parent = by_id.get(m.parent_message_id) if m.parent_message_id else None
        if parent is not None and parent is not m:
            parent.children.append(m)
        else:
            m.parent_missing = bool(m.parent_message_id)
            roots.append(m)

    def sort_tree(node_list: list[Message]):
        node_list.sort(key=lambda m: m.sort_key())
        for node in node_list:
            sort_tree(node.children)

    sort_tree(roots)
    return roots


def render_message(m: Message, depth: int, is_root: bool, parent_missing: bool = False) -> list[str]:
    indent = "  " * depth
    continuation_indent = indent + "  "
    reply_marker = " (返信、親メッセージ未取得)" if parent_missing else ("" if is_root else " (返信)")
    attachment_marker = " [添付あり]" if m.has_attachment else ""
    body_lines = (m.body or "").splitlines() or [""]
    first_line = f"{indent}- **[{m.timestamp}] {m.author_name or '(不明)'}{reply_marker}:** {body_lines[0]}{attachment_marker}"
    lines = [first_line]
    lines.extend(f"{continuation_indent}{line}" for line in body_lines[1:])
    if m.mentions:
        lines.append(f"{continuation_indent}mentions: {m.mentions}")
    for child in m.children:
        lines.extend(render_message(child, depth + 1, is_root=False))
    return lines


def flatten(roots: list[Message]):
    stack = list(roots)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def render_markdown(csv_path: Path, roots: list[Message], all_messages: list[Message]) -> str:
    channels = sorted({m.channel_or_chat for m in all_messages if m.channel_or_chat})
    lines = [
        "---",
        "source_type: teams",
        f"original_file: {csv_path.as_posix()}",
        f"extracted_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"channels: [{', '.join(channels)}]" if channels else "channels: []",
        f"message_count: {len(all_messages)}",
        f"thread_count: {len(roots)}",
        "---",
        "",
        f"# Teams チャット抽出: {csv_path.name}",
        "",
    ]
    for i, root in enumerate(roots, start=1):
        lines.append(f"## スレッド {i}")
        lines.extend(render_message(root, depth=0, is_root=True, parent_missing=root.parent_missing))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_markdown_plain(source_path: Path, source_format: str, body: str) -> str:
    lines = [
        "---",
        "source_type: teams",
        f"source_format: {source_format}",
        f"original_file: {source_path.as_posix()}",
        f"extracted_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "channels: []",
        "---",
        "",
        f"# Teams チャット抽出: {source_path.name}",
        "",
        "## 本文",
        "",
        body.strip(),
        "",
        "> スレッド復元（`parent_message_id`）・発言者ごとの構造抽出は行っていません"
        "（自由記述のテキストのため）。HOTL②で内容を確認し、Teamsチャットの特性"
        "（逐語要約ではなく決定・未解決の論点・非公式な知見の抽出に振り切る、"
        "references/ingest.md参照）を踏まえてwikiへ反映してください。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        messages = load_messages(path)
        roots = build_threads(messages)
        all_messages = list(flatten(roots))
        return render_markdown(path, roots, all_messages)
    elif suffix in (".txt", ".md"):
        body = path.read_text(encoding="utf-8")
        source_format = suffix.lstrip(".")
        return render_markdown_plain(path, source_format, body)
    else:
        raise ValueError(f"未対応の拡張子です: {suffix}（.csv / .txt / .md）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Teams CSV / txt / md ファイル")
    parser.add_argument("-o", "--output", type=Path, default=None, help="出力先md（省略時は入力と同じディレクトリ・同名.md）")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 1

    try:
        markdown = extract(args.input)
    except ValueError as e:
        print(f"抽出に失敗しました: {e}", file=sys.stderr)
        return 1

    output_path = args.output or args.input.with_suffix(".md")
    if output_path.resolve() == args.input.resolve():
        print(
            f"出力先が入力ファイルと同一です: {output_path}"
            "（raw/は不変の一次ソースのため上書きできません。-o で別名の出力先を指定してください）",
            file=sys.stderr,
        )
        return 1
    output_path.write_text(markdown, encoding="utf-8")
    print(f"書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
