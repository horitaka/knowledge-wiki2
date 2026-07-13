---
type: overview
title: プロジェクト全体像
description: このwikiが対象とするプロジェクトの全体像・主要な入口ページへのポインタ
tags: []
timestamp: 2026-07-13T22:00:00+09:00
sources:
  - raw/transcripts/2026-07-06_定例会議.md
  - raw/decks/2026-07-08_進捗報告.md
  - raw/teams/2026-07-09_thread.md
status: active
confluence_id:
confluence_space:
---

## このwikiについて

このwikiは、会議議事録・進捗報告デッキ・Teamsチャット履歴を一次ソースとして、LLM（Claude Code）が継続的に構築・保守する組織内ナレッジベースである。設計の詳細は [docs/llm-wiki.md](../docs/llm-wiki.md) を参照。

**現在は少数ソースでの手動ingest検証（docs/llm-wiki.md §11-3）としてサンプルデータ（架空の在庫管理システム刷新プロジェクト）を投入した段階。**

## 主要entity

- [在庫管理システム刷新プロジェクト](entities/在庫管理システム刷新プロジェクト.md)
- [田中太郎](entities/田中太郎.md)（PM） / [佐藤花子](entities/佐藤花子.md)（テックリード） / [鈴木一郎](entities/鈴木一郎.md)（法務）
- [クラウドギア社](entities/クラウドギア社.md)（採用ベンダー） / [データフォース社](entities/データフォース社.md)（不採用）

## 主要concept

- [データ移行方針](concepts/データ移行方針.md)

## 直近の決定

- [2026-07-06 ベンダー選定: クラウドギア社採用](decisions/2026-07-06-ベンダー選定.md)

## 未解決の論点

- [エクスポート仕様確定遅延懸念](open_questions/2026-07-09-エクスポート仕様確定遅延懸念.md)
