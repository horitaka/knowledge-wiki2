# 命名規約・名寄せ

## ファイル名

- `wiki/entities/`, `wiki/concepts/`, `wiki/decisions/`, `wiki/open_questions/` … `<正規化されたtitle>.md`
  - 例: `wiki/entities/田中太郎.md`, `wiki/decisions/2026-07-10-移行方式決定.md`
  - decisionは日付を先頭に付け、同名決定の衝突と時系列把握を両立させる: `YYYY-MM-DD-<内容を表す短い名前>.md`
- `wiki/summaries/` … `<ソースの日付>-<ソース種別>-<短い説明>.md`
  - 例: `2026-07-10-meeting-定例.md`, `2026-07-11-teams-thread-042.md`
- ファイル名にスペースは使わず、日本語はそのまま使ってよい（このリポジトリは日本語前提）。記号は `-` と `_` のみ

## Confluenceページタイトルとの対応

ローカルのファイル名（拡張子除く）を、そのままConfluenceページタイトルとして使う。`title` frontmatterと一致させること（ズレるとpublish時の突き合わせが分かりにくくなる）。

## 相互リンク

wiki内の相互参照は `[[相対パスまたはtitle]]` のwikilink風記法、もしくは標準markdownリンク `[表示名](../entities/田中太郎.md)` のどちらでもよいが、**リポジトリ内では標準markdownリンクに統一する**（Confluence publish時にリンク解決がしやすいため）。

## 日本語の名寄せ（entity名の正規化）

人名・プロジェクト名は表記ゆれが必ず発生する（例:「田中さん」「田中」「田中太郎」「Tanaka」）。ingest時に以下の手順で正規化する。

1. `wiki/entities/` 内に近い名前の既存ページがないか確認する（表記ゆれ・敬称・部分一致を考慮）
2. 既存entityが見つかれば、そのentityへ追記する（新規ファイルを作らない）
3. 見つからない場合のみ新規entityを作成し、`title` はフルネーム（人物なら姓名、判明していれば）を正とする
4. 敬称（さん/氏/様）はtitleに含めない。本文中の言及ではそのまま使ってよい
5. Teams CSVの `author_email` が使える場合は、メールアドレスを名寄せの一次キーとして優先する（表記ゆれよりメールの方が信頼できる）
6. 迷った場合は新規作成せず `wiki/open_questions/` に「〇〇と△△は同一人物か要確認」として積む
