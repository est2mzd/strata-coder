# RTX4060 / RTX3090からSparkを使う

Cursorで開いたリポジトリのPCにStrata-Coderをインストールします。推論はSpark、ファイル操作とテストはリポジトリのPCで実行します。Remote SSHで開いている場合は、そのリモートホストが実行場所です。

1. Cursorで `Extensions: Install from VSIX` を実行して配布VSIXを選択。
2. Python 3.10以上・Git・SSHを作業PCに用意。
3. 既存の変更を自分でcommit/stashし、Gitのルートを開く。
4. SSH鍵認証なら設定 `strataCoder.sshHost` を既存SSHホスト名にする。
5. パスワード認証なら下記トンネルを手動で開き、direct接続にする。
6. `Strata-Coder: Check Connection` で接続確認。
7. Agent Chatで「Strata-Coderに調査を委譲して。方針決定と最終レビューはあなたが担当して」と依頼。

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:8080 gdx-spark
```

```json
{
  "strataCoder.connectionMode": "direct",
  "strataCoder.baseUrl": "http://127.0.0.1:18080/v1"
}
```

設定変更後は、タスクが終了してから `Strata-Coder: Register / Reconnect` を実行してください。パスワードは端末にのみ入力します。モデル名は空欄なら実際にロードされた１モデルを選びます。

`strataCoder.testCommands` はIDからコマンド引数配列への対応です。初期値は空で、勝手にテストコマンドは実行しません。信頼できるリポジトリ向けのコマンドをユーザー設定に登録してください。

まず小さな調査を試し、次に１ファイル修正で差分レビューまで試します。v0.1では既存変更のあるrepoやsubmoduleは対象外です。Cursor上の実機動作・トークン削減率は別途検証が必要です。
