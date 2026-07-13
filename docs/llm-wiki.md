# LLM Wiki 構築 — 設計まとめ

- 作成日: 2026-07-12
- 対象: 組織内ナレッジのLLM Wiki(Claude Code agent skill → Confluence Cloud)
- ステータス: 設計確定（実装未着手）。未確定は §10 に集約
- 出典パターン: Andrej Karpathy「llm-wiki」

---

## 1. 目的と背景

Karpathyの「llm-wiki」パターンを組織内ナレッジに適用する。RAGのように毎回生ソースから知識を再発見するのではなく、**LLMが構造化・相互リンクされたmarkdown群(wiki)を継続的に構築・保守する累積型の成果物(compounding artifact)**を作る。人はソースのキュレーションと問いかけに集中し、要約・相互参照・整合維持といった保守作業はLLMが担う。

- 実装形態: Claude Codeの **agent skill**
- 入力ソース: ①会議の議事録/トランスクリプト、②進捗報告デッキ(ppt)、③Teamsチャット履歴
- 公開先: **Confluence Cloud**（Atlassian MCP経由）
- 実行環境: ローカルPCのClaude Code。ローカルでmdを作成し、Confluenceへ反映

---

## 2. 中核となる設計判断

> **ローカルのmarkdownを唯一の正(source of truth)とし、Confluenceは「そこから生成される公開ミラー(publish target)」に徹する。**

理由:
1. Claude CodeはConfluence APIを往復せず、ローカルファイルだけで読み書き・相互参照・lintできる（高速・低トークン・失敗点が少ない）
2. git履歴がそのまま版管理と `log.md` の監査証跡になる
3. 「ローカルでmd作成 → Confluenceに反映」という要件そのもの

**Confluence上での直接編集は行わない（確定）。** これにより双方向の突き合わせが不要になり、設計が単純化する。人の知見はConfluenceではなく一次ソース（raw/）経由で取り込む。

---

## 3. 確定した要件（決定事項一覧）

| 項目                 | 決定                                              | 補足                                                     |
| -------------------- | ------------------------------------------------- | -------------------------------------------------------- |
| Confluence種別       | Cloud                                             | REST v2 / ADF系。ローカルからの書き込みは許可済み        |
| 公開経路             | Atlassian MCP（公式Rovo MCP）                     | `createConfluencePage` / `updateConfluencePage` 等を使用 |
| 正のありか           | ローカルmd = 正                                   | Confluenceは下流ミラー。**直接編集なし**                 |
| リポジトリ単位       | 1リポジトリ = 1プロジェクト                       | entityの粒度もプロジェクト内                             |
| 運用                 | 初期は単独運用で確立 → パターン確定後にチーム展開 | チーム化時にPRゲート/排他を差し込む                      |
| ページ型             | 4型 + 未解決論点キュー                            | §5 参照                                                  |
| 言語                 | 日本語前提                                        | 検索の日本語アナライザは規模拡大時に検討                 |
| 公開契機             | 手動 + HOTLゲート                                 | dry-run差分 → 承認 → MCP発火                             |
| 検索                 | まず `index.md` 前提 → 規模が見えたら判断         | 数百ページ超でハイブリッド検索を検討                     |
| 画像のConfluence反映 | **テキストのみ公開**                              | 図・スクショはraw/に保持、公開はテキスト合成のみ         |
| PII（公開側）        | 追加処理なし                                      | raw/へのローカル保存は許容済み                           |
| Teams入力            | **CSV**                                           | カラム定義は §7.3                                        |

---

## 4. アーキテクチャ

### 4.1 3層構造

