---
name: wave-scheduler
description: >
  plan.dag.json（依存 DAG）を Agent teams で実行できる形に変換する。2つのモードを持つ：
  モードA（既定）＝トポロジカルソート＋ファイル重複検出で discrete な wave（層）に分割し、
  wave境界は人間/leadが明示的に進める。モードB＝ファイル重複を疑似 depends_on エッジに
  変換し、1本のDAGとして一括登録してAgent teamsのタスク依存機構に実行を委ねる。
  teammate 割り当て表 (waves.md)・機械可読 (waves.json)・agent teams 引き渡し用プロンプト
  (handoff.md) を出力する。並列実装パイプラインの工程5。
  「実装順を計画」「wave に分ける」「並列スケジュール」「teammate 割り当て」「DAGを一括登録」
  といった依頼で起動する。
---

# wave-scheduler（工程5：実装順の計画）

`dependency-mapper` が出した DAG を、agent teams + worktree で回せる形に変換する。
このスキルが agent teams の最大の失敗要因＝**マージ衝突を設計段階で潰す**。

**2つのモードがあり、`--mode` で選ぶ（既定は `wave`）：**

|                       | モードA（`--mode wave`・既定）             | モードB（`--mode dag`）                                 |
| --------------------- | ------------------------------------------ | ------------------------------------------------------- |
| 出力の形              | discrete な wave（層）に分割               | 論理依存＋疑似依存を合成した1本のDAG                    |
| Agent teamsへの渡し方 | wave単位で少しずつ登録・毎回teammate spawn | 全タスクを一括でTaskCreate、teammateは自己組織的にclaim |
| wave間/タスク間の同期 | 人間/leadが明示的に次を流す                | Agent teamsのタスク依存機構に委ねる                     |
| HOTLチェックポイント  | wave境界（discrete、分かりやすい）         | 登録前のDAGレビュー1回＋hookによるイベント駆動監視      |
| 向くケース            | まず安全に始めたい・PoC段階                | Agent teamsの安定性を確認済み・並列度を最大化したい     |

どちらも **入力（`dependency-mapper` が出す `depends_on` + `touches`）は共通で必須**。
`tasks.md` をそのまま Agent teams に渡す、という簡略化はどちらのモードでも取れない
（ファイル重複を検出する仕組みが Agent teams 自体には無いため）。

## モードA: wave の定義（不変条件）

1 つの wave に入れてよいのは、次を **全て満たす** タスク群:

1. **論理依存を満たす**：`depends_on` が全て前の wave までに完了している
2. **物理的に非重複**：wave 内のどの 2 タスクも共通の `touches` ファイルを持たない
3. **幅上限内**：wave のタスク数 ≤ teammate 上限（既定 5、**推奨 3〜5**）

→ wave 内は安全に並列、wave 間は直列。物理依存はここで直列化される。

### アルゴリズム（貪欲リストスケジューリング）

1. `ready` = 依存が全解決済みの未スケジュールタスク
2. 優先度 = **下流に連なるタスク数**（クリティカルパス上のものを先に流し、全体段数を短縮）
3. `ready` を優先度順に見て、**幅上限**と**ファイル非重複**を満たす限り同一 wave に詰める
4. 詰め切れなかったタスクは次 wave へ（＝物理衝突・幅上限による直列化）

## モードB: DAG一括登録の定義

wave のような discrete な区切りを作らず、`touches` の重複を **疑似 `depends_on` エッジ**に
変換してから、論理依存と合成した1本のDAGをそのまま登録する。

### アルゴリズム（優先度考慮トポロジカル順 ＋ ファイル重複の鎖状直列化）

1. 論理依存（`depends_on`）だけを見て、優先度（下流に連なるタスク数）を考慮したトポロジカル
   順 `order` を1本作る（Kahn法。同点はID昇順で安定化）
2. `order` を先頭から見て、同じファイルに触れるタスクは「直前にそのファイルを触ったタスク」
   への疑似依存エッジを1本だけ追加する（all-pairsではなく鎖状に直列化。3タスクが同じ
   ファイルを触るなら2エッジで足りる）
3. 疑似エッジは常に `order` に沿った「前→後」方向にしか張らないため、合成後も循環は
   生じない（構造的に保証される）
