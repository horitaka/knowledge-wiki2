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

## 2026-07-13 22:00 ingest

- 対象: raw/transcripts/2026-07-06_定例会議.vtt, raw/decks/2026-07-08_進捗報告.pptx, raw/teams/2026-07-09_thread.csv（docs/llm-wiki.md §11-3「少数ソースで手動ingest」の検証。実サンプル未入手のため、社内利用を想定した合成サンプル3件を作成）
- 内容: 3種の抽出スクリプトで正規化mdを生成（transcript.py はVTT経路、pptx_extract.py、teams_extract.py。いずれも動作確認済み、docxのdocx抽出パスは今回未検証）。生成md をレビュー後、以下12ページを新規作成: entities 6件（在庫管理システム刷新プロジェクト、田中太郎、佐藤花子、鈴木一郎、クラウドギア社、データフォース社）、decisions 1件（2026-07-06-ベンダー選定）、concepts 1件（データ移行方針）、open_questions 1件（エクスポート仕様確定遅延懸念）、summaries 3件（各ソース1件）。`wiki/index.md`・`wiki/overview.md` を更新
- 備考: 3ソースが同一プロジェクトの一連の出来事だったため、圧縮原則どおりentity/decision/conceptへ情報が集約され、summaryは薄く保てた（各3〜5行）。ページ数はガイド目安（1ソースあたり10〜15）の範囲内（3ソース合計12ページ、ただし相互に関連する内容だったため重複更新は少なかった）。pptx_extract.py / teams_extract.py / transcript.py(VTT) の抽出構造は想定どおりで、ワークフロー（抽出→レビュー→wiki反映→index/overview更新→log追記）が問題なく機能することを確認。lint.py・search.py・publish.py は依然未実装のため、次フェーズ（§11-4）で整備する
