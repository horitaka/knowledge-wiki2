# publish ワークフロー（Confluence Cloud / Atlassian MCP）

`scripts/publish/publish.py` を実装済み。**重要な制約: Pythonスクリプトは Atlassian MCP のツール（`createConfluencePage` / `updateConfluencePage`）を自分では呼び出せない。** MCPツールを呼べるのはClaude Code agent（LLM）だけなので、役割を分割している。

- `publish.py configure` … **初回publish前に一度だけ**、公開先の space と親ページID（root_page_id）を `publish_config.json` へ保存する。1リポジトリ=1スペース=1親ページ配下が前提で、ページごとのfrontmatterにspaceは持たせない
- `publish.py plan` … 決定論的な部分（フォルダ/対象ページの走査・content_hashの算出・sync_state.jsonとの差分判定・ハード制約チェック・dry-run表示）を行う。**状態は一切書き換えない**
- `publish.py record` … agentがMCPツールを呼んでpage-idを得た**後**に、その結果を `sync_state.json`（フォルダ・ページ共通）と、コンテンツページのfrontmatter（`confluence_id`のみ）へ書き戻す

## スペース・親ページの指定（1リポジトリ=1スペース=1親ページ配下）

ページ単位でconfluence_spaceを持たせるとwikiのどのページも同じ値を持つだけで複雑さしか増えないため廃止した。代わりに `scripts/publish/publish_config.json` に1箇所だけ設定する。

```json
{
  "space": "KNOW",
  "root_page_id": "123456",
  "configured_at": "2026-07-15T10:00:00+09:00"
}
```

- **初回publish時**: agentはユーザーにspace（Confluenceスペースキー）と、配下にwikiを再現する親ページ（root_page_id、既存の実ページのIDまたはURL）を確認する。ユーザーからチャットで未指定の場合は、AskUserQuestion等で明示的に問い合わせる（agentが値を推測・仮決めしない）。値が揃ったら次を実行する。
  ```
  python3 scripts/publish/publish.py configure --space <SPACEKEY> --root-page-id <親ページID>
  ```
- **2回目以降のpublish時**: `publish_config.json` に前回の値が残っているので、agentは何も聞かず `plan`/`record` をそのまま実行する。`plan` は `publish_config.json` が未設定（space/root_page_id のどちらかが空）だと exit code 2 で止まり、configureを促すメッセージを出す
- space/root_page_id を変更したい場合は `configure --force` が必要（誤って上書きしないためのガード）。**変更しても、既存にpublish済みのフォルダ・ページのsync_state.jsonエントリは自動移行されない**（旧親ページ配下に残ったままになる）ため、原則変更しない運用とする

## ページ階層（リポジトリのフォルダ構造 = Confluenceのページ構造）

`root_page_id` で指定した親ページの配下に、`wiki/` のディレクトリ構造をそのまま再現する。

```
<root_page_id>（ユーザー指定の既存ページ）
├─ overview.md の内容（wiki/直下のページはroot直下の子ページになる）
├─ entities（フォルダページ。自動生成・タイトルは "entities"）
│   ├─ 田中太郎
│   └─ ...
├─ concepts（フォルダページ）
├─ decisions（フォルダページ）
├─ open_questions（フォルダページ）
└─ summaries（フォルダページ）
```

- `entities` / `concepts` / `decisions` / `open_questions` / `summaries` の各ディレクトリは、配下に公開対象ページが1件以上あれば、対応する「フォルダページ」（タイトル=ディレクトリ名、本文なし）としてConfluence側にも自動生成される。実体を持つmarkdownファイルは無い（`wiki/entities/` 自体に対応するmdファイルは無い）
- `wiki/overview.md` のようにディレクトリ直下ではないページは、フォルダページを経由せず `root_page_id` の直接の子ページになる
- `index.md` / `log.md` は非公開（従来通り）

## 使うツール

公式Rovo MCPの `createConfluencePage` / `updateConfluencePage` / `getConfluencePage` / 配下ページ一覧 / `getConfluenceSpaces`。本文フォーマットは `markdown`（デフォルト）を指定でき、markdownをそのまま渡せるため独自のmd→ADF変換器は不要。`createConfluencePage` 呼び出し時は親ページID（フォルダページ、またはroot_page_id）を指定すること。

## 冪等性（sync_state.json）

MCPは離散的なツール呼び出しで「公開済みか/変化したか」を追跡しない。そのため `scripts/publish/sync_state.json` に `ローカルページパス（またはフォルダキー） ↔ Confluence page-id ＋ 直近公開時のcontent-hash` を保持する。フォルダページのキーは `wiki/<dirname>`（例: `wiki/entities`）。

```json
{
  "wiki/entities": {
    "confluence_id": "789012",
    "published_at": "2026-07-15T10:05:00+09:00"
  },
  "wiki/entities/田中太郎.md": {
    "confluence_id": "123456",
    "content_hash": "sha256:...",
    "published_at": "2026-07-15T10:06:00+09:00"
  }
}
```

