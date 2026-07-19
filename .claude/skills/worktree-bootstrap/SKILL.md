---
name: worktree-bootstrap
description: >
  wave-scheduler が出す waves.json を読み、指定した wave の各タスクぶん git worktree を
  main（既定）ベースで新規作成し、.env のコピー・`uv sync`・`pytest --collect-only`
  スモークチェックまでを一括実行する。並列実装パイプライン工程6（agent teams + worktree
  実装）の前段。「worktree を作って」「各 worktree の環境構築」「wave の環境をセットアップ」
  「.env をworktreeにコピーしてuv syncして」といった依頼で起動する。
---

# worktree-bootstrap（工程6準備：各 worktree の環境構築）

`wave-scheduler` が出した `waves.json` の 1 wave ぶん（teammate 数だけ）の worktree を、
teammate（Agent）を起動する**前に**まとめて用意するスキル。ここを毎回手作業でやると
「.env コピー忘れで API キーが読めない」「uv sync し忘れて import エラー」のような
本質と無関係な失敗で teammate の1ターンを浪費するため、機械的に潰す。

## このスキルがやること／やらないこと

| やる                                                                | やらない                                        |
| ------------------------------------------------------------------- | ----------------------------------------------- |
| base ブランチを fetch し、最新コミットから branch + worktree を作成 | 実装そのもの（teammate/Agent の仕事）           |
| repo root の `.env` を worktree にコピー                            | PR 作成・マージ                                 |
| worktree 内で `uv sync`                                             | worktree の削除（`git worktree remove` は別途） |
| `uv run pytest --collect-only -q` でスモークチェック                | テストの実行・グリーン化（teammate の仕事）     |

## 前提

- `wave-scheduler` の出力 `waves.json` があること（無い場合は `--branch` の ad-hoc モードを使う）
- ローカルに `uv` がインストール済み
- `.env` は repo root にある想定（無くても致命的エラーにはしない＝ WARN 扱い。mock 中心のタスクなら無くても進められる）

## 実行

### wave 単位（通常はこちら）

```bash
python3 .claude/skills/worktree-bootstrap/scripts/bootstrap_worktree.py \
  --waves-json specs/<story-id>/waves.json \
  --wave 1 \
  --base main
```

wave 内の全タスク（teammate 数ぶん）の worktree をまとめて作る。ブランチ名はリポジトリーのルールに則る

`--dag specs/<story-id>/plan.dag.json`（dependency-mapper の出力）を併せて渡すと、
各タスクの `title` から ASCII 部分だけを抽出した slug が付与され
`<id>-<slug>`（例: `fix/j-trade-logs-retention`）になる。plan.dag.json は
dependency-mapper スキル共通のスキーマであり、**特定のディレクトリ構成やファイル命名規則を
前提にしない**ため、このリポジトリに限らずどのプロジェクトでもそのまま使える。

### 1タスクだけやり直す

```bash
... --waves-json specs/<story-id>/waves.json --wave 1 --task-id L --force
```

### waves.json を使わない ad-hoc モード

```bash
... --branch fix/my-change --base main
```

### 主なオプション

| オプション                 | 既定値                            | 用途                                                                                    |
| -------------------------- | --------------------------------- | --------------------------------------------------------------------------------------- |
| `--worktrees-dir`          | `../<repo名>-worktrees`           | worktree の置き場所（repo外の兄弟ディレクトリ）                                         |
| `--dag`                    | なし                              | `plan.dag.json` を渡すとタスク `title` からブランチ slug を生成（無ければタスクIDのみ） |
| `--branch-prefix`          | `fix/`                            | ブランチ名の接頭辞                                                                      |
| `--env-file`               | `.env`                            | コピーする環境変数ファイル                                                              |
| `--no-sync` / `--no-smoke` | off                               | 該当ステップをスキップ                                                                  |
| `--smoke-cmd`              | `uv run pytest --collect-only -q` | import 崩れの検知だけを目的にした軽量コマンド                                           |
| `--dry-run`                | off                               | 実際には何も作らず、実行内容だけ表示                                                    |
| `--force`                  | off                               | 既存 worktree を削除して作り直す                                                        |

## 出力の読み方

```
task  branch                          worktree  env       uv sync   smoke
L     fix/l-trade-logs                OK        OK        OK        OK
J     fix/j-trade-logs-retention      OK        OK        OK        OK
K     fix/k-vercel-cron               OK        OK        OK        OK
```

いずれかが `NG` の場合、直下に理由（fetch失敗・uv sync のエラー出力・.env欠如など）が出る。
`env` の NG は `.env` 不在（警告レベル、teammate 起動自体は妨げない）、`worktree`/`uv sync`/`smoke`
の NG は起動前に人間が直すべき問題。

## wave 境界での使い方（重要）

このスキルは実行のたびに `git fetch origin <base>` してから分岐する。
**wave N+1 の worktree を作るのは、wave N の全 PR が base ブランチにマージされた後**に限る。
`wave-scheduler` が出す `depends_on`（例：O は L・M に依存）は「L・M がマージ済みの main」を
前提にしている。マージ前に先回りして全 wave 分の worktree を一括作成すると、O 側の分岐元が
古い main のままになり、O の teammate は L・M のヘルパをまだ見えない状態で実装を始めてしまう。

## 人のチェック（HOTL）

wave の切れ目（前 wave マージ直後・次 wave 着手前）に1回、`--dry-run` で対象タスクと
ブランチ名を確認してから本実行するのを推奨。生成後の状態確認は上記の表を数秒眺めれば足りる。

## やってはいけないこと

- コピーした `.env` を worktree 内で `git add` しない（`.gitignore` 対象。誤コミット厳禁）
- 現在のリポジトリ（呼び出し元の作業ディレクトリ）のブランチを勝手に checkout しない
  （`git worktree add` は独立した作業ディレクトリを作るだけで、呼び出し元の checkout には触れない）
- 前 wave が未マージのまま次 wave の worktree を作らない（上記「wave 境界での使い方」参照）
- `uv sync` や スモークチェックが失敗した worktree に teammate を起動しない
  （import エラーの原因究明で teammate のターンを浪費させない）
