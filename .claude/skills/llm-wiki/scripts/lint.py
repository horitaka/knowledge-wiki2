#!/usr/bin/env python3
"""wiki/ 配下の機械チェック（lint）。

references/lint.md の「機械チェック」4種を実施する。
- frontmatter欠落・必須フィールド不足（type/status の値が不正な場合を含む）
- orphanページ（どこからもリンクされていない、index.mdにも載っていない）
- 重複ページ（同一entityが名寄せされずに複数ファイルに分裂している疑い）
- リンク切れ（相互リンク先・sourcesの参照先ファイルが存在しない）

stale判定・矛盾検出はLLM判断の仕事であり、このスクリプトは行わない。

既定ではread-only。`--fix` を指定した場合のみ、frontmatterに完全に欠落している
安全なキー（type/tags/status/confluence_id/confluence_space）を補完する。
本文、および既存のフィールド値は一切書き換えない（ハードルール、references/lint.md）。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
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
VALID_STATUS = {"draft", "active", "stale", "superseded"}
REQUIRED_FIELDS = ["type", "title", "description", "timestamp", "status"]
SAFE_FIX_DEFAULTS = {"tags": [], "status": "draft", "confluence_id": None, "confluence_space": None}

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)[^)]*\)")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    category: str
    file: Path
    message: str


@dataclass
class Page:
    path: Path
    expected_type: str | None
    fields: dict
    fm_lines: list[str] | None
    body: str
    raw_text: str


def expected_type_for(path: Path, wiki_dir: Path) -> str | None:
    rel = path.relative_to(wiki_dir)
    if len(rel.parts) == 2:
        return DIR_TYPE_MAP.get(rel.parts[0])
    if rel.name == "overview.md":
        return "overview"
    return None  # index.md / log.md はフリーフォーマットのため対象外


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


def load_page(path: Path, wiki_dir: Path) -> Page:
    raw_text = path.read_text(encoding="utf-8")
    fm_lines, body = split_frontmatter(raw_text)
    fields = parse_frontmatter_fields(fm_lines) if fm_lines is not None else {}
    return Page(
        path=path,
        expected_type=expected_type_for(path, wiki_dir),
        fields=fields,
        fm_lines=fm_lines,
        body=body,
        raw_text=raw_text,
    )


def check_frontmatter(page: Page) -> list[Issue]:
    issues: list[Issue] = []
    if page.expected_type is None:
        return issues  # index.md / log.md はfrontmatter必須の対象外

    if page.fm_lines is None:
        issues.append(Issue("error", "frontmatter", page.path, "frontmatterブロックが存在しない"))
        return issues

    for key in REQUIRED_FIELDS:
        if not page.fields.get(key):
            issues.append(Issue("error", "frontmatter", page.path, f"必須フィールド `{key}` が欠落/空"))

    sources = page.fields.get("sources")
    if not sources:
        issues.append(Issue("error", "frontmatter", page.path, "必須フィールド `sources` が欠落/空"))

    type_value = page.fields.get("type")
    if type_value and type_value not in VALID_TYPES:
        issues.append(Issue("error", "frontmatter", page.path, f"`type: {type_value}` は不正な値"))
    elif type_value and type_value != page.expected_type:
        issues.append(
            Issue(
                "error",
                "frontmatter",
                page.path,
                f"`type: {type_value}` がディレクトリ由来の期待値 `{page.expected_type}` と不一致",
            )
        )

    status_value = page.fields.get("status")
    if status_value and status_value not in VALID_STATUS:
        issues.append(Issue("error", "frontmatter", page.path, f"`status: {status_value}` は不正な値"))

    return issues


def extract_link_targets(text: str) -> list[str]:
    targets = [m.group(1) for m in MD_LINK_RE.finditer(text)]
    targets += [m.group(1) for m in WIKILINK_RE.finditer(text)]
    resolved = []
    for t in targets:
        t = t.strip()
        if not t or t.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved.append(t.split("#", 1)[0])
    return resolved


def check_broken_links(page: Page, repo_root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for target in extract_link_targets(page.raw_text):
        resolved = (page.path.parent / target).resolve()
        if not resolved.exists():
            issues.append(Issue("error", "broken_link", page.path, f"リンク切れ: `{target}` -> {resolved}"))
    sources = page.fields.get("sources")
    if isinstance(sources, list):
        for src in sources:
            resolved = (repo_root / src).resolve()
            if not resolved.exists():
                issues.append(Issue("warning", "broken_link", page.path, f"sourcesの参照先が存在しない: `{src}`"))
    return issues


def check_orphans(pages: list[Page], wiki_dir: Path) -> list[Issue]:
    linked: set[Path] = set()
    for page in pages:
        for target in extract_link_targets(page.raw_text):
            resolved = (page.path.parent / target).resolve()
            linked.add(resolved)

    issues: list[Issue] = []
    for page in pages:
        if page.expected_type not in DIR_TYPE_MAP.values():
            continue  # index/log/overview は入口ページなのでorphan判定対象外
        if page.path.resolve() not in linked:
            issues.append(
                Issue("warning", "orphan", page.path, "どこからもリンクされておらず、index.mdにも未掲載")
            )
    return issues


def normalize_title(title: str) -> str:
    t = title.strip()
    for suffix in ("さん", "氏", "様"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t.strip().casefold()


def check_duplicates(pages: list[Page], wiki_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    by_type: dict[str, list[Page]] = {}
    for page in pages:
        if page.expected_type not in DIR_TYPE_MAP.values():
            continue
        title = page.fields.get("title")
        if not title:
            continue
        by_type.setdefault(page.expected_type, []).append(page)

    for _type, group in by_type.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                na, nb = normalize_title(a.fields["title"]), normalize_title(b.fields["title"])
                if not na or not nb:
                    continue
                if na == nb:
                    issues.append(
                        Issue(
                            "error",
                            "duplicate",
                            a.path,
                            f"タイトルが `{b.path.relative_to(wiki_dir)}` と重複（名寄せ漏れの疑い）",
                        )
                    )
                elif len(na) >= 2 and len(nb) >= 2 and (na in nb or nb in na):
                    issues.append(
                        Issue(
                            "warning",
                            "duplicate_suspect",
                            a.path,
                            f"タイトルが `{b.path.relative_to(wiki_dir)}` と類似（同一entityの分裂疑い、要確認）",
                        )
                    )
    return issues


def apply_safe_fix(page: Page) -> list[str]:
    """frontmatterに完全に欠落しているキーのみ安全な既定値で補完する。既存の値・本文は触らない。"""
    if page.fm_lines is None or page.expected_type is None:
        return []

    fixed: list[str] = []
    new_lines = list(page.fm_lines)

    if "type" not in page.fields:
        new_lines.append(f"type: {page.expected_type}")
        fixed.append(f"type: {page.expected_type}")

    for key, default in SAFE_FIX_DEFAULTS.items():
        if key in page.fields:
            continue
        if isinstance(default, list):
            rendered = f"{key}: []" if not default else f"{key}: [{', '.join(default)}]"
        else:
            rendered = f"{key}: {default or ''}".rstrip()
        new_lines.append(rendered)
        fixed.append(rendered)

    if fixed:
        new_text = "\n".join([FRONTMATTER_DELIM, *new_lines, FRONTMATTER_DELIM]) + "\n" + page.body
        page.path.write_text(new_text, encoding="utf-8")

    return fixed


def collect_pages(wiki_dir: Path) -> list[Page]:
    return [load_page(p, wiki_dir) for p in sorted(wiki_dir.rglob("*.md"))]


def run_lint(wiki_dir: Path, repo_root: Path, fix: bool) -> tuple[list[Issue], dict[Path, list[str]]]:
    pages = collect_pages(wiki_dir)
    issues: list[Issue] = []
    fixes: dict[Path, list[str]] = {}

    for page in pages:
        issues.extend(check_frontmatter(page))
        issues.extend(check_broken_links(page, repo_root))

    issues.extend(check_orphans(pages, wiki_dir))
    issues.extend(check_duplicates(pages, wiki_dir))

    if fix:
        for page in pages:
            applied = apply_safe_fix(page)
            if applied:
                fixes[page.path] = applied

    return issues, fixes


def format_report(issues: list[Issue], fixes: dict[Path, list[str]], wiki_dir: Path) -> str:
    lines: list[str] = []
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    lines.append(f"lint結果: error {len(errors)}件 / warning {len(warnings)}件")
    for issue in issues:
        rel = issue.file.relative_to(wiki_dir.parent) if wiki_dir.parent in issue.file.parents else issue.file
        lines.append(f"[{issue.severity}] [{issue.category}] {rel}: {issue.message}")

    if fixes:
        lines.append("")
        lines.append("--fix で補完したフィールド:")
        for path, applied in fixes.items():
            rel = path.relative_to(wiki_dir.parent) if wiki_dir.parent in path.parents else path
            lines.append(f"  {rel}: {', '.join(applied)}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-dir", type=Path, default=Path("wiki"), help="lint対象のwikiディレクトリ（既定: wiki/）")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="frontmatterに完全欠落しているキー（type/tags/status/confluence_id/confluence_space）のみ既定値で補完する",
    )
    args = parser.parse_args()

    wiki_dir = args.wiki_dir.resolve()
    if not wiki_dir.is_dir():
        print(f"wikiディレクトリが見つかりません: {wiki_dir}", file=sys.stderr)
        return 1
    repo_root = wiki_dir.parent

    issues, fixes = run_lint(wiki_dir, repo_root, args.fix)
    print(format_report(issues, fixes, wiki_dir))

    return 1 if any(i.severity == "error" for i in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