- コンテンツページが未マッピング → `createConfluencePage`（親IDはフォルダページのconfluence_id、または直下ページならroot_page_id）。返却page-idを `sync_state.json` と対象ページの `confluence_id` frontmatterの両方に保存
- コンテンツページがマッピング済み ＆ hash変化 → `updateConfluencePage`（page-id指定。親は変わらないので指定不要）
- 変化なし → スキップ
- フォルダページが未作成 → `createConfluencePage`（親IDはroot_page_id、本文なしの空ページで可）。返却page-idを `sync_state.json` の `wiki/<dirname>` キーへ保存。フォルダページは一度作成すれば更新しない

`content_hash` は `sha256(title + "\n" + body)`（frontmatterを除いた本文部分。フォルダページには無い）。`publish.py plan` が算出し、`publish.py record` がMCP呼び出し後にsync_state.jsonへ書き戻す。

## ハード制約（MCP仕様に起因。必ず守る）

1. **マクロ不可**: storage形式を送れないため、目次・パネル・ステータス等のConfluenceマクロは変換時に落ちる。公開ページは見出し・表・箇条書き・リンク・コード・本文のみで構成する（TOCマクロ等は使わない）
2. **ページサイズ上限**: markdown本文が大きい（約56KB前後）と create/update がタイムアウト（約300秒）。本文はツール呼び出しにインラインされるため出力トークンも膨張する。**1ページは目安50KB未満に抑える**（圧縮原則・summaryを薄く保つ方針と一致させる）
3. **画像・添付アップロード不可**: Rovo MCPに添付アップロードのツールが無い。**テキストのみ公開**する。図が必要な場合は `raw/assets/` への参照リンクで代替する（添付の直叩きは対象外）

## 公開フロー（HOTLゲート）

```
（初回のみ）ユーザーへspace・親ページを確認 → publish.py configure
ingest（ローカル・レビュー付き）
  → git commit
  → publish.py plan（フォルダ作成要否＋作成/更新するN件＋blocked/差分を提示。状態は書き換えない）
  → 承認（HOTL③）
  → agentがAtlassian MCPを発火
      1. planのfoldersに挙がった未作成フォルダページを先に作成（親=root_page_id）
      2. 作成のたびに publish.py record --folder <dirname> --confluence-id <id> で記録
      3. 対象ページ1件ずつ create/update（親IDはフォルダのconfluence_id、または直下ならroot_page_id）
      4. 各ページごとに publish.py record --page <path> --confluence-id <id> で記録
  → agentが wiki/log.md に公開結果を追記
```

git commitが自然なチェックポイント兼監査。共有wikiへのpushは常に人の承認を挟む。`publish.py plan` は実際にMCPを呼ばず、必要なフォルダ・対象ページ一覧・create/update/blockedの別・サイズ・content_hash差分のみを提示する。

## 実際の手順

1. **初回のみ**: ユーザーからspaceと親ページIDを確認し、`python3 scripts/publish/publish.py configure --space <space> --root-page-id <親ページID>` を実行する
2. `python3 scripts/publish/publish.py plan` を実行する
   - `publish_config.json` が未設定の場合はexit code 2で止まる。ユーザーに確認のうえ手順1を行う
   - `blocked` が1件でもあれば承認前に解消する（サイズ超過・画像埋め込みなど）
   - `--out`（既定 `scripts/publish/plan.json`）に本文込みの詳細planがJSONで出力される。agentがMCP呼び出し時にこれを参照してよい。各itemの `parent_key`/`parent_confluence_id` が親（フォルダまたはroot）を示す。`parent_confluence_id` が `null` の場合は、`folders` セクションの対応するフォルダを先に作成してから、そのconfluence_idを親として使う
3. 出力された `folders` / `create` / `update` の一覧を人に提示し、承認を得る（HOTL③）
4. 承認されたら、agentがまず未作成フォルダページを `createConfluencePage`（親=root_page_id、本文なし）で作成し、都度 `python3 scripts/publish/publish.py record --folder <dirname> --confluence-id <id>` を実行する
5. 続けて承認された各ページについて、agentが `createConfluencePage`（`action: create`、親=フォルダまたはroot_page_id）または `updateConfluencePage`（`action: update`、page-id指定）を呼ぶ
6. 呼び出しが成功したら、そのページについて `python3 scripts/publish/publish.py record --page <path> --confluence-id <id>` を実行し、結果を記録する
7. 一連の公開が終わったら `wiki/log.md` に対象ページ・件数・備考を追記する

## 実測での裏取り（推奨）

上記MCP挙動は公式リポジトリで未解決要望が出ている項目を含むため、接続済みインスタンスで `tools/list` と本文の受け口、および `createConfluencePage` の親ページ指定パラメータを一度実測し、仕様変更が無いか確認しておく（docs/llm-wiki.md §10・§9.6）。
