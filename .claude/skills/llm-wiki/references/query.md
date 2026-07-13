# query ワークフロー

wikiの内容について問い合わせを受けたときの手順。

## 手順

1. `wiki/index.md` を読み、質問に関連しそうなページ（entity/concept/decision/summary/open_question）を特定する
   - 現状indexは手動運用の一覧ページ。規模が数百ページを超えたら `scripts/search.py` によるハイブリッド検索を検討する（docs/llm-wiki.md §10）
2. 該当ページを開き、内容を読む。関連ページへのリンクを辿って必要な範囲まで探索する
3. 出典（`sources` frontmatter）付きで回答を統合する。「〇〇によると」ではなく、どのraw sourceに基づくかを明示する
4. 複数ページで矛盾する情報が見つかった場合は、回答にその旨を明記し、`wiki/open_questions/` に矛盾として積む（lintを待たずにその場で記録してよい）

## wikiへの還元

質問への回答が既存ページに反映されていない新しい統合（複数ソースを跨いだ洞察）を含む場合は、wikiへ還元してよい。

- 対象は entity / concept / decision のいずれか（圧縮原則を満たす場合のみ）
- 単なる言い換え・焼き直しのページは作らない
- 還元した場合は `wiki/log.md` に追記する
