# テスト用の指示：可変数のCursorエージェントから委譲する

> v0.3では[decision方式](decision-mode-ja.md)が既定です。このページのCursor Chat/MCP手順はsupervisionMode=legacy用です。Strata・コーディネーター・SSHの起動設定は両方式で共通です。

これは実機でCursorに入力するテスト指示です。**エージェント数Nは自由に変更**します。Nはモデル同時実行数ではありません。まずN=2から始め、必要に応じて増やしてください。実装は共有キューを使う`queued`モードです。[起動手順](multi-agent-setup-ja.md)を先に完了してください。

各エージェントに渡す`owner`は識別用ラベルです。認証情報ではありません。APIキー／SSHパスワードは指示へ入れません。未実装の自動Agent再開に依存しないよう、完了通知後は必要なら利用者が結果取得を依頼します。

## 1. コーディネーターの確認【１つのChatで実施】

> Strata-Coderのstrata_healthで接続を確認してください。execution_modeがqueuedであること、worker_limitとモデル名を報告してください。inference_blockedが空でなければ新しい仕事を出さず理由を報告してください。ファイルの変更はしないでください。

## 2. 可変数の調査依頼【各Agentへ同じ形式で渡す】

`<RUN>`を今回の実行名、`<I>`を各Agentの番号、`<FILE>`を存在する小さなソースファイルに置き換えます。例：`RUN=trial-01`、`I=1`。番号を変えた指示をN個のAgentに配ります。エージェントの作成自体はCursorで行ってください。

> Strata-Coderに次の調査を委譲してください。ownerは「<RUN>-agent-<I>」、request_keyは「<RUN>-research-<I>」です。researchモード、max_steps=4で、<FILE>の役割・主要な関数・呼び出し元を調べ、根拠のファイル名を添えた短い報告を求めてください。編集もテスト実行も禁止です。タスクIDを記録してください。受付応答が不明になった場合だけ、同じ条件と同じrequest_keyで再送してください。待機中の状態を何度も問い合わせず、長時間かかる場合はタスクIDを報告して待ってください。

完了通知の後、必要なら各Agentへ：

> 先ほどのタスクIDについてstrata_summaryを取得してください。調査結果を確認し、判断に必要な箇所だけstrata_evidenceで追加取得してください。全ログは読まないでください。結果と不明点を短く報告してください。

期待する結果：N件が個別のタスクIDで受け付けられます。空き枠がない仕事はqueuedになります。受付上限を超えた場合は明確な容量エラーになります。Workerと推論の同時実行数はそれぞれ設定値以内です。

## 3. 同じ依頼の再送【重複実行防止】

> 先ほど送ったstrata_submitと完全に同じobjective、owner、request_key、その他の引数で再送してください。返されたタスクIDが元と一致し、deduplicated=trueになるか確認してください。新しいrequest_keyは作らないでください。

同じキーで違う内容を送るとエラーになるのが正常です。新しい仕事には新しいキーを使います。

## 4. 編集と証拠レビュー【お試しrepoで実施】

対象のファイル名、テストID、具体的なバグを置き換えて使います。先にGitの変更がないことを確認します。

> Strata-Coderへこのバグの修正を委譲してください：<具体的なバグ>。ownerは「<RUN>-editor-1」、request_keyは「<RUN>-edit-1」。編集範囲は<対象ファイル>のみ、受入条件は<観測可能な条件>、test_idsは<登録済みテストID>です。Strata内部で調査・編集・テストを行わせてください。あなたは結果の要約、全変更差分、最終テスト証拠を確認してください。まだstrata_applyは呼ばず、問題点と採用可否を報告してください。

レビュー後：

> レビュー済みの変更を採用してください。確認した正確なpatch_sha256でstrata_applyを呼び、apply_queuedは適用完了とは扱わないでください。結果がappliedか確認してください。新しい基準コミットへの再適用でreview_readyに戻った場合は、新しい差分とテストをレビューしてから判断してください。commitとpushはしないでください。

## 5. 取消と障害【テスト用環境だけで実施】

> 待機中のタスク<タスクID>をstrata_cancelで取り消してください。他のAgentのタスクは取り消さないでください。cancelledになったことを一度確認してください。

Worker切断テストはお試しrepoで行います。実行中にMCPを切断し、リース期限後にinterruptedとなり自動再実行されないことを確認します。適用中断は結果不明としてそのworkspaceの後続適用を停止します。通常の作業repoで無理に障害を起こさないでください。

## 6. Cursorトークン削減の比較

> 同じ基準コミット・同じ課題・同じCursorモデル・同じAgent数Nで、Cursorのみの場合とStrata-Coderへ委譲する場合を比較してください。計測に使えるCursor側の利用量が取得できなければ「未計測」としてください。StrataのusageをCursorトークンとして扱わないでください。指示・状態取得・証拠レビュー・再指示・失敗後の引取りをすべて含むCursor総トークンと、成功率・残った不具合・所要時間を記録してください。個々のタスクに加え、N個全体の合計を比較してください。

## 自動テスト用コマンド【CursorのChatではなくターミナル】

Strata-Coderリポジトリのルートで実行します。

```sh
python3 -m unittest discover -s tests -v
node tests/extension.test.js
```

Agent数を変える合成負荷テスト：

```sh
python3 tools/load_test.py --agents 7 --workers 3 --inference 1 --tasks-per-agent 2
python3 tools/load_test.py --agents 73 --workers 4 --inference 2 --tasks-per-agent 2
```

`completed`が`tasks`と一致し、`peak_inference`が`inference_limit`以下、`errors`が空なら成功です。これは**偽モデルによるキュー／実行枠の試験**であり、実モデルの品質・速度やCursorトークンの測定ではありません。数値は引数で変更できます。

## 深度選択のテスト

> strata_healthでdefault_depthとreasoning_supportを確認してください。今回はautoでhello.pyの調査を委譲し、reasoning_effortと短いdepth_reasonを難しさに応じて指定してください。owner="depth-trial"、request_key="depth-auto-1"、max_steps=4、max_output_tokens=2048を使ってください。結果のdepth_selectionと選択理由を報告してください。

続いて別の依頼として：

> 今回はhigh固定で同じファイルを調査してください。depth="high"、owner="depth-trial"、request_key="depth-high-1"、max_steps=4、max_output_tokens=4096で委譲し、選択値を確認してください。結果が不十分でも自動再委譲せず理由を報告してください。

これは設定の伝達確認です。回答品質の差やCursorトークン削減率を証明するテストではありません。
