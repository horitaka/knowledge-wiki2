# frontmatterスキーマ

全ページ（`wiki/` 配下のすべてのmarkdown）は以下のYAML frontmatterを先頭に持つ。

```yaml
---
type: entity            # entity | concept | decision | summary | overview | open_question
title: 田中太郎
description: XXプロジェクトのテックリード。バックエンド全般を担当
tags: [人物, XXプロジェクト]
timestamp: 2026-07-13T10:00:00+09:00
sources:
  - raw/transcripts/2026-07-10_定例.md
  - raw/teams/2026-07-11_thread-042.md
status: active           # draft | active | stale | superseded
confluence_id:            # 初回公開時に付与。空のまま未公開を表す
confluence_space:         # 例: KNOW
---
```

## フィールド定義

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `type` | 必須 | `entity` / `concept` / `decision` / `summary` / `overview` / `open_question` のいずれか。ページ型の定義は [page-types.md](page-types.md) |
| `title` | 必須 | ページの主題。ファイル名の元になる（[naming-conventions.md](naming-conventions.md)） |
| `description` | 必須 | 一行要約。`index.md` の一覧表示にそのまま使う |
| `tags` | 任意 | 横断検索・分類用のタグの配列 |
| `timestamp` | 必須 | 最終更新日時（ISO 8601）。ingestで内容を更新するたびに更新する |
| `sources` | 必須（summaryは1件、entity/concept/decisionは複数可） | どの `raw/` ソースが当該ページの内容に寄与したかの相対パス一覧。来歴の唯一の記録場所 |
| `status` | 必須 | 下表参照。lintのstale/矛盾判定の対象になる |
| `confluence_id` | 公開後に必須 | 初回 `publish` 時にMCPから返却されるpage-idを記録する。冪等更新の鍵。未公開の間は空 |
| `confluence_space` | 公開後に必須 | 公開先のConfluence spaceキー |

## `status` の意味

| 値 | 意味 | 遷移条件 |
| --- | --- | --- |
| `draft` | ingest直後、まだレビュー未確定 | HOTL②の確認が済んだら `active` へ |
| `active` | 現行の正しい情報 | 通常状態 |
| `stale` | 一定期間更新がない、または内容の鮮度に疑義がある | lintのLLM判断で検出。人が確認して `active` に戻すか `superseded` にする |
| `superseded` | 別ページに置き換えられた | 単独削除の代わりに使う。`decision` ページでは新しい決定ページへのリンクを本文に残す |

## decision型の追加フィールド

`type: decision` のページは frontmatter に加えて本文に以下を必ず含める（詳細は [page-types.md](page-types.md)）。

- 決定者
- 決定日
- 根拠
- 撤回/再検討条件
- supersede関係（このdecisionが何を置き換えたか、何に置き換えられうるか）
