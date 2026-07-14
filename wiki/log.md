# Log

ingest / lint / publish の監査ログ。新しいエントリを末尾に追記する（降順ソートはしない。git blameで十分追跡できるため）。

## 記録フォーマット

```
## YYYY-MM-DD HH:MM 操作種別（ingest|lint|publish）
- 対象: raw/... または対象ページ一覧
- 内容: 何を行ったか（触れたページ、作成/更新/status変更の別）
- 備考: 判断に迷った点、次に確認すべきこと
```

---

