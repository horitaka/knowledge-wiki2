# Index

wiki全体のルーティング入口。`query` 操作はまずこのページから該当ページを探す。ingest操作のたびに新規/更新ページをここへ反映すること。

規模が数百ページを超えたらハイブリッド検索（`scripts/search.py`）の導入を検討する（docs/llm-wiki.md §10）。

## entities

（まだページなし。ingest後、`title` — `description` の形式で1行ずつ追加する）

## concepts

（まだページなし）

## decisions

（まだページなし）

## open_questions

（まだページなし）

## summaries

（まだページなし。summaryは点数が多くなるため、日付降順で直近N件のみ載せ、古いものは省略してよい）
