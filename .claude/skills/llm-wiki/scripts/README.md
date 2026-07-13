# scripts/

決定論的な前処理・lint・publishスクリプトを置く場所（docs/llm-wiki.md §11、SKILL.mdの実装状況）。

## 実装済み（フェーズ2）

- `ingest_prep/transcript.py` — VTT / Word（.docx、MSトランスクリプト）→ 正規化md。合成データで検証済み、**実サンプル未検証**（特に.docxのレイアウト仮定は docs/llm-wiki.md §10 の未確定事項）
- `ingest_prep/pptx_extract.py` — 進捗デッキ → 正規化md（タイトル・本文・表・スピーカーノート。画像は件数のみ記録）。合成データで検証済み
- `ingest_prep/teams_extract.py` — Teams CSV → スレッド復元済みmd（`parent_message_id` で再構成、systemメッセージ除外）。合成データで検証済み、依存なし
- `lint.py` — `wiki/` 配下の機械チェック（frontmatter欠落・必須フィールド不足、orphanページ、重複ページ疑い、リンク切れ）。標準ライブラリのみ、依存なし
- `publish/publish.py` — Confluence publishの決定論的な部分（`plan`: create/update/skip/blockedの判定とdry-run表示、`record`: MCP呼び出し結果のsync_state.json + frontmatterへの書き戻し）。**MCPツール自体はPythonから呼べない**ため、実際の`createConfluencePage`/`updateConfluencePage`呼び出しはagentが行う（[../references/publish.md](../references/publish.md)）

`.docx` / `.pptx` を扱うスクリプトは `pip install -r scripts/requirements.txt` が必要（python-docx, python-pptx）。`teams_extract.py` / `lint.py` / `publish/publish.py` は標準ライブラリのみ。

使い方:
- 抽出: `python3 scripts/ingest_prep/<script>.py <input> [-o <output>]`（出力省略時は入力と同じディレクトリ・同名 `.md`）
- lint: `python3 scripts/lint.py [--wiki-dir wiki] [--fix]`（`--fix` は完全欠落キー`type`/`tags`/`status`/`confluence_id`/`confluence_space`の既定値補完のみ。本文・既存値は書き換えない）。stale判定・矛盾検出はLLM判断のため対象外（[../references/lint.md](../references/lint.md)）
- publish: `python3 scripts/publish/publish.py plan --default-space <space>` でdry-run → 承認 → agentがMCP発火 → `python3 scripts/publish/publish.py record --page <path> --confluence-id <id> --confluence-space <space>` で記録（[../references/publish.md](../references/publish.md)）

## 未実装

- `search.py` — ローカル索引 / 検索

未実装の間は手動 / LLM単体で行う。手順は `.claude/skills/llm-wiki/references/query.md` を参照。

`publish/sync_state.json` は `publish.py record` が書き込む（local page ↔ confluence page-id ＋ content-hashを記録する場所）。
