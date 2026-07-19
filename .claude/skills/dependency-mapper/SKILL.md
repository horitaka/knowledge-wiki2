---
name: dependency-mapper
description: >
  tasks.md（Spec Kit の PR 粒度タスク）と impact.md（影響範囲マップ）から、機械可読な依存 DAG
  (plan.dag.json) を生成する。各タスクに論理依存 (depends_on) と接触ファイル (touches) を付与し、
  循環・未定義依存を検証し、物理衝突（同一ファイルを触る組）を洗い出す。並列実装パイプラインの工程4。
  「依存を整理」「DAG を作る」「plan.dag.json」「tasks を並列化前提で構造化」といった依頼で起動する。
---

# dependency-mapper（工程4：依存関係の整理）

`tasks.md` を「並列実装できる形」に構造化するスキル。出力 `plan.dag.json` が
次工程 `wave-scheduler` の入力になる。ここが甘いと後段のマージ地獄に直結するので、
**機械処理と意味理解を明確に分業**する。

## 依存の 2 種類（最重要概念）

| 種類 | 定義 | 誰が決めるか | DAG での扱い |
|---|---|---|---|
| **論理依存** | B が A の成果物（型・API 契約・スキーマ）に依存 | **Claude（意味理解）** | `depends_on` の有向辺 |
| **物理依存** | 同一ファイル/モジュールを触る＝論理独立でも衝突しうる | **スクリプト（機械的）** | 辺にしない。`touches` に記録し、scheduler が排他制約として処理 |

物理依存は方向を持たない排他関係なので `depends_on` には入れない。
その分離こそがこのスキルの設計上の肝。

## 手順

### 1. draft を機械生成（取れるものだけ取る）

```bash
python3 .claude/skills/dependency-mapper/scripts/parse_tasks.py \
  --tasks   specs/<story-id>/tasks.md \
  --impact  specs/<story-id>/impact.md \
  --out     specs/<story-id>/plan.dag.json \
  --story-id <story-id>
```

- タスク ID / タイトル / `[P]` / 行内ファイルパスを抽出し、`touches` を初期化。
- `impact.md`（Explore fan-out の出力）があれば task→files を補完・上書き。
- この時点で `depends_on` は **全て空**。

### 2. 論理依存を Claude が付与（このスキルの中核作業）

`spec.md` と `plan.md` を読み、各タスクの `depends_on` を埋める。判断基準:

- タスク B の実装が、タスク A が定義する **型・関数シグネチャ・API 契約・DB スキーマ・
  共有インターフェース** を必要とするか？ → する なら `B.depends_on += [A]`
- 単に「同じファイルを触る」だけなら **論理依存ではない**（→ touches に任せる、辺は張らない）。
- 迷ったら spec の受け入れ条件（EARS 記法）を根拠に判断し、`notes` に理由を一言残す。

同時に `touches` の取りこぼしも補正する（パーサはヒューリスティックなので、
「本文には書かれていないが実際に触るファイル」を spec/plan から足す）。

**編集判断は必ず明示する**：何をどの根拠で depends_on に入れ、何を意図的に入れなかったか
（＝物理衝突として scheduler に委ねたか）を人間に説明してからファイルを書く。

### 3. 検証（scheduler に渡す前の門番）

```bash
python3 .claude/skills/dependency-mapper/scripts/validate_dag.py specs/<story-id>/plan.dag.json
```

- **[HARD]** 循環依存 / 未定義依存 / 自己依存 → あれば exit 1。必ず直す。
- **[WARN]** `touches` 空のタスク → ファイル未特定は安全側で直列化されがち。可能なら埋める。
- **[物理衝突レポート]** 同一ファイルを触るペア一覧。これは**エラーではなく設計情報**——
  scheduler がこれらを別 wave に分離する。人間はここを数分眺めて依存漏れ/過剰だけ矯正すればよい
  （機械可読なのでレビューは速い＝コスパの高い人手ポイント）。

## 人のチェック（HOTL）

工程4 は元ガイドで `○`（推奨・軽いが効く）。DAG は機械可読なので目視は数分。
ここでの 1 回の矯正が工程6のマージ衝突を丸ごと防ぐ。重いゲートにはしない。

## 出力スキーマ（plan.dag.json / v1）

```json
{
  "story_id": "003-user-auth",
  "tasks": [
    {
      "id": "T004",
      "title": "AuthService を実装",
      "parallelizable_hint": false,
      "depends_on": ["T001", "T002", "T003"],
      "touches": ["src/services/auth_service.py", "src/models/user.py"],
      "notes": "User モデルの型と token スキーマに依存"
    }
  ]
}
```

## やってはいけないこと

- 物理依存を `depends_on` に混ぜない（方向のない排他を有向辺にすると DAG が歪む）。
- パーサ出力を無検証で scheduler に渡さない（必ず validate を通す）。
- 1 行 CSS 修正のような小変更に本フローを適用しない（PR 2 本以上に割れる規模が発動条件）。
