---
name: llm-wiki
description: 組織内ナレッジ（会議議事録・進捗デッキ・Teamsチャット）をローカルmarkdown wikiとして構築・保守し、Confluence Cloudへ公開する。ingest（新規ソースの取り込み）、query（wikiへの問い合わせ）、lint（整合性チェック）、publish（Confluence反映）のいずれかを行うときに使う。設計の背景・決定事項は docs/llm-wiki.md を参照。
---

# LLM Wiki

Karpathyの「llm-wiki」パターン（RAGで毎回生ソースから再発見するのではなく、構造化・相互リンクされたmarkdown群を継続的に構築・保守する）を、このリポジトリのナレッジ管理に適用するスキル。

**唯一の正は `wiki/` 配下のローカルmarkdown。Confluenceはそこから生成される公開ミラーであり、直接編集はしない。**

設計の背景・決定理由・未確定事項は [docs/llm-wiki.md](../../../docs/llm-wiki.md) にまとめてある。矛盾があれば docs/llm-wiki.md を正とし、このSKILL.mdを追従させる。

## ディレクトリ構成

```
raw/            不変の一次ソース。読むだけで改変しない
  transcripts/  会議議事録・トランスクリプト（VTT / Word / txt / md）
  decks/        進捗報告デッキ（pptx / PDF）
  teams/        Teamsチャット履歴（CSV / txt / md）
  assets/       図・スクリーンショット等（Confluenceへは公開しない）

wiki/           LLMが維持するmarkdown群。公開wikiの正
  index.md      全ページへのルーティング入口
  log.md        ingest/lint/publishの監査ログ
  overview.md   プロジェクト全体像
  entities/     プロジェクト・人/役割・チーム・システム・ベンダー
  concepts/     横断テーマ
  decisions/    決定 + 根拠 + 撤回条件 + supersede関係
  open_questions/  未解決論点・矛盾のキュー
  summaries/    一次ソース1件 = 1ページ（軽量な来歴）

.claude/skills/llm-wiki/
  SKILL.md        このファイル
  references/     ページ型・命名規約・各ワークフローの詳細
  scripts/        決定論的な前処理・lint・publishスクリプト（フェーズ2で実装）
```

## 圧縮原則（最重要）

複数の一次ソースを跨いで**圧縮・統合するページだけが価値を持つ**。1ソースを書き写しただけのページ（例: 会議議事録をそのまま1ページ化）は負の価値であり作らない。

- 押し出す主役は **entity / decision / concept**
- **summary** は来歴として薄く保つ（要点リンク + 出典のみ）
- 会議議事録を機械的に1本ずつConfluenceへ公開してノイズで埋めない

詳細は [references/page-types.md](references/page-types.md) を参照。

## ワークフロー

このスキルは4つの操作を提供する。それぞれの詳細手順は references/ 配下の対応ファイルを読んでから実行すること。

| 操作 | いつ使うか | 詳細 |
| --- | --- | --- |
| **ingest** | `raw/` に新しい一次ソースが置かれたとき | [references/ingest.md](references/ingest.md) |
| **query** | wikiの内容について質問されたとき | [references/query.md](references/query.md) |
| **lint** | 定期実行、またはingest直後の整合性確認 | [references/lint.md](references/lint.md) |
| **publish** | ローカルの変更をConfluenceへ反映するとき | [references/publish.md](references/publish.md) |

### ingest の要点

1. 決定論的スクリプト（`scripts/ingest_prep/`）で raw ソースを正規化mdへ抽出する。要約・判断は行わない（トークンを使わない）
   - Microsoft情報保護ラベル（IRM/Azure RMS）で保護されたファイルが渡された場合、スクリプトが検出してエラーを返す。ラベル解除権限者による複製作成のほか、印刷/エクスポートが許可されていればPDFとして保存し `raw/` に配置し直した上で `pdf_extract.py` で再実行するようユーザーに促す（詳細は[references/ingest.md](references/ingest.md)）
2. 人がレビューする（HOTL①）
3. LLMが正規化mdを読み、要点を対話で確認する（HOTL②）
4. summary作成、`index.md` 更新、関連する entity/decision/concept を横断更新、`log.md` に追記する
5. 新規ページを作るか既存ページに追記するかの判定基準: **他から参照される独立した実体/概念なら新規、既存ページの属性・更新にすぎないなら追記**

### query の要点

1. `wiki/index.md` から該当ページへルーティングする
2. 該当ページを読み、出典（sources）付きで統合回答する
3. 良い回答はwikiへ還元してよいが、圧縮原則を守り焼き直しのページは作らない

