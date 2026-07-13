# AGENTS.md

このリポジトリはLLM Wiki（Karpathyの「llm-wiki」パターンに基づく組織内ナレッジベース）である。Claude Code以外のツールでこのリポジトリを扱う場合も、以下を読むこと。

- 設計の背景・決定事項: [docs/llm-wiki.md](docs/llm-wiki.md)
- スキーマ・ワークフロー（最重要）: [.claude/skills/llm-wiki/SKILL.md](.claude/skills/llm-wiki/SKILL.md)

## 最低限守るべきこと

1. `wiki/` 配下のmarkdownが唯一の正。Confluence上での直接編集はしない
2. `raw/` は不変の一次ソース。改変しない
3. 複数ソースを跨いで圧縮するページ（entity/decision/concept）だけが価値を持つ。1ソースの書き写しは作らない
4. ページを単独削除しない（`status: superseded` にする）
5. Confluenceへの公開は必ず人の承認を挟む（HOTLゲート）
