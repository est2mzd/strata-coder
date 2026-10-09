# 可変数のAgentを使うqueuedモードの起動手順（v0.2）

> v0.3では[decision方式](decision-mode-ja.md)が既定です。このページのCursor Chat/MCP手順はsupervisionMode=legacy用です。Strata・コーディネーター・SSHの起動設定は両方式で共通です。

Cursor Agent数に固定値を設けず、共有キューで依頼を受け付けます。ただし待機キューの容量は有限で設定可能です。`single`モードは従来の１タスク方式です。複数Agentで使う場合は、全クライアントを`queued`にしてください。

## 1. gdx-spark：Strataを起動

既存のStrataを起動し、モデルを読み込みます。詳しくは[基本ガイドの1章](quickstart-ja.md)を参照してください。Strataは`127.0.0.1:8080`で応答する前提です。既に起動中なら重ねて起動しません。

## 2. gdx-spark：共有コーディネーターを１つ起動

**別のSSHターミナル**でStrata-Coderリポジトリへ移動します。以下は配置例です。

```sh
cd ~/work/llm/strata-coder
python3 tools/coordinator.py --state ~/.local/state/strata-coder-coordinator --port 8091 --worker-limit 4 --inference-limit 1 --queue-capacity 1000 --per-owner 100
```

起動したターミナルは残します。`Coordinator ready`が表示されたら準備完了です。

- `worker-limit`：全クライアントを通じたWorkerタスクの同時実行枠。
- `inference-limit`：Strataへの同時推論要求数。最初は1。Strataの対応能力を測ってから増やします。
- `queue-capacity`：受付済み・処理中の仕事の総上限。エージェント数の固定値ではありません。
- `per-owner`：同じ依頼元ラベルが占有できる受付件数。

状態ディレクトリにSQLiteのタスク記録と認証用`token`ファイルが作られます。**起動メッセージにはトークンの値を表示しません。** 接続するPCの利用者へ、このファイルの内容を安全な方法で渡します。トークンは管理権限を持つ秘密情報で、ChatやGitに貼りません。この初期版は同一利用者の信頼できるPC群向けで、異なる利用者間の権限分離はありません。

同じStrataに対して複数コーディネーターを起動すると、推論枠が別々に計算されます。**全PCが同じ１つのコーディネーターを使ってください。** 別のアプリがStrataへ直接送る推論要求までは制御できません。

## 3. 手元PC：SSHトンネルを開く

パスワード接続の場合は、手元のターミナルで次を実行します。

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:18091:127.0.0.1:8091 gdx-spark
```

入力後に何も表示されなくても正常です。そのまま残します。queuedモードはコーディネーター経由で推論するので、手元PCから8080へ別トンネルを作る必要はありません。

## 4. 手元PC：Cursor拡張を設定

v0.2のVSIXを`Extensions: Install from VSIX`でインストールします。未公開の開発版の場合は、開発担当から渡されたVSIXを使用します。公開mainの古い成果物ではqueuedモードを使えません。

Cursorの**User Settings**で次を設定します。

```json
{
  "strataCoder.executionMode": "queued",
  "strataCoder.connectionMode": "direct",
  "strataCoder.coordinatorUrl": "http://127.0.0.1:18091/v1",
  "strataCoder.workerConcurrency": 2,
  "strataCoder.testConcurrency": 1,
  "strataCoder.pythonPath": "python3"
}
```

Pythonコマンドが`python`の環境ではPython Pathも変更します。`workerConcurrency`はそのワークスペースのWorker枠、`testConcurrency`はそのワークスペースのテスト枠です。複数ワークスペースを開く場合は各々に枠があるため、PC全体の負荷も考えて設定します。

1. コマンドパレットで`Strata-Coder: Set Coordinator Token`を実行し、2で作られたトークンを入力。
2. `Strata-Coder: Register / Reconnect`を実行。
3. `Strata-Coder: Check Connection`を実行。
4. `execution_mode: queued`、モデル名とキュー設定が表示されることを確認。

Strata自体にAPIキーを設定している場合は、**gdx-sparkでコーディネーターを起動する環境**に`STRATA_API_KEY`を設定します。queuedモードの推論モデル設定もコーディネーターの`--model`で行います。拡張のModel／Set API Keyはsingleモード用です。

SSH鍵認証が動く場合は、Connection Modeを`ssh`、Ssh Hostを`gdx-spark`、Coordinator Portを`8091`にすると拡張がトンネルを作ります。手動トンネルは不要ですが、Coordinator Tokenはどちらの方式でも必要です。

## 5. Agentへ仕事を依頼

[テスト用指示集](test-prompts-ja.md)を使います。各Agentに異なる`owner`、各依頼に異なる`request_key`を付けます。受付応答を受け取れず同じ依頼を再送するときだけ、同じキーを使います。

拡張のステータスバーには最近のタスクの実行中・待機中・レビュー待ち件数が表示されます。`Strata-Coder: Show Task Status`でタスクIDを確認できます。この進捗監視はプログラムで行い、Cursorモデルを呼びません。

**完了通知はCursor Agentを自動で再開しません。** 応答待ちのMCP呼び出しが終了した場合はその結果を受け取れますが、既にChatが終了している場合は「タスクID…の結果を取得して」と依頼してください。短い間隔で同じ状態を繰り返し問い合わせる運用は避けます。

## 6. 変更の適用と再レビュー

Cursorが全差分とテスト証拠を確認し、`strata_apply`へ正確なハッシュを渡すと`apply_queued`になります。元repoへの適用はワークスペース単位で直列化されます。

- 元repoが変更済みなら、上書きせず監督Agentへ戻します。
- 基準コミットだけ変わり元repoがcleanなら、新しいworktreeでパッチ適用とテストを試し、新しいハッシュでレビュー待ちに戻します。
- 競合なら自動修正せず、元の証拠と作業ツリーを残します。
- 適用は未commitの変更を残します。続く変更の統合前に、利用者または監督が既存変更を扱う必要があります。勝手なcommit・stash・resetはしません。

## 7. 停止・障害時

queuedの仕事はコーディネーター再起動後も残ります。実行中にWorkerの定期応答が途絶えると、既定60秒のリース期限後にinterruptedとなります。副作用を二重実行しないよう、自動再実行しません。

推論のHTTP応答が不明になった場合、Strataがまだ計算中かもしれないため新しい推論の受付を停止します。gdx-sparkでStrataの状態を調べ、処理が終了していると確認してから次を実行します。

```sh
python3 tools/coordinator_admin.py --token-file ~/.local/state/strata-coder-coordinator/token reset-inference --confirm-inspected
```

状態だけを調べる場合：

```sh
python3 tools/coordinator_admin.py --token-file ~/.local/state/strata-coder-coordinator/token status
```

適用中断でそのworkspaceの適用が隔離された場合は、元repoと保存された成果を人が確認してから`reset-apply --workspace 対象workspaceID --confirm-inspected`を使用します。通常の再試行として自動実行しないでください。止まったタスクは自動的に再開せず、新しい契約で再依頼するか、保存された作業を引き取ります。