4. 論理依存＋疑似依存を合成した `depends_on` を持つタスク一覧が最終出力

wave分割やteammate上限による幅の強制は行わない。代わりに「理論上の最大並列幅／段数」を
参考情報として算出し、spawnするteammate数の目安にする。

## 実行

**モードA（既定）:**

```bash
python3 .claude/skills/wave-scheduler/scripts/schedule_waves.py \
  specs/<story-id>/plan.dag.json \
  --mode wave \
  --max-teammates 3 \
  --out-md      specs/<story-id>/waves.md \
  --out-json    specs/<story-id>/waves.json \
  --out-prompts specs/<story-id>/handoff.md
```

**モードB:**

```bash
python3 .claude/skills/wave-scheduler/scripts/schedule_waves.py \
  specs/<story-id>/plan.dag.json \
  --mode dag \
  --max-teammates 3 \
  --out-md      specs/<story-id>/dag-plan.md \
  --out-json    specs/<story-id>/dag-plan.json \
  --out-prompts specs/<story-id>/handoff.md
```

- `--max-teammates`：モードAでは wave あたりの並列上限（強制）。モードBでは spawn する
  teammate 数の目安（強制ではない）。**まず 3 で PoC**、安定したら 5 まで。
  トークンは teammate 数に線形に増える点に注意（実装=Sonnet / テスト・レビュー=Haiku へ
  ルーティングしてコスト最適化）。
- 入力 DAG は事前に `validate_dag.py` を通っている前提。scheduler 自身も循環・未定義依存は
  弾くが、物理衝突レポートは dependency-mapper 側で見ておくこと。
- `--mode` を省略すると `wave`（モードA）になる。

## 出力の読み方

**モードA（`waves.md`）:**

- **サマリ**：wave 数（直列段数）・最大並列幅・「物理制約で後ろ倒しになったタスク数」。
  最後の数字が **このスキルが防いだマージ衝突の量**の目安。
- **Wave N のテーブル**：`teammate-k` ↔ タスクの割り当て表。そのまま agent teams の起動指示になる。
- **物理制約で直列化されたタスク**：論理上はもっと早く着手できたが、ファイル重複 or 幅上限で
  後ろ倒しにしたもの。ここが「設計段階での衝突回避」の実績。

**モードB（`dag-plan.md`）:**

- **サマリ**：論理依存エッジ数・疑似依存エッジ数（＝ファイル重複から追加された分）・
  参考情報としての理論上の最大並列幅／段数。
- **タスク一覧**：登録順（優先度考慮済みトポロジカル順）に、各タスクの `depends_on`
  （論理＋疑似の合成後）と、そのうち疑似分がどれかを表示。
- **ファイル重複から追加された疑似依存**：ここが唯一の人間レビューポイント。
  「本当にこの順で直列化してよいか」を確認する（モードAの「物理制約で直列化されたタスク」に相当）。

**共通（`handoff.md`）:**

- モードA：wave ごとに区切られた指示文。「このwaveのタスクを TaskCreate で登録して
  teammate を spawn しろ」という内容で、次wave分は前wave完了確認後にあらためて貼る。
- モードB：全タスクを一度に登録する単一の指示文。`depends_on` を明記した状態で
  TaskCreate に渡し、あとは teammate が自己組織的に claim する前提。

## 人のチェック（HOTL）＝攻め具合の判断点

工程5 は元ガイドで `○`（推奨）。ここが **並列度とコスト/衝突リスクのトレードオフの承認点**。
モードA/Bどちらで進めるかもこの段階で決める。

- 並列幅を上げる（teammate 増）→ 速いがトークン増・調整コスト増。
- モードAでwave 数が多い（直列段数が長い）→ 依存 or 物理衝突が重い。DAG を見直す価値があるサイン。
- モードBで疑似依存エッジが多い → ファイル重複が多い設計になっている可能性。タスク分解
  （工程3）に戻って粒度を見直す価値がある。
- `waves.md` / `dag-plan.md` を数分眺め、攻めるか安全側かを人間が決める。承認後、工程6（並列実装）へ。

## モードA/Bの選び方（Agent teamsへの引き渡し方針）

以下は **どちらのモードを選んでも共通して成り立つ前提**：

