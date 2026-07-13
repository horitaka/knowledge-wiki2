# scripts/

決定論的な前処理・lint・publishスクリプトを置く場所（docs/llm-wiki.md §11、SKILL.mdの実装状況）。

## 実装済み（フェーズ2）

- `ingest_prep/transcript.py` — VTT / Word（.docx、MSトランスクリプト）→ 正規化md。合成データで検証済み、**実サンプル未検証**（特に.docxのレイアウト仮定は docs/llm-wiki.md §10 の未確定事項）
- `ingest_prep/pptx_extract.py` — 進捗デッキ → 正規化md（タイトル・本文・表・スピーカーノート。画像は件数のみ記録）。合成データで検証済み
- `ingest_prep/teams_extract.py` — Teams CSV → スレッド復元済みmd（`parent_message_id` で再構成、systemメッセージ除外）。合成データで検証済み、依存なし

`.docx` / `.pptx` を扱うスクリプトは `pip install -r scripts/requirements.txt` が必要（python-docx, python-pptx）。`teams_extract.py` は標準ライブラリのみ。

使い方: `python3 scripts/ingest_prep/<script>.py <input> [-o <output>]`（出力省略時は入力と同じディレクトリ・同名 `.md`）

## 未実装

- `search.py` — ローカル索引 / 検索
- `lint.py` — orphan・frontmatter欠落・stale等の機械チェック
- `publish/publish.py` — 差分ページのみ Atlassian MCP 経由で create/update

未実装の間は各操作を手動 / LLM単体で行う。手順は `.claude/skills/llm-wiki/references/` の各ファイルの「未実装時の代替手順」を参照。

`publish/sync_state.json` は空の `{}` で用意済み（local page ↔ confluence page-id ＋ content-hashを記録する場所。publish.py実装後に使う）。
