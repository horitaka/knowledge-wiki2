# ingest ワークフロー

新しい一次ソース（会議議事録・進捗デッキ・Teamsチャット）を `raw/` に取り込み、wikiへ反映する手順。

**方針（二段構え）:** パースや整形は決定論的スクリプトに寄せてトークンを消費しない。LLMは「判断」（要約・相互参照・矛盾検出・名寄せ）だけに使う。

## 手順

1. **配置**: 元ファイルを `raw/{transcripts,decks,teams}/` の適切なサブディレクトリに置く
2. **抽出（決定論的・スクリプト）**: 対応するスクリプトで正規化mdへ変換する。出力は入力と同じディレクトリに同名の `.md` として書き出す（例: `raw/transcripts/2026-07-10_定例.vtt` → `raw/transcripts/2026-07-10_定例.md`）
   - VTT/Word議事録 → `python3 scripts/ingest_prep/transcript.py <input> [-o <output>]`（`.docx` は `pip install -r scripts/requirements.txt` が必要）。開くパスワードで暗号化されたdocxの復号は未対応（IRM保護の検出は対応、下記参照）
   - 自由記述の議事録（txt/md） → 同じ `python3 scripts/ingest_prep/transcript.py <input> [-o <output>]` で処理する（追加の依存なし）。人手で書かれたメモを想定しており、VTT/docxのような話者/タイムスタンプの構造抽出は行わず、frontmatterを付与して本文をそのままラップするだけ（出席者・決定事項の判断はHOTL②に委ねる）。**入力が `.md` の場合、省略時の出力先（同名`.md`）が入力自身と衝突し `raw/` の不変性を壊すため、必ず `-o` で別名の出力先を指定する**（未指定だとスクリプトがエラーで停止する）
   - pptx進捗デッキ → `python3 scripts/ingest_prep/pptx_extract.py <input> [-o <output>]`（要 `scripts/requirements.txt`）
     - 開くパスワードで暗号化されたpptxは `--password` / `--password-file` / 環境変数 `PPTX_PASSWORD`（`--password-env`で変更可）のいずれかでパスワードを渡す。未指定かつ対話端末で実行時はプロンプトで入力を求める。シェル履歴を残さないため `--password-file` か環境変数を優先する。「編集の制限」等パスワード無しで開ける保護は対応不要（通常どおり抽出される）
   - PDF進捗デッキ → `python3 scripts/ingest_prep/pdf_extract.py <input> [-o <output>] [--source-type deck]`（要 `scripts/requirements.txt`。ページ単位でテキストを抽出、本文/表の区別はしない）
     - **Microsoft情報保護ラベル（IRM/Azure RMS）で保護されたファイル（pptx/docx共通）はパスワードでは復号できない**（コンテンツキーがAzure ADの利用者IDに紐づくライセンスサーバからしか取得できないため）。スクリプトはこれを検出して明確なエラーを返す（`--password`を渡しても解決しない）。対処は次のいずれか: (1) **人手のみ**でラベル解除権限を持つ人がOffice上でファイルを開き、ラベル/保護を解除した複製を作成して `raw/` に配置し直してから再実行する。(2) ラベルのポリシーで印刷/エクスポートが許可されている場合は、閲覧権限を持つ人がOffice上でファイルをPDFとして保存し、そのPDFを `raw/decks/`（議事録の場合は `raw/transcripts/`）に配置し直した上で `pdf_extract.py <input> [--source-type deck|transcript]` で再実行するようユーザーに促す。いずれもLLMが暗号化バイト列を直接読んで代替する手段はない（手順2の「スクリプトが失敗した場合はLLMが手動で…」は適用不可）
   - Teams CSV → `python3 scripts/ingest_prep/teams_extract.py <input> [-o <output>]`（標準ライブラリのみ、依存なし）
   - 自由記述のチャットログ（txt/md） → 同じ `python3 scripts/ingest_prep/teams_extract.py <input> [-o <output>]` で処理する（追加の依存なし）。人手でコピー&ペースト・転記されたログを想定しており、CSVのような`message_id`/`parent_message_id`によるスレッド復元・発言者ごとの構造抽出は行わず、frontmatterを付与して本文をそのままラップするだけ（決定・未解決の論点・非公式な知見の抽出はHOTL②に委ねる）。**入力が `.md` の場合、省略時の出力先（同名`.md`）が入力自身と衝突し `raw/` の不変性を壊すため、必ず `-o` で別名の出力先を指定する**（未指定だとスクリプトがエラーで停止する）
   - 4スクリプトとも合成データでの検証は済んでいるが、**実サンプルでは未検証**。特にWord(.docx)議事録は話者名/タイムスタンプのレイアウトを正規表現で推測しており、想定と異なる場合は本文が丸ごと「未パース区間」に落ちる（サイレントに消えることはない）。実サンプル投入時にレイアウトのズレがないか必ず確認する
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
