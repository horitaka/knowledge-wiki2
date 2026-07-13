# publish ワークフロー（Confluence Cloud / Atlassian MCP）

`scripts/publish/publish.py` を実装済み。**重要な制約: Pythonスクリプトは Atlassian MCP のツール（`createConfluencePage` / `updateConfluencePage`）を自分では呼び出せない。** MCPツールを呼べるのはClaude Code agent（LLM）だけなので、役割を分割している。

- `publish.py plan` … 決定論的な部分（対象ページの走査・content_hashの算出・sync_state.jsonとの差分判定・ハード制約チェック・dry-run表示）を行う。**状態は一切書き換えない**
- `publish.py record` … agentがMCPツールを呼んでpage-idを得た**後**に、その結果を `sync_state.json` とページのfrontmatter（`confluence_id`/`confluence_space`のみ）へ書き戻す

## 使うツール

公式Rovo MCPの `createConfluencePage` / `updateConfluencePage` / `getConfluencePage` / 配下ページ一覧 / `getConfluenceSpaces`。本文フォーマットは `markdown`（デフォルト）を指定でき、markdownをそのまま渡せるため独自のmd→ADF変換器は不要。

## 冪等性（sync_state.json）

MCPは離散的なツール呼び出しで「公開済みか/変化したか」を追跡しない。そのため `scripts/publish/sync_state.json` に `ローカルページパス ↔ Confluence page-id ＋ 直近公開時のcontent-hash` を保持する。

```json
{
  "wiki/entities/田中太郎.md": {
    "confluence_id": "123456",
    "confluence_space": "KNOW",
    "content_hash": "sha256:...",
    "published_at": "2026-07-13T10:00:00+09:00"
  }
}
```

- 未マッピング → `createConfluencePage`、返却page-idを `sync_state.json` と対象ページの `confluence_id` frontmatterの両方に保存
- マッピング済み ＆ hash変化 → `updateConfluencePage`（page-id指定）
- 変化なし → スキップ

`content_hash` は `sha256(title + "\n" + body)`（frontmatterを除いた本文部分）。`publish.py plan` が算出し、`publish.py record` がMCP呼び出し後にsync_state.jsonへ書き戻す。

## ハード制約（MCP仕様に起因。必ず守る）

1. **マクロ不可**: storage形式を送れないため、目次・パネル・ステータス等のConfluenceマクロは変換時に落ちる。公開ページは見出し・表・箇条書き・リンク・コード・本文のみで構成する（TOCマクロ等は使わない）
2. **ページサイズ上限**: markdown本文が大きい（約56KB前後）と create/update がタイムアウト（約300秒）。本文はツール呼び出しにインラインされるため出力トークンも膨張する。**1ページは目安50KB未満に抑える**（圧縮原則・summaryを薄く保つ方針と一致させる）
3. **画像・添付アップロード不可**: Rovo MCPに添付アップロードのツールが無い。**テキストのみ公開**する。図が必要な場合は `raw/assets/` への参照リンクで代替する（添付の直叩きは対象外）

## 公開フロー（HOTLゲート）

```
ingest（ローカル・レビュー付き）
  → git commit
  → publish.py plan（作成/更新するN件＋blocked/差分を提示。状態は書き換えない）
  → 承認（HOTL③）
  → agentがAtlassian MCPを発火（対象ページ1件ずつ create/update）
  → 各ページごとに publish.py record（page-idをsync_state.json + frontmatterへ書き戻す）
  → agentが wiki/log.md に公開結果を追記
```

git commitが自然なチェックポイント兼監査。共有wikiへのpushは常に人の承認を挟む。`publish.py plan` は実際にMCPを呼ばず、対象ページ一覧・create/update/blockedの別・サイズ・content_hash差分のみを提示する。

## 実際の手順

1. `python3 scripts/publish/publish.py plan --default-space <space>` を実行する
   - `blocked` が1件でもあれば承認前に解消する（サイズ超過・画像埋め込み・confluence_space未指定など）
   - `--out`（既定 `scripts/publish/plan.json`）に本文込みの詳細planがJSONで出力される。agentがMCP呼び出し時にこれを参照してよい
2. 出力された `create` / `update` の一覧を人に提示し、承認を得る（HOTL③）
3. 承認された各ページについて、agentが `createConfluencePage`（`action: create`）または `updateConfluencePage`（`action: update`、page-id指定）を呼ぶ
4. 呼び出しが成功したら、そのページについて `python3 scripts/publish/publish.py record --page <path> --confluence-id <id> --confluence-space <space>` を実行し、結果を記録する
5. 一連の公開が終わったら `wiki/log.md` に対象ページ・件数・備考を追記する

## 実測での裏取り（推奨）

上記MCP挙動は公式リポジトリで未解決要望が出ている項目を含むため、接続済みインスタンスで `tools/list` と本文の受け口を一度実測し、仕様変更が無いか確認しておく（docs/llm-wiki.md §10・§9.5）。