### lint の要点

最大の失敗モードは「ingest時に相互参照を更新しきれずページが腐るドリフト」。

- 機械チェック（`scripts/lint.py`）: frontmatter欠落・orphanページ・重複
- LLM判断: stale判定・矛盾検出（結果は `wiki/open_questions/` へ）
- ハードルール:
  - ページを**単独削除しない**（status: superseded にして残す）
  - lintは**コンテンツを書き換えない**（frontmatter修復のみ）
  - 結果は必ず `log.md` に追記する

### publish の要点

`（初回のみ）space・親ページをユーザーに確認 → publish.py configure → ingest（ローカル・レビュー付き）→ git commit → publish.py を dry-run → 承認（HOTL③）→ Atlassian MCP発火`

1リポジトリ=1スペース=1親ページ配下が前提。space・親ページ（root_page_id）はページごとのfrontmatterではなく `publish_config.json` に一箇所だけ持つ。**初回publish時**にユーザーからspaceと親ページの指定が無ければ、agentはAskUserQuestion等で明示的に問い合わせる（推測・仮決めしない）。**2回目以降**は `publish_config.json` に記録済みの値をそのまま使い、聞き直さない。`wiki/` のディレクトリ構造（entities/concepts/decisions/open_questions/summaries）は親ページ配下のフォルダページとして再現される。

git commitが自然なチェックポイント兼監査。共有Confluenceへのpushは常に人の承認を挟む。MCPのハード制約（マクロ不可・ページサイズ上限・添付不可）とスペース/階層の設定方法は [references/publish.md](references/publish.md) を必ず確認すること。

## frontmatter

全ページ共通のfrontmatterスキーマ・各フィールドの意味は [references/frontmatter.md](references/frontmatter.md) を参照。

## 命名規約・日本語の名寄せ

ファイル名・entity名の正規化ルールは [references/naming-conventions.md](references/naming-conventions.md) を参照。人名・プロジェクト名の表記ゆれ（「田中さん」/「田中」/フルネーム等）はingest時に必ず正規化する。

## 現在の実装状況

- [x] ディレクトリ骨格 / SKILL.md / ページ型・命名規約・frontmatterスキーマ
- [x] 抽出スクリプト4種（`scripts/ingest_prep/transcript.py` / `pptx_extract.py` / `teams_extract.py` / `pdf_extract.py`）。合成データで検証済み。**実サンプル未検証**（特にWord(.docx)議事録の話者/時刻レイアウトは仮のヒューリスティック — docs/llm-wiki.md §10）。`pdf_extract.py`はIRM保護ファイルの代替導線として新規追加。`transcript.py`は自由記述の議事録メモ（txt/md）にも対応（frontmatter付与＋本文パススルーのみ、構造抽出はしない — docs/llm-wiki.md §11-7）。`teams_extract.py`は自由記述のチャットログ（txt/md）にも対応（同様にfrontmatter付与＋本文パススルーのみ、スレッド復元・発言者構造抽出はしない — docs/llm-wiki.md §11-8）
- [x] 少数ソースでの手動ingest検証（合成サンプル3件・VTT/pptx/Teams CSV）。抽出→レビュー→wiki反映→index/overview更新→log追記の一連のワークフローを確認。詳細は `wiki/log.md` の2026-07-13 22:00エントリ
- [ ] `scripts/search.py`
- [x] `scripts/lint.py`（frontmatter欠落・orphan・重複疑い・リンク切れの機械チェック、`--fix`で安全なfrontmatter補完のみ実施。stale判定・矛盾検出はLLM判断のまま）
- [x] `scripts/publish/publish.py`（`configure`でspace・親ページIDを`publish_config.json`へ一元管理、`plan`でフォルダ/create/update/skip/blockedを判定しdry-run表示、`record`でMCP呼び出し後の結果をsync_state.json + frontmatterへ書き戻す。**MCP発火自体はagentが行う**、スクリプトは呼べない）。1リポジトリ=1スペース=1親ページ配下、wikiのディレクトリ構造をConfluence側のフォルダページ階層として再現する設計に更新済み（2026-07-15）
- [ ] Atlassian MCPの実測（tools/list・本文フォーマット・page-id更新挙動）。現時点で接続済みMCPインスタンス未確認のため未実施

未実装の操作を求められた場合は、決定論的スクリプトが無いことを明示した上で、手動またはLLM単体での代替手順を提案すること。