1. **外部から一括登録する公式インターフェースがない**：agent teams のタスクは lead が
   `TaskCreate` を呼んで登録するものであり、スクリプトが `~/.claude/tasks/{team-name}/` に
   直接書き込む経路はサポートされていない。どちらのモードでも「登録」は lead への
   自然言語プロンプト（`handoff.md`）という形を取る。
2. **物理衝突検出は agent teams に存在しない**：公式ドキュメントでもファイル競合回避は
   「teammate ごとに担当ファイルを分ける」という人間向けのベストプラクティスとして
   書かれているだけで、自動検出の仕組みはない。`touches` の重複判定はこのスキルにしかなく、
   モードBでも省略できない（疑似エッジの計算に使っている）。

その上で、モードAとモードBの違いは **「タスク完了マーク漏れリスクをどう扱うか」** に集約される。
公式 Limitations は _"Task status can lag: teammates sometimes fail to mark tasks as
completed, which blocks dependent tasks"_ と明記しており、完了マークの付け忘れで下流タスクが
永久にブロックされうる。

- **モードA**はこのリスクを、discrete な wave 境界を人間が握ることで回避する。安全だが、
  wave の切れ目ごとに人間が介入する分、フル自動化はできない。
- **モードB**はこのリスクを受け入れる代わりに、Agent teams のタスク依存機構をフル活用して
  wave 単位の手動ハンドオフを無くす。**`TeammateIdle` / `TaskCompleted` hook による
  代替ガードレールとセットで使うことが前提**（下記「工程6への引き継ぎ」参照）。

**推奨**：最初の PoC はモードAで進め、Agent teams のタスク依存の安定性（完了マーク漏れの
発生頻度、hookでの補足の効きやすさ）を実運用で確認できてから、モードBへの移行を検討する。

## 工程6 への引き継ぎ

**モードA:**

1. `handoff.md` から **その時点で流してよい wave の1ブロックだけ** を lead に貼り付ける
   （複数wave分を一度に貼らない）。
2. lead が `TaskCreate` でそのwave分のタスクを登録し、`waves.md` の割り当てに従って
   teammate を spawn する。各 teammate は「実装 → テスト → green → PR」を回す。
3. **wave の切れ目だけが監視ポイント**（逐一承認しない＝HOTL）。ただし完了確認は
   teammate の自己申告だけに頼らず、人間が実際の成果物（テスト結果・PR）を確認してから
   次waveの `handoff.md` ブロックを貼る。

**モードB:**

1. `handoff.md`（全タスク分の単一プロンプト）を lead に貼り付ける。lead が全タスクを
   `depends_on` 付きで `TaskCreate` し、目安の人数の teammate を spawn する。
2. teammate は共有タスクリストから依存解決済みのタスクを自己組織的に claim して進める。
3. **`TeammateIdle` hook**：teammate がアイドルになる直前に「claim中のタスクが実は完了して
   いるのに未マークでないか」を検査し、未完了なら exit code 2 で作業を続けさせる。
4. **`TaskCompleted` hook**：完了が主張されたタイミングで、テストが実際に green かなど
   機械的に確認し、満たさなければ完了をブロックする。
5. 人間は「wave の切れ目」ではなく、hookが拾えない異常（誰もタスクを取らない、暴走等）が
   無いかを `/tasks` で随時確認する。

**共通:** 規模が上がったら `waves.json` / `dag-plan.json` を headless `claude -p` の driver に
食わせて `worktree × プロセス` を回す運用に切り替えてもよい。この場合もモードAなら wave境界の
同期は driver 側のスクリプトが明示的に制御する。

## やってはいけないこと

- 検証前の DAG をそのまま流さない（循環があると停止する。両モード共通）。
- teammate 上限を無闇に上げない（3〜5 推奨。experimental 段階では小さく始めて widen）。
- **モードA**で、wave の切れ目以外で並列実行中の teammate に逐一介入しない（並列の意味が消える）。
- **モードA**で、wave 間の同期を agent teams のタスク依存（`depends_on`）機構に丸投げしない。
  `handoff.md` は必ず1wave分ずつ貼る。
- **モードB**を `TeammateIdle` / `TaskCompleted` hook なしで運用しない。完了マーク漏れによる
  永久ブロックを検知する手段が無くなる。
