#!/usr/bin/env python3
"""会議トランスクリプト（VTT または Word .docx）-> 正規化markdown。

VTTは仕様が定まっているため確定実装。docx（MS Teamsトランスクリプトの
エクスポート）は実サンプル未検証のため best-effort なヒューリスティック実装。
docx側で構造を認識できなかった段落は "unparsed" として出力に残し、
サイレントに消さない（実サンプルでの検証・SKILL.mdの調整に使う）。

Microsoft情報保護ラベル（IRM/Azure RMS）で保護されたdocxは復号できないため、
明確なエラーで検出する（office_crypto.py参照）。開くパスワードで暗号化された
docxの復号（pptxのような）は未対応。

判断（要約・アクションアイテム/決定の抽出）は行わない。構造の正規化のみ。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
VOICE_TAG_RE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>)?$", re.DOTALL)
FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DOCX_SPEAKER_TIME_RE = re.compile(r"^(?P<speaker>.+?)\s{1,4}(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*$")


@dataclass
class Utterance:
    start: str
    end: str
    speaker: str
    text: str


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def parse_vtt(content: str) -> list[Utterance]:
    lines = content.replace("\r\n", "\n").split("\n")
    utterances: list[Utterance] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        m = TIMESTAMP_RE.search(line)
        if not m:
            i += 1
            continue
        start, end = m.group("start"), m.group("end")
        i += 1
        text_lines = []
        while i < n and lines[i].strip() != "" and not TIMESTAMP_RE.search(lines[i]):
            text_lines.append(lines[i])
            i += 1
        raw_text = " ".join(t.strip() for t in text_lines if t.strip())
        if not raw_text:
            continue
        voice_match = VOICE_TAG_RE.search(raw_text)
        if voice_match:
            speaker = voice_match.group(1).strip()
            text = strip_tags(voice_match.group(2)).strip()
        else:
            speaker = "(不明)"
            text = strip_tags(raw_text)
        if text:
            utterances.append(Utterance(start=start, end=end, speaker=speaker, text=text))
    return utterances


def parse_docx(path: Path) -> tuple[list[Utterance], list[str]]:
    try:
        import docx  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "python-docx が必要です（pip install python-docx）。"
            "requirements.txt を参照してください。"
        ) from e

    try:
        from office_crypto import is_encrypted
    except ImportError as e:
        raise RuntimeError(
            "msoffcrypto-tool が必要です（pip install msoffcrypto-tool）。"
            "requirements.txt を参照してください。"
        ) from e

    # IRM保護時は is_encrypted() が IRMProtectedError を送出する（そのまま呼び出し元へ伝播させる）。
    if is_encrypted(path):
        raise RuntimeError(
            "このdocxは開くパスワードで暗号化されています。"
            "本スクリプトはdocxのパスワード復号には未対応です"
            "（pptx_extract.pyのパスワード対応を参考に実装を追加してください）。"
        )

    document = docx.Document(str(path))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    utterances: list[Utterance] = []
    unparsed: list[str] = []
    current_speaker: str | None = None
    current_time: str | None = None
    buffer: list[str] = []

    def flush():
        if current_speaker is not None and buffer:
            utterances.append(
                Utterance(start=current_time or "", end="", speaker=current_speaker, text=" ".join(buffer))
            )

    for para in paragraphs:
        m = DOCX_SPEAKER_TIME_RE.match(para)
        if m:
            flush()
            current_speaker = m.group("speaker").strip()
            current_time = m.group("time").strip()
            buffer = []
        elif current_speaker is not None:
            buffer.append(para)
        else:
            unparsed.append(para)
    flush()

    return utterances, unparsed


def guess_date_from_filename(path: Path) -> str | None:
    m = FILENAME_DATE_RE.search(path.stem)
    return m.group(1) if m else None


def render_markdown(source_path: Path, source_format: str, utterances: list[Utterance], unparsed: list[str]) -> str:
    speakers = sorted({u.speaker for u in utterances if u.speaker and u.speaker != "(不明)"})
    date = guess_date_from_filename(source_path)

    lines = [
        "---",
        "source_type: transcript",
        f"source_format: {source_format}",
        f"original_file: {source_path.as_posix()}",
        f"extracted_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"meeting_date: {date or ''}",
        f"attendees: [{', '.join(speakers)}]" if speakers else "attendees: []",
        f"utterance_count: {len(utterances)}",
        "---",
        "",
        f"# 会議トランスクリプト: {source_path.stem}",
        "",
        "## 発話記録",
        "",
    ]
    for u in utterances:
        ts = f"[{u.start}]" if u.start else ""
        lines.append(f"**{ts} {u.speaker}:** {u.text}".strip())
        lines.append("")

    if unparsed:
        lines.append("## 未パース区間（要確認）")
        lines.append("")
        lines.append("以下は話者/時刻の構造を検出できなかった段落。docxのレイアウトが")
        lines.append("想定と異なる可能性があるため、SKILL.md/transcript.pyの見直しに使う。")
        lines.append("")
        for p in unparsed:
            lines.append(f"- {p}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        content = path.read_text(encoding="utf-8")
        utterances = parse_vtt(content)
        unparsed: list[str] = []
        source_format = "vtt"
    elif suffix == ".docx":
        utterances, unparsed = parse_docx(path)
        source_format = "docx"
    else:
        raise ValueError(f"未対応の拡張子です: {suffix}（.vtt または .docx）")
    return render_markdown(path, source_format, utterances, unparsed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="VTT または docx ファイル")
    parser.add_argument("-o", "--output", type=Path, default=None, help="出力先md（省略時は入力と同じディレクトリ・同名.md）")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 1

    try:
        markdown = extract(args.input)
    except (ValueError, RuntimeError) as e:
        print(f"抽出に失敗しました: {e}", file=sys.stderr)
        return 1

    output_path = args.output or args.input.with_suffix(".md")
    output_path.write_text(markdown, encoding="utf-8")
    print(f"書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
