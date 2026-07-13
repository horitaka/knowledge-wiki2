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

## 2026-07-13 抽出スクリプト3種の実装

- 対象: `.claude/skills/llm-wiki/scripts/ingest_prep/`
- 内容: `transcript.py`（VTT確定実装 + Word(.docx)は話者/時刻をヒューリスティックに検出するbest-effort実装、未パース段落は落とさず出力に残す）、`pptx_extract.py`（タイトル・本文・表・スピーカーノート抽出、画像は件数のみ記録）、`teams_extract.py`（`parent_message_id`によるスレッド復元、systemメッセージ除外、複数行本文・孤立返信に対応）を実装。scratchpadで合成データ（VTT/docx/pptx/CSV）を作成し、いずれも動作確認済み。`scripts/requirements.txt`（python-docx, python-pptx）を追加
- 備考: **実サンプルでの検証はまだ**。特に.docxの話者/時刻レイアウトは推測に基づく仮実装のため、実際のMS Teamsトランスクリプトを投入した際にレイアウトのズレがないか要確認（docs/llm-wiki.md §10）。`search.py`・`lint.py`・`publish/publish.py`は未実装のまま
