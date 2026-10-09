# Evaluation protocol (no savings claimed yet)

**段階目標：Step 1＝1/10以下（10%）、Step 2＝1/50以下（2%）、Step 3＝1/100以下（1%）。現在はStep 1を実装・検証中です。品質を維持した実測で合格してから次へ進みます。**


Compare Cursor-only and Cursor+Strata on the same committed repository snapshots and equivalent instructions. Separate research, one-file fixes, multi-file changes and ambiguous tasks. Include failure cases. Use fresh sessions, identical Cursor model/settings and repeat runs in varied order.

Record for both arms: task ID, base SHA, task category, total Cursor input/output tokens (and cached categories separately if available), all retries/review/polling calls, actual billed cost if available, wall time, hidden-test outcome, reviewer-identified defects and whether the task completed. For the delegated arm also record Strata tokens, worker iterations and hardware load. Worker usage is never substituted for Cursor usage.

Evaluate only accepted fixes with equivalent correctness. Compare aggregate cost per successful task as well as task-level distributions; failed delegations and supervisor takeover remain in the denominator. Review patches without knowing which arm produced them where practical. Tune delegation using failures, not merely model self-confidence.

Initial acceptance gates: no lost user changes, no out-of-scope writes through worker tools, failed tests block apply, reviewed hash/base conflicts reject apply, cancellation stops further tool execution, useful research citations, and a real Cursor Chat invocation on each supported host. No numerical token-saving target is a verified result until measured.

## 実測準備状況（2026-10-09）

評価用の公式Cursor CLI（2026.10.01-e373342）を隔離した作業フォルダーへ取得しました。初回は未ログインでしたが、利用者による認証後に実測を開始しました。結果は[token-evaluation-ja.md](token-evaluation-ja.md)に記録します。

小規模な予備評価として、ページ分割、区間の統合、有効期限付きキャッシュの3課題を用意しました。Cursor単独／Strata-Coder併用の2条件を各2回、計12実行とし、2回目は条件の実行順を逆転させます。両条件の初期ソースと可視テストを一致させ、正解判定コードは評価側に置きます。これは小さなPython修正の予備評価で、複雑な実プロジェクト全体に一般化しません。

準備の再現方法（既存の結果を上書きしないよう空の出力先を指定）：

```sh
python3 tools/prepare_token_evaluation.py --output /tmp/strata-token-evaluation --repeats 2
```

`runs.json`に課題・条件・プロンプト・基準commit・初期ソースのSHA-256を記録します。`checks.json`は評価側で実行する追加の正解判定です。この準備コマンドはLLMを呼ばず、トークンも測定しません。

認証後、同一モデル・同一設定・新規セッションで実行し、セッション別のCursor使用量が取得可能か確認します。CLIの結果に使用量が含まれない場合は、Cursor側の利用明細などで各実行との対応を確認する必要があります。表示された文章だけを数えて総トークンに代用しません。取得できない項目はnullとし、削減率を算出しません。CLI比較はIDE Chatそのものの比較と区別して報告します。


## 実行と集計

準備したfixtureとは別の空フォルダーにログを保存します。コーディネーターとSSHトンネルを先に起動し、token-fileには共有トークンを保存したローカルファイルを指定してください。`--cli`には認証済みCursor CLIの絶対パスを指定します。

```sh
python3 tools/run_token_evaluation.py --fixtures /tmp/strata-token-evaluation --output /tmp/strata-token-results --cli /absolute/path/to/cursor-agent --coordinator-url http://127.0.0.1:18091/v1 --token-file /absolute/private/coordinator-token --model composer-2.5
python3 tools/summarize_token_evaluation.py /tmp/strata-token-results/results.json
```

実行スクリプトは専用fixtureの`.cursor/mcp.json`を設定し、CLIをsandbox有効・ツール許可付きで起動します。既存の業務repoをfixtureに指定しないでください。各実行に300秒の上限があり、失敗実行を結果から除きません。結果のusageが欠ける場合、総量・削減率をnullにします。生ログにはローカルパスや会話が含まれるため、そのまま公開しません。

トークン総数は入力＋出力＋キャッシュ読込＋キャッシュ書込です。これは[Cursor公式のTokenUsage定義](https://cursor.com/docs/sdk/typescript)に合わせた集計であり、キャッシュを含むトークン数と課金額は同じではありません。reasoningはoutputの内数なので重ねて加算しません。


## 新しい合格条件

利用者の要求により、品質を維持したCursor総トークン比率0.01以下を必須とします。[新設計](architecture.md)を参照してください。旧構成の評価は12実行中10実行完了後、11実行目で停止しました。[途中結果](token-evaluation-ja.md)は完了済み5組の比較であり、全計画の完了評価ではありません。
