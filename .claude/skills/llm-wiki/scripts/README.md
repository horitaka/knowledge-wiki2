# scripts/（未実装 — フェーズ2）

決定論的な前処理・lint・publishスクリプトを置く場所。ディレクトリ構成は決めてあるが中身は未実装（docs/llm-wiki.md §11、SKILL.mdの実装状況）。

- `ingest_prep/transcript.py` — VTT / Word（MSトランスクリプト）→ 正規化md
- `ingest_prep/pptx_extract.py` — 進捗デッキ → 正規化md
- `ingest_prep/teams_extract.py` — Teams CSV → スレッド復元済みmd
- `search.py` — ローカル索引 / 検索
- `lint.py` — orphan・frontmatter欠落・stale等の機械チェック
- `publish/publish.py` — 差分ページのみ Atlassian MCP 経由で create/update
- `publish/sync_state.json` — local page ↔ confluence page-id ＋ content-hash

未実装の間は各操作を手動 / LLM単体で行う。手順は `.claude/skills/llm-wiki/references/` の各ファイルの「未実装時の代替手順」を参照。
