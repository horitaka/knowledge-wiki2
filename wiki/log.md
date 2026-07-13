# Log

ingest / lint / publish の監査ログ。新しいエントリを末尾に追記する（降順ソートはしない。git blameで十分追跡できるため）。

## 記録フォーマット

```
## YYYY-MM-DD HH:MM 操作種別（ingest|lint|publish）
- 対象: raw/... または対象ページ一覧
- 内容: 何を行ったか（触れたページ、作成/更新/status変更の別）
- 備考: 判断に迷った点、次に確認すべきこと
```

---

## 2026-07-13 骨格構築

- 対象: リポジトリ全体
- 内容: `.claude/skills/llm-wiki/` (SKILL.md + references 6件)、`raw/`・`wiki/` ディレクトリ構成、frontmatterスキーマ、`wiki/index.md`・`wiki/log.md`・`wiki/overview.md` の雛形、`AGENTS.md` を作成。docs/llm-wiki.md §11のフェーズ1に相当
- 備考: 抽出スクリプト3種・search.py・lint.py・publish.pyは未実装（フェーズ2以降）。実サンプル未取得のため.docx構造は未検証（docs/llm-wiki.md §10）