- **raw/** … 不変の一次ソース。LLMは読むだけで改変しない。組織の source of truth
- **wiki/** … LLMが維持するmarkdown群。**公開wikiの正**。要約・entity・concept・decision・overview
- **schema (SKILL.md)** … wikiの構造・規約・ワークフローを規定する最重要ファイル。ドメインと共に育てる

### 4.2 ディレクトリ構成

```
knowledge-wiki/                    # git リポジトリ = 1プロジェクトのwiki
├─ .claude/skills/llm-wiki/
│  ├─ SKILL.md                     # ★スキーマ + ワークフロー（最重要）
│  ├─ references/                  # ページ型定義・命名規約・ingest/query/lint/publish詳細
│  └─ scripts/
│     ├─ ingest_prep/              # ★決定論的な入力抽出
│     │  ├─ transcript.py          # VTT / Word（MSトランスクリプト）→ 正規化md
│     │  ├─ pptx_extract.py        # 進捗デッキ → 正規化md（pptxスキル流用）
│     │  └─ teams_extract.py       # Teams CSV → スレッド復元済みmd
│     ├─ search.py                 # ローカル索引 / 検索（初期はindex.md参照）
│     ├─ lint.py                   # orphan・frontmatter欠落・stale等の機械チェック
│     └─ publish/
│        ├─ publish.py             # 差分ページのみ Atlassian MCP 経由で create/update
│        └─ sync_state.json        # local page ↔ confluence page-id ＋ content-hash
├─ raw/                            # ★不変の一次ソース
│  ├─ transcripts/   decks/   teams/   assets/
├─ wiki/                           # ★LLMが維持するmarkdown（公開の正）
│  ├─ index.md   log.md   overview.md
│  ├─ entities/                    # プロジェクト・人/役割・チーム・システム・ベンダー
│  ├─ concepts/                    # 横断テーマ
│  ├─ decisions/                   # 決定 + 根拠 + 撤回条件 + supersede関係
│  ├─ open_questions/              # 未解決論点キュー（lintの矛盾検出をここへ）
│  └─ summaries/                   # 一次ソース1件 = 1ページ（軽量な来歴）
└─ AGENTS.md                       # 他ツール併用時の入口（任意）
```

将来 `ai-dev-toolkit` から複数wikiへ配布する場合は、`scripts/` を汎用エンジンとしてツールキット側へ切り出し、SKILL.md を「汎用ワークフロー + wiki固有の規約」に分割する。当面は同居で開始。

---

## 5. ページ型タクソノミ

| 型                 | 役割                                                     | 備考                                               |
| ------------------ | -------------------------------------------------------- | -------------------------------------------------- |
| **entity**         | プロジェクト/人/システム/ベンダー                        | **多数ソースを跨いで圧縮が起きる中核**。最大の価値 |
| **decision**       | 決定・根拠・決定者・日付・**撤回/再検討条件**・supersede | チーム用途のキラー機能（決定の記憶）               |
| **concept**        | 横断テーマ                                               | 例: 移行方針、コストガバナンス                     |
| **summary**        | 一次ソース1件 = 1ページ                                  | **軽量に保つ**（来歴 + 要点リンクのみ）            |
| **open_questions** | 未解決論点・矛盾のキュー                                 | lintの矛盾検出結果を流し込む                       |

**圧縮原則（最重要）:** 複数ソースを跨いで**圧縮するページ**だけが価値を持つ。1ソースを写しただけのページは負の価値。押し出す主役はentity/decision/conceptで、summaryは来歴として薄く持つ。会議議事録を機械的に1本ずつ公開してConfluenceをノイズで埋めない。

**日本語の名寄せ:** 人名・プロジェクト名の表記ゆれ（例:「田中さん」/「田中」/フルネーム）はingest時にentity名を正規化する方針をSKILL.mdに明記する。

---

## 6. frontmatter スキーマ

```yaml
type: entity            # entity | concept | decision | summary | overview | open_question
title:
description:            # 一行。index.md に反映
tags: []
timestamp:              # 最終更新
sources: []             # 来歴。どのraw sourceが寄与したか
status: active          # draft | active | stale | superseded ← 再検査対象の判定
confluence_id:          # 初回公開時に付与。冪等更新の鍵
confluence_space:
```

---

## 7. 入力ソースと取り込み

**共通方針（二段構え）:** パースや整形は決定論的スクリプトに寄せてトークンを消費せず、LLMは「判断（要約・相互参照・矛盾検出）」だけに使う。抽出 → 正規化md（raw/へ）→ 人がレビュー（HOTL①）→ LLMがingest。

### 7.1 議事録 / トランスクリプト（VTT または Word）

- **VTT** … WEBVTT形式。話者は `<v 話者名>` ボイスタグ等で判定、タイムスタンプ付き。仕様が定まっており着手可能
- **Word(.docx)** … MS Teamsトランスクリプトのエクスポート。話者名・タイムスタンプ・本文が並ぶ標準レイアウトを想定し python-docx で抽出。**構造は初回の実サンプルで検証（→ §10）**
- 抽出物: 日付・出席者・会議名 + 発話（話者/時刻/本文）。アクションアイテムと決定を拾う

### 7.2 進捗報告デッキ（pptx）

- python-pptx（お持ちのpptxスキルを流用）で、スライドタイトル=見出し、本文テキスト、スピーカーノート、表を抽出
- 定型テンプレならステータス表・リスク一覧・マイルストーンを構造化データとして抽出
- **図・スクショはraw/に保持するが Confluence へは出さない**（テキストのみ公開）。必要時はソース参照リンクで代替

### 7.3 Teamsチャット（CSV）

Power Automateの出力を**CSV（UTF-8）**とする。スレッド復元・発言者特定・ノイズ除外に必要な最小構成として、以下のカラムを定義する。

| カラム              | 必須 | 形式                 | 説明                                                                     |
| ------------------- | ---- | -------------------- | ------------------------------------------------------------------------ |
| `message_id`        | 必須 | 文字列               | メッセージの一意ID                                                       |
| `parent_message_id` | 必須 | 文字列（空可）       | 返信元の `message_id`。ルート投稿は空。**スレッド復元に使用**            |
| `timestamp`         | 必須 | ISO 8601             | 投稿日時（例: `2026-07-12T09:30:00+09:00`）                              |
| `author_name`       | 必須 | 文字列               | 送信者の表示名                                                           |
| `author_email`      | 推奨 | 文字列               | 送信者メール。**人物の名寄せ・表記ゆれ解決**に使用                       |
| `body`              | 必須 | 文字列               | 本文（プレーンテキスト。@メンションは可能なら氏名へ解決済み）            |
| `channel_or_chat`   | 推奨 | 文字列               | 取得元のチャネル/チャット名                                              |
| `mentions`          | 任意 | 文字列（`;` 区切り） | @メンションされた人（氏名またはメール）                                  |
| `message_type`      | 任意 | 文字列               | `message` / `system`。`system`（参加通知等）はPower Automate側で除外推奨 |
| `has_attachment`    | 任意 | `true`/`false`       | 添付有無の記録（添付・画像は公開wikiには取り込まない）                   |

- 改行を含む本文があるため、値はダブルクォートで囲み、RFC 4180準拠のCSVとする
- リアクション・参加通知等のノイズはPower Automate側で除外し、返信関係（`parent_message_id`）は保持する
- ingestはチャット特性を踏まえ、逐語要約ではなく**決定・未解決の論点・非公式な知見**の抽出に振り切る

---

## 8. 操作（ingest / query / lint）と HOTL

- **Ingest** … raw/に新ソースを置いて投入 → 要点を対話で確認（HOTL②）→ summary作成、index更新、関連entity/decision/conceptを横断更新、log追記。1ソースで10〜15ページに触れる。新規/追記の判定は「他から参照される独立した実体/概念なら新規、既存の属性・更新なら追記」
- **Query** … `index.md` でルーティング → 該当ページを読み、出典付きで統合回答。良い回答はwikiへ還元可（ただし圧縮原則を守り焼き直しは作らない）
- **Lint（必須）** … 最大の失敗モードは「ingest時に相互参照を更新しきれずページが腐るドリフト」。frontmatter欠落・orphan・重複は機械チェック、stale/矛盾はLLM判断。ハードルール: 単独削除しない / lintはコンテンツを書き換えない（frontmatter修復のみ）/ 結果をlog追記。CI・タイマーで定期実行

---

## 9. Confluence公開（Atlassian MCP）

### 9.1 使うツール

公式Rovo MCPの `createConfluencePage` / `updateConfluencePage` / `getConfluencePage` / 配下ページ一覧 / `getConfluenceSpaces` を使用。本文フォーマットは `markdown`（デフォルト）を指定でき、**markdownをそのまま渡せる**ため独自のmd→ADF変換器は不要。

### 9.2 冪等性（sync_state.json）

MCPは離散的なツール呼び出しで、「公開済みか/変化したか」は追跡しない。そのため `sync_state.json` に `ローカルページ ↔ Confluence page-id ＋ 直近公開時のcontent-hash` を保持する。

- 未マッピング → `createConfluencePage`、返却page-idを保存
- マッピング済み ＆ hash変化 → `updateConfluencePage`（page-id指定）
- 変化なし → スキップ

### 9.3 ハード制約（MCP仕様に起因）

1. **マクロ不可** … storage形式を送れないため、目次・パネル・ステータス等のConfluenceマクロは変換時に落ちる。→ 公開ページは見出し・表・箇条書き・リンク・コード・本文のみで構成（TOCマクロ等は使わない）
2. **ページサイズ上限** … markdown本文が大きい（約56KB前後）と create/update がタイムアウト（約300秒）。加えて本文はツール呼び出しにインライン → 出力トークンも膨張。→ **1ページは数十KB以下（目安50KB未満）に抑える**（圧縮原則・index.md前提と一致）
3. **画像・添付アップロード不可** … Rovo MCPに添付アップロードのツールが無い。→ **テキストのみ公開**（本設計の決定と一致）。図が必要なら添付だけREST直叩きの別工程が要る（今回は対象外）

### 9.4 公開フロー（HOTLゲート）

`ingest（ローカル・レビュー付き）→ git commit → publish.py を dry-run（作成/更新するN件＋差分を提示）→ 承認（HOTL③）→ MCP発火`。git commitが自然なチェックポイント兼監査。共有wikiへのpushは常に人の承認を挟む。

### 9.5 実測での裏取り（推奨）

上記MCP挙動は公式リポジトリで未解決要望が出ている項目を含むため、接続済みインスタンスで `tools/list` と本文の受け口を一度実測し、仕様変更が無いか確認しておく。

---

## 10. 残課題（未確定 / 実装中に確定）

- **Wordトランスクリプト(.docx)の構造** … 実サンプル1件で最終確定（VTTは仕様定義済みで先行着手可）
- **接続済みAtlassian MCPの実測** … `tools/list`・本文フォーマットの受け口・page-id更新の挙動を裏取り
- **（将来）日本語検索アナライザ** … 規模が数百ページを超えた時点でハイブリッド検索（分かち書き）を検討
- **（将来）チーム化** … 公開を冪等＋gitコミット済みに保ち、チーム展開時にPRゲート・排他・SKILL.md所有権を差し込む

---

## 11. 段階的構築プラン

1. **SKILL.md + ページ型/命名規約/frontmatterの確定**（スキーマが最重要）✅
2. **抽出スクリプト3種**（`transcript.py` / `pptx_extract.py` / `teams_extract.py`）✅
3. **少数ソースで手動ingest** → 構造とページ粒度を検証 ✅（合成サンプル3件で実施。詳細は `wiki/log.md` の2026-07-13 22:00エントリ、下記コラム参照）
4. **lint** の整備（機械チェック + LLM判断、定期実行）
5. **publish**（sync_state + MCP、dry-run→承認ゲート）

> **§11-3 検証メモ（2026-07-13）:** 実サンプルが未入手のため、架空の「在庫管理システム刷新プロジェクト」を題材に、VTT議事録・pptx進捗デッキ・Teams CSVの3ソースを作成し `raw/` に配置。3種の抽出スクリプトで正規化mdを生成 → レビュー → entity 6件・decision 1件・concept 1件・open_question 1件・summary 3件（計12ページ）をwikiへ反映し、`index.md`/`overview.md`/`log.md` を更新。3ソースが同一プロジェクトの一連の出来事だったため、圧縮原則（entity/decision/conceptに情報を集約し、summaryは薄く保つ）が機能することを確認できた。docx経路（Wordトランスクリプト）は今回未検証のまま（§10参照）。

---

## 付録: 参考リンク

- Karpathy「llm-wiki」: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Atlassian Rovo MCP Server（公式）: https://www.atlassian.com/platform/remote-mcp-server
- 公式リポジトリ: https://github.com/atlassian/atlassian-mcp-server
- 対応ツール一覧: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/supported-tools/
- 関連Issue（storage形式/マクロ/大容量/添付の制約）: atlassian-mcp-server の #182, #161, #60, #59, #21
