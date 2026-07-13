# lint ワークフロー

**最大の失敗モードは、ingest時に相互参照を更新しきれずページが腐る「ドリフト」。** lintはそれを検出・修復するための定期チェック。

## 機械チェック（`scripts/lint.py`）

以下は決定論的に判定できるためスクリプト化済み（docs/llm-wiki.md §11）。

- frontmatter欠落・必須フィールド不足（[frontmatter.md](frontmatter.md)の必須項目を参照。`type`/`status` の不正値・ディレクトリとの不一致も含む）
- orphanページ（どこからもリンクされていない、`index.md` にも載っていない）
- 重複ページ（同一entityが名寄せされずに複数ファイルに分裂している疑い。タイトル完全一致はerror、部分一致はwarningとして人/LLMのレビューに回す）
- リンク切れ（相互リンク先・`sources` の参照先ファイルが存在しない）

実行: `python3 .claude/skills/llm-wiki/scripts/lint.py [--wiki-dir wiki] [--fix]`

- 既定はread-only。exit codeはerrorが1件でもあれば1、なければ0
- `--fix` は frontmatterに**完全に欠落しているキー**（`type`/`tags`/`status`/`confluence_id`/`confluence_space`）のみ既定値で補完する。`type` はディレクトリから、`status` は `draft` を既定値とする。**`title`/`description`/`timestamp`/`sources` は値を推測できないため対象外**（欠落していれば人/LLMが内容を見て埋める）
- stale判定・矛盾検出はスクリプト化していない（決定論的に判定できないため。下記「LLM判断が必要なチェック」を参照）

## LLM判断が必要なチェック

- **stale判定**: `timestamp` が古く、かつ関連する新しいsourceが追加されているのに更新されていないページを `status: stale` にする
- **矛盾検出**: 複数ページ間で内容が矛盾している（例: あるentityの役割が別々のページで違う記述になっている）場合、`wiki/open_questions/` に矛盾として積む

## ハードルール

1. **ページを単独削除しない**。置き換えの場合は `status: superseded` にし、置き換え先へのリンクを本文に残す
2. **lintはコンテンツを書き換えない**。frontmatterの修復（欠落フィールドの補完、status更新）のみ行う。本文の要約・言い換えはlintの仕事ではない（ingestで行う）
3. lint結果は必ず `wiki/log.md` に追記する（日時・検出件数・対応内容）
4. CI・タイマーでの定期実行を前提に設計する（現状は手動実行）

## 実行手順

1. `python3 .claude/skills/llm-wiki/scripts/lint.py` を実行し、機械チェックの結果を確認する
2. 欠落キーで安全に補完できるもの（`type`/`tags`/`status`/`confluence_id`/`confluence_space`）は `--fix` 付きで再実行する。`title`/`description`/`timestamp`/`sources` の欠落や、`duplicate`/`duplicate_suspect`/`orphan` の指摘は本文の理解が要るため、LLMが該当ページを読んで判断する（新規作成すべきか、既存ページへ統合すべきか等）
3. `status: active` のページ間で矛盾がないか目視で確認する（entity/decisionを優先）。stale判定（更新が滞っているのに関連sourceが増えているページ）もここで行う
4. 検出結果（機械チェックの残issue、矛盾、stale判定）を `wiki/open_questions/` および `wiki/log.md` に記録する
