# ingest ワークフロー

新しい一次ソース（会議議事録・進捗デッキ・Teamsチャット）を `raw/` に取り込み、wikiへ反映する手順。

**方針（二段構え）:** パースや整形は決定論的スクリプトに寄せてトークンを消費しない。LLMは「判断」（要約・相互参照・矛盾検出・名寄せ）だけに使う。

## 手順

1. **配置**: 元ファイルを `raw/{transcripts,decks,teams}/` の適切なサブディレクトリに置く
2. **抽出（決定論的・スクリプト）**: 対応するスクリプトで正規化mdへ変換する。出力は入力と同じディレクトリに同名の `.md` として書き出す（例: `raw/transcripts/2026-07-10_定例.vtt` → `raw/transcripts/2026-07-10_定例.md`）
   - VTT/Word議事録 → `python3 scripts/ingest_prep/transcript.py <input> [-o <output>]`（`.docx` は `pip install -r scripts/requirements.txt` が必要）
   - pptx進捗デッキ → `python3 scripts/ingest_prep/pptx_extract.py <input> [-o <output>]`（要 `scripts/requirements.txt`）
   - Teams CSV → `python3 scripts/ingest_prep/teams_extract.py <input> [-o <output>]`（標準ライブラリのみ、依存なし）
   - 3スクリプトとも合成データでの検証は済んでいるが、**実サンプルでは未検証**。特にWord(.docx)議事録は話者名/タイムスタンプのレイアウトを正規表現で推測しており、想定と異なる場合は本文が丸ごと「未パース区間」に落ちる（サイレントに消えることはない）。実サンプル投入時にレイアウトのズレがないか必ず確認する
   - スクリプトが失敗する、または対象の入力形式に対応していない場合は、LLMが直接raw内容を読み、正規化md相当の構造（日付・出席者・話者別発話 or スレッド復元）を手動で作ってから次のステップへ進む
3. **人によるレビュー（HOTL①）**: 正規化mdの内容が元ソースを正しく反映しているか、機微情報が含まれていないかを人が確認する
4. **要点確認（HOTL②）**: LLMが正規化mdを読み、抽出した要点（決定・アクションアイテム・言及されたentity等）を対話で人に確認する
5. **wiki反映**:
   - `wiki/summaries/` に来歴ページを1件作成する（[page-types.md](page-types.md)の粒度を守り、薄く保つ）
   - 言及された entity を [naming-conventions.md](naming-conventions.md) の名寄せ手順に沿って新規作成 or 追記する
   - 決定が含まれていれば `wiki/decisions/` に新規decisionページを作成する（既存決定のsupersedeであれば `superseded_by`/`supersedes` を相互に記入する）
   - 横断的なテーマへの言及があれば `wiki/concepts/` を更新する
   - `wiki/index.md` に新規/更新ページへのリンクと一行説明を反映する
6. **監査記録**: `wiki/log.md` に「日時・対象ソース・触れたページ一覧・要約」を追記する
7. **コミット**: `git commit` する（publishの起点になるチェックポイント）

## 新規 vs 追記の判定

**他から参照される独立した実体/概念なら新規、既存ページの属性・更新にすぎないなら追記。**

- 新規: 初めて言及される人物、初めて出てくる決定、新しいプロジェクトフェーズの概念
- 追記: 既存entityの役割変更、既存decisionへの補足、既存conceptの進捗更新

判断に迷う場合は既存ページへの追記を優先する（ページの増殖よりも統合を優先する）。

## 1ソースあたりの目安

1ソースのingestで触れるページは10〜15ページ程度が目安。大幅に超える場合はソースの粒度が粗すぎる（複数の話題を含む）可能性があるため、summaryを分割することを検討する。

## Teamsチャットの特性

逐語要約ではなく**決定・未解決の論点・非公式な知見**の抽出に振り切る。`parent_message_id` によるスレッド復元を先に行い、スレッド単位でまとめてから判断する。カラム定義は docs/llm-wiki.md §7.3 を参照。
