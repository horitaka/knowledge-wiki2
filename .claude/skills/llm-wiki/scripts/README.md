# scripts/

決定論的な前処理・lint・publishスクリプトを置く場所（docs/llm-wiki.md §11、SKILL.mdの実装状況）。

## 実装済み（フェーズ2）

- `ingest_prep/transcript.py` — VTT / Word（.docx、MSトランスクリプト）/ プレーンテキスト（.txt）・Markdown（.md、自由記述の議事録メモ）→ 正規化md。txt/mdは構造抽出をせずfrontmatter付与＋本文パススルーのみ。合成データで検証済み、**実サンプル未検証**（特に.docxのレイアウト仮定は docs/llm-wiki.md §10 の未確定事項）
- `ingest_prep/pptx_extract.py` — 進捗デッキ → 正規化md（タイトル・本文・表・スピーカーノート。画像は件数のみ記録）。合成データで検証済み
- `ingest_prep/teams_extract.py` — Teams CSV（`parent_message_id` でスレッド復元、systemメッセージ除外）/ 自由記述のチャットログ（txt/md、構造抽出なしのパススルー）→ 正規化md。合成データで検証済み、依存なし
- `lint.py` — `wiki/` 配下の機械チェック（frontmatter欠落・必須フィールド不足、orphanページ、重複ページ疑い、リンク切れ）。標準ライブラリのみ、依存なし
- `publish/publish.py` — Confluence publishの決定論的な部分（`configure`: space・親ページID（1リポジトリ=1スペース=1親ページ配下）を`publish_config.json`へ保存、`plan`: フォルダ/create/update/skip/blockedの判定とdry-run表示、`record`: MCP呼び出し結果のsync_state.json（フォルダ・ページ共通） + コンテンツページfrontmatterへの書き戻し）。**MCPツール自体はPythonから呼べない**ため、実際の`createConfluencePage`/`updateConfluencePage`呼び出しはagentが行う（[../references/publish.md](../references/publish.md)）

`.docx` / `.pptx` を扱うスクリプトは `pip install -r scripts/requirements.txt` が必要（python-docx, python-pptx）。`teams_extract.py` / `lint.py` / `publish/publish.py` は標準ライブラリのみ。

使い方:
- 抽出: `python3 scripts/ingest_prep/<script>.py <input> [-o <output>]`（出力省略時は入力と同じディレクトリ・同名 `.md`）
- lint: `python3 scripts/lint.py [--wiki-dir wiki] [--fix]`（`--fix` は完全欠落キー`type`/`tags`/`status`/`confluence_id`の既定値補完のみ。本文・既存値は書き換えない）。stale判定・矛盾検出はLLM判断のため対象外（[../references/lint.md](../references/lint.md)）
- publish: 初回のみ `python3 scripts/publish/publish.py configure --space <SPACEKEY> --root-page-id <親ページID>` → `python3 scripts/publish/publish.py plan` でdry-run → 承認 → agentがMCP発火（フォルダページ→配下ページの順） → `python3 scripts/publish/publish.py record --page <path> --confluence-id <id>`（フォルダページの場合は `--folder <dirname>`）で記録（[../references/publish.md](../references/publish.md)）

## 未実装

- `search.py` — ローカル索引 / 検索

未実装の間は手動 / LLM単体で行う。手順は `.claude/skills/llm-wiki/references/query.md` を参照。

`publish/publish_config.json` は `publish.py configure` が書き込む（space・親ページIDをリポジトリに1つだけ記録する場所）。`publish/sync_state.json` は `publish.py record` が書き込む（local page/folder ↔ confluence page-id ＋ content-hashを記録する場所）。
