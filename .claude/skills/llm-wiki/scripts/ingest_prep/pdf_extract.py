#!/usr/bin/env python3
"""PDF（進捗デッキ、またはIRM保護docxをPDF変換した議事録）-> 正規化markdown。

IRM/Azure RMS保護されたpptx/docxはmsoffcrypto-toolでは復号できないため
（office_crypto.py参照）、その代替導線として「閲覧・印刷/エクスポート権限を
持つ人がOffice上でPDFとして保存し、そのPDFを本スクリプトで抽出する」運用を
想定する（office_crypto.IRM_GUIDANCE参照）。

PDFはpptx/docxと異なりタイトル・本文・表・スピーカーノートの構造情報を
保持しないため、ページ単位でテキストをそのまま書き出す（本文/表の区別はしない）。
画像は枚数のみ記録する（Confluenceへは非公開 — docs/llm-wiki.md §7.2 / §9.3 と同様）。

判断（要約等）は行わない。構造の正規化のみ。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


def load_reader(path: Path):
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "pypdf が必要です（pip install pypdf）。"
            "requirements.txt を参照してください。"
        ) from e

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise RuntimeError(
            "このPDFはパスワードで保護されています。本スクリプトはPDFの復号には対応していません。"
            "パスワードを解除した複製をraw/に配置し直してから再実行してください。"
        )
    return reader


def extract_page(page, index: int) -> list[str]:
    lines = [f"## Page {index}", ""]
    text = (page.extract_text() or "").strip()
    if text:
        for line in text.splitlines():
            line = line.strip()
            if line:
                lines.append(f"- {line}")
        lines.append("")

    image_count = len(list(page.images))
    if image_count:
        lines.append(f"（画像 {image_count} 件あり — Confluence非公開、raw/decksの原本を参照）")
        lines.append("")

    return lines


def render_markdown(pdf_path: Path, reader, source_type: str) -> str:
    heading = "進捗デッキ" if source_type == "deck" else "会議トランスクリプト"
    lines = [
        "---",
        f"source_type: {source_type}",
        "source_format: pdf",
        f"original_file: {pdf_path.as_posix()}",
        f"extracted_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"page_count: {len(reader.pages)}",
        "---",
        "",
        f"# {heading}: {pdf_path.stem}",
        "",
    ]
    for i, page in enumerate(reader.pages, start=1):
        lines.extend(extract_page(page, i))
    return "\n".join(lines).rstrip() + "\n"


def extract(path: Path, source_type: str = "deck") -> str:
    reader = load_reader(path)
    return render_markdown(path, reader, source_type)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="pdfファイル")
    parser.add_argument("-o", "--output", type=Path, default=None, help="出力先md（省略時は入力と同じディレクトリ・同名.md）")
    parser.add_argument(
        "--source-type",
        choices=["deck", "transcript"],
        default="deck",
        help="frontmatterのsource_type（デフォルト: deck。IRM保護docxをPDF化して議事録として投入する場合は transcript を指定）",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 1

    try:
        markdown = extract(args.input, source_type=args.source_type)
    except RuntimeError as e:
        print(f"抽出に失敗しました: {e}", file=sys.stderr)
        return 1

    output_path = args.output or args.input.with_suffix(".md")
    output_path.write_text(markdown, encoding="utf-8")
    print(f"書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
