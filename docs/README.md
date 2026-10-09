# Strata-Coder ドキュメント

## 評価・試行錯誤

1. [試行錯誤の記録](trial-history-ja.md)：v0.2から指令短縮まで。成功と失敗を分けた一覧、原因、次の実験への反映。
2. [方針委譲方式の比較実験](policy-experiment-ja.md)：同じ複数ファイルの作業をCursor単独とCursor方針＋Strata実行で比較。仮説・手法・結果・再現方法。3試行とも事前調査で停止し、効果は未確認。
3. [79.85%削減を確認したv0.3試験](decision-verification-ja.md)：成功した小課題1組と、その限界。
4. [v0.2のトークン比較](token-evaluation-ja.md)：共有キューだけでは使用量が増えた結果。
5. [段階的な情報取得の追加実装](progressive-context-ja.md)：短縮指令・Python AST・Serenaから参考にした考え方。
6. [自動テストの履歴](verification.md)：機能テストと実LLM評価の違い。

## 導入・運用

- [判断方式の導入と評価コマンド](decision-mode-ja.md)
- [導入の概要](quickstart-ja.md)
- [Strata・共有コーディネーターの起動](multi-agent-setup-ja.md)
- [アーキテクチャ](architecture.md)

総トークンの目標はStep 1＝10%以下、Step 2＝2%以下、Step 3＝1%以下です。品質を満たさない試行は、トークン比が低くても不合格です。料金・表示文字数・Strata使用量をCursor総トークンと混同しません。
