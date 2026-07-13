# publish ワークフロー（Confluence Cloud / Atlassian MCP）

**現状 `scripts/publish/publish.py` は未実装（フェーズ2）。** このファイルは実装時の仕様と、実装前に手動でpublishする場合の注意点をまとめる。

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

## ハード制約（MCP仕様に起因。必ず守る）

1. **マクロ不可**: storage形式を送れないため、目次・パネル・ステータス等のConfluenceマクロは変換時に落ちる。公開ページは見出し・表・箇条書き・リンク・コード・本文のみで構成する（TOCマクロ等は使わない）
2. **ページサイズ上限**: markdown本文が大きい（約56KB前後）と create/update がタイムアウト（約300秒）。本文はツール呼び出しにインラインされるため出力トークンも膨張する。**1ページは目安50KB未満に抑える**（圧縮原則・summaryを薄く保つ方針と一致させる）
3. **画像・添付アップロード不可**: Rovo MCPに添付アップロードのツールが無い。**テキストのみ公開**する。図が必要な場合は `raw/assets/` への参照リンクで代替する（添付の直叩きは対象外）

## 公開フロー（HOTLゲート）

```
ingest（ローカル・レビュー付き）
  → git commit
  → publish.py を dry-run（作成/更新するN件＋差分を提示）
  → 承認（HOTL③）
  → Atlassian MCP発火
```

git commitが自然なチェックポイント兼監査。共有wikiへのpushは常に人の承認を挟む。dry-runでは実際にMCPを呼ばず、対象ページ一覧・create/updateの別・差分サマリのみを提示する。

## 未実装時の代替手順（手動publish）

`publish.py` が無い間にどうしても公開が必要な場合:

1. 対象ページを1件選び、[ハード制約](#ハード制約mcp仕様に起因必ず守る)を満たしているか確認する（サイズ・マクロ不使用・画像なし）
2. 対象ページの `confluence_id` frontmatterを確認する
   - 空 → `createConfluencePage` を呼び、返却されたpage-idをそのページのfrontmatterに書き戻す
   - 値あり → `updateConfluencePage` をそのpage-idで呼ぶ
3. 呼び出し前に必ず人に対象ページと内容を提示し、承認を得る（HOTL③相当）
4. 公開結果を `wiki/log.md` に追記する

## 実測での裏取り（推奨）

上記MCP挙動は公式リポジトリで未解決要望が出ている項目を含むため、接続済みインスタンスで `tools/list` と本文の受け口を一度実測し、仕様変更が無いか確認しておく（docs/llm-wiki.md §10・§9.5）。
