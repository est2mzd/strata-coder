# はじめてのStrata-Coder導入ガイド

**v0.3の既定値はdecision方式です。新規導入は[短い判断資料と指令で使う](decision-mode-ja.md)を参照してください。以下はsupervisionMode=legacyを選んだ場合のv0.2接続手順です。**

SSHの接続名が未設定の場合は、先に2-4のSSH設定を行ってください。

このガイドでは、**gdx-sparkで動いているStrataを、手元のPCのCursorから利用する**ところまで設定します。最初はパスワードでSSH接続できれば進められる方法を説明します。

Strata-Coderは開発初期版です。LinuxでのWorker動作とSSH経由の推論は検証済みですが、Cursorの実画面での連携、Windows・macOSは検証中です。画面名が違ったり、エラーが出たりした場合は、末尾の「困ったとき」を確認してください。

このページは **v0.2の共有キュー（queuedモード）** を使う手順です。Agent数は固定せず、実際に動かすWorker数と推論数を別々に制限します。**v0.2はまだpushしていない開発版です。公開mainの古いVSIXでは、この手順を実行できません。**

## 最初に：何をどこへ入れるのか

- **Strata**：AIモデルを動かすサーバー。**gdx-spark側**で動かします。
- **Strata-Coderのコーディネーター**：依頼を共有キューで管理し、Strataへの推論数を制御します。**gdx-spark側**で１つ起動します。
- **Strata-CoderのCursor拡張**：**手元のPC側**へ入れます。Workerが手元のGitリポジトリのコピーで調査・編集・テストを実行します。
- **Cursor**：あなたが依頼を入力するエディタ。方針の決定と、Strataが作った変更のレビューを担当します。
- **SSHトンネル**：手元のPCからgdx-sparkのコーディネーターへつなぐ通路です。最初はターミナルで起動します。

手元のPCにAIモデルをダウンロードする必要はありません。Cursorの通常のモデルは引き続き使用します。Strataに詳しい調査や修正作業を任せることで、Cursorが読む情報量を減らす構成です。削減率はまだ測定していません。

**このガイドの範囲**：Cursorで手元のPCのフォルダーを開く場合です。Cursorの「Remote SSH」で別のPCのフォルダーを開く場合は実行場所が変わるので、まずこの構成で接続を確認してください。

---

## 1. Strataのセットアップ概要【gdx-spark側】

### 1-1. gdx-sparkへログインする

手元のPCでターミナルを開きます。

- Windows：スタートメニューから「PowerShell」を開く。
- macOS：「ターミナル」を開く。
- Linux：「端末」または「ターミナル」を開く。

次を入力してEnterを押します。

```sh
ssh gdx-spark
```

パスワードを求められたら、gdx-sparkへログインするパスワードを入力します。**入力中に文字が表示されなくても正常です。** パスワードをチャット欄や設定ファイルへ貼り付ける必要はありません。

初回は接続先の確認が表示される場合があります。接続先の管理者から確認したホスト鍵の指紋と一致することを確かめてから接続します。

接続できたら、**このターミナルはgdx-spark上で操作している状態**です。以降、このウィンドウを「起動用ターミナル」と呼びます。

### 1-2. Strata本体とモデルを用意する【導入済みなら次へ】

Strata-Coderとは別に、gdx-spark側に次の３つが必要です。

1. Strata本体のソースとサーバープログラム。
2. gdx-sparkのARM環境で動く推論エンジン。
3. ダウンロード・設定済みのAIモデルと、その起動スクリプト。

**すでにこれらが用意されている場合は、再インストールせず1-3へ進みます。**

未導入の場合は、[Strata本体の日本語README](https://github.com/Niko1221/Strata/blob/main/README.ja.md)と[インストールガイド](https://github.com/Niko1221/Strata/blob/main/docs/INSTALL.md)で概要を確認してください。ただし、gdx-sparkはARM環境のため、一般的なPC向けの手順をそのまま実行すれば動くとは限りません。先にARM対応のエンジンとモデルを準備する必要があります。このガイドの以降の手順は、**ARM対応済みのStrataが導入されている前提**です。

Strata-Coderの拡張をインストールしても、Strata本体やモデルは自動で用意されません。

### 1-3. Strataを起動する

**すでにStrataの起動用ターミナルやサービスが動いていると分かっている場合は、重ねて起動せず1-4へ進みます。** 起動済みか分からない場合も、先に1-4で確認し、接続できればそのサーバーを使います。接続できない場合は、既存の起動ログを確認してから起動します。

未起動の場合は、1-1で開いた**起動用ターミナル（gdx-spark側）**で、Strataを置いたフォルダーへ移動します。以下のパスは一例です。別の場所へ導入した場合は読み替えてください。

```sh
cd ~/work/llm/strata
```

続けて、用意されている起動スクリプトを確認します。

```sh
ls run-*.sh
```

例えば`run-iq3_s.sh`が表示され、これが使用するモデルの起動スクリプトなら、次を実行します。

```sh
bash ./run-iq3_s.sh
```

ファイル名は設定したモデルによって異なります。**実際に表示された、使用するモデルのスクリプト名を指定してください。** `No such file or directory`と出る場合は、フォルダーやファイル名が違うか、セットアップが完了していません。

起動ログが表示され、モデルの読み込みが始まります。読み込みには数分かかる場合があります。サーバーが準備できると`ready:`で始まる案内が表示されます。

**このターミナルは閉じずに、そのまま残してください。** 入力待ちに戻らずログが表示されている状態で構いません。ここで`Ctrl + C`を押したり、ターミナルを閉じたりすると、Strataが停止する場合があります。

Strataは基本的にgdx-sparkの`127.0.0.1:8080`で待ち受けます。ネットワーク全体へ公開する設定に変える必要はありません。

### 1-4. 別のターミナルで起動を確認する

**起動用ターミナルは残したまま**、手元のPCで新しいターミナルをもう１つ開きます。こちらを「確認用ターミナル」と呼びます。

確認用ターミナルで、gdx-sparkへ接続します。

```sh
ssh gdx-spark
```

ログインできたら、次を実行します。**この`curl`はStrataを起動するコマンドではなく、起動済みのサーバーを確認するコマンドです。**

```sh
curl http://127.0.0.1:8080/v1/models
```

次のように`data`とモデルの`id`が表示されれば成功です。モデル名は環境によって異なります。

```json
{"object":"list","data":[{"id":"使用中のモデル名"}]}
```

- `Connection refused`：Strataがまだ起動していない、終了している、またはポート番号が違います。1-3の起動ログを確認してください。
- まだ読み込み中：起動用ターミナルのログを確認して待ち、再度実行します。
- `401`や認証エラー：APIキーが必要な可能性があります。Strata管理者へ確認し、2-3でコーディネーターを起動する環境にAPIキーを設定します。

### 1-5. 確認用ターミナルだけ手元のPCへ戻す

**確認用ターミナル**で次を入力します。

```sh
exit
```

**起動用ターミナルでは実行しません。** Strataを動かしたままにしておきます。

以降の手順は、特に断りがなければ**手元のPC側**で行います。今`exit`した確認用ターミナルは、2章の操作に使えます。

---

## 2. Strata-Coderのセットアップ詳細【gdx-sparkと手元のPC】

### 2-1. 必要なソフトを確認する

手元のターミナルで、それぞれ実行します。

```sh
python3 --version
```

```sh
git --version
```

```sh
ssh -V
```

Pythonは**3.10以上**が必要です。Windowsで`python3`が見つからない場合は、次も試します。

```powershell
python --version
```

`python`でバージョンが表示された場合は、後のCursor設定の「Python Path」を`python`にします。

見つからないソフトがある場合：

- Python：[Python公式ダウンロード](https://www.python.org/downloads/)から導入します。WindowsのインストーラーでPATHへ追加する選択肢があれば有効にします。
- Git：[Git公式ダウンロード](https://git-scm.com/downloads)から導入します。
- SSH：Windowsでは設定の「オプション機能」で「OpenSSH クライアント」を確認します。macOSでは通常付属しています。
- Ubuntuでは、以下で必要なものを導入できます。

```sh
sudo apt update
sudo apt install python3 git openssh-client
```

インストールした後はターミナルを開き直して、バージョンを再確認してください。**通常の利用にNode.jsやnpmは不要です。**

### 2-2. v0.2のプログラムと拡張ファイルを用意する

今回はgdx-sparkの `~/work/llm/strata-coder` に実装済みです。公開GitHubから取り直さず、この作業フォルダーを使います。手元のPCには、今回渡した **`strata-coder-0.2.0.vsix`** を保存してください。VSIXはCursorへインストールするファイルです。ソースコードのZIPとは異なります。

まだpushしていないため、GitHub Actionsのmain成果物をダウンロードしても今回の実装は含まれません。将来公開されたときは、v0.2以降のソースと対応するVSIXをそろえてください。手元のPCにソースをcloneする必要はありません。通常の利用にNode.jsやnpmも不要です。

### 2-3. コーディネーターを起動する【gdx-spark側】

Strataの起動用ターミナルを残し、**別のターミナル**で実行します。

```sh
ssh gdx-spark
cd ~/work/llm/strata-coder
python3 --version
ls tools/coordinator.py
```

Python 3.10以上とファイルの存在を確認します。ファイルがなければ古いソースか、移動先が違います。

StrataがAPIキーを要求する構成だけ、同じターミナルで次を実行し、求められたらキーを入力します。キーを要求しない構成では不要です。

```bash
read -rsp 'Strata API key: ' STRATA_API_KEY; echo
export STRATA_API_KEY
```

続いて起動します。

```sh
python3 tools/coordinator.py --state ~/.local/state/strata-coder-coordinator --port 8091 --worker-limit 4 --inference-limit 1 --queue-capacity 1000 --per-owner 100
```

`Coordinator ready`が表示されたら、このターミナルも閉じずに残します。

- `worker-limit 4`：全PCを通じて同時に実行するWorkerの上限です。
- `inference-limit 1`：Strataへ同時に送る推論の上限です。最初は1にします。
- `queue-capacity 1000`：受付済み・処理中の仕事の総上限です。
- `per-owner 100`：同じ依頼元ラベルが占有できる受付件数です。

**いずれもCursorのAgent数ではありません。** Agent数は可変で、空き枠がなければ待機します。全PCから同じ１つのコーディネーターへ接続してください。Strataへ直接送られる別アプリの要求は、この制限の対象外です。

最初の起動で認証用ファイル `~/.local/state/strata-coder-coordinator/token` が作られます。別のSSHターミナルからこのファイルを開き、内容を3-4の秘密情報入力欄へコピーします。例えば、gdx-spark側で次を実行すると表示できます。

```sh
cat ~/.local/state/strata-coder-coordinator/token
```

**表示される値は管理権限を持つ秘密情報です。Chat・Git・共有スクリーンショットへ貼らないでください。** SSHパスワードやStrata APIキーとは別物です。この構成は同じ利用者の信頼できるPC群向けです。

### 2-4. SSHの接続名を確認する【手元のPC側】


手元のターミナルで次を実行します。

```sh
ssh gdx-spark
```

ログインできたら`exit`で戻ります。すでに1-1でログインできていれば、再確認は不要です。

`Could not resolve hostname gdx-spark`と出た場合は、そのPCにSSHの接続名が設定されていません。次のファイルをテキストエディターで作成または開きます。

- Windows：ユーザーフォルダー内の`.ssh\config`（例：`C:\Users\自分のユーザー名\.ssh\config`）
- macOS／Linux：`~/.ssh/config`

`.ssh`フォルダーがなければ作成してください。ファイル名は`config`で、`config.txt`にしないように注意します。既存の設定があれば消さずに、次を追加します。**同じ`Host gdx-spark`の項目がある場合は、その項目を確認・修正します。**

```sshconfig
Host gdx-spark
    HostName 接続先のIPアドレスまたはホスト名
    User 接続先のログインユーザー名
```

`HostName`と`User`の日本語部分を実際の値に置き換えて保存します。実際のIPアドレスやユーザー名は、この公開ガイドには記載していません。再び`ssh gdx-spark`を実行し、ログインできることを確認します。

### 2-5. SSHトンネルを開く【まずはこの方法を使用】

手元のターミナルで、次を１行で実行します。

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:18091:127.0.0.1:8091 gdx-spark
```

パスワードを求められたら入力します。

**入力後に何も表示されず、そのまま待ち続ければ正常です。** このターミナルは閉じずに残します。CursorでStrataを使っている間、通路を維持するためです。

- `18091`：手元のPC側で使うポート番号。
- `8091`：gdx-spark側のコーディネーターのポート番号。
- `-N`：接続先の操作画面を開かず、通路だけを作る指定。

コーディネーターのポートを変更した場合だけ、右側の`8091`を変更します。queuedモードでは手元から8080へトンネルを作る必要はありません。

### 2-6. 起動したターミナルを確認する

この時点で、Strata用・コーディネーター用・手元のSSHトンネル用の３つを残します。コーディネーターは認証付きPOST APIなので、ブラウザーでURLを開くだけでは接続確認できません。3-5の拡張コマンドで確認します。

---

## 3. CursorでのStrata-Coderのセットアップ詳細【手元のPC側】

### 3-1. VSIXをインストールする

1. Cursorを起動します。
2. **コマンドパレット**を開きます。Windows／Linuxは`Ctrl + Shift + P`、macOSは`Command + Shift + P`です。これはChat欄ではなく、エディタの操作を検索する入力欄です。
3. `Extensions: Install from VSIX`と入力し、該当する項目を選びます。
4. 2-2で保存した**`.vsix`ファイル**を選びます。ZIPファイルは選びません。
5. 再読み込みを求められたら実行します。表示されない場合も、コマンドパレットから`Developer: Reload Window`を実行します。
6. 左側の拡張機能一覧で`Strata-Coder`を検索し、インストールされていることを確認します。

### 3-2. 最初のお試し用フォルダーを用意する

いきなり大切なプロジェクトを変更せず、小さなフォルダーで接続を試します。手元のターミナルで次を実行します。既存フォルダーと名前が重なる場合は、別の名前に変えてください。

```sh
mkdir strata-coder-demo
cd strata-coder-demo
git init
```

Cursorのメニューから**File → Open Folder**で、この`strata-coder-demo`フォルダーを開きます。

- 自分で作ったフォルダーなので、信頼の確認が出たら信頼する設定にします。
- Explorerで新しいファイル`hello.py`を作り、次を入力して保存します。

```python
def greet(name):
    return "Hello, " + name

print(greet("world"))
```

Cursorの**Terminal → New Terminal**を開き、次を実行します。これはCursor内のターミナルであり、Chat欄ではありません。

```sh
git add hello.py
git commit -m "Add demo file"
git status --short
```

最後のコマンドが**何も表示しなければ準備完了**です。Strata-Coderは、変更が保存済み・commit済みのGitリポジトリを前提にしています。

`Author identity unknown`が出た場合は、このお試しrepo内だけのGitの記録用名前を設定して、commitを再実行できます。

```sh
git config user.name "Demo User"
git config user.email "demo@example.invalid"
git commit -m "Add demo file"
```

この設定はお試し用です。実際のプロジェクトでは、自分が使用するGitの名前とメールアドレスを設定してください。

### 3-3. Strata-Coderの接続先を設定する

SSHトンネルは2-5のターミナルで動かしたままにします。

1. コマンドパレットを開きます。
2. **`Preferences: Open Settings (UI)`**を選びます。
3. 設定画面の**User／ユーザー**側を選びます。Workspace側ではありません。
4. 検索欄に`strataCoder`と入力します。
5. 次の値に設定します。

- **Connection Mode**：`direct`
- **Execution Mode**：`queued`（初期値はsingleなので必ず変更）
- **Coordinator Url**：`http://127.0.0.1:18091/v1`
- **Depth**：`auto`（Cursorが依頼時にlow／medium／highと理由を選択）
- **Worker Concurrency**：`2`
- **Test Concurrency**：`1`
- **Python Path**：2-1で動いたコマンド。通常は`python3`、Windowsで`python`を確認した場合は`python`。
- **Model／Base Url**：queuedモードでは使用しません。モデルはコーディネーター側で選択します。
- **Test Commands**：最初のお試しでは空のまま。

**directでも通信はSSHトンネルを通ります。** この設定は「拡張機能自身はトンネルを作らず、2-5で開いた通路につなぐ」という意味です。

設定をJSONで編集することに慣れている場合は、コマンドパレットの`Preferences: Open User Settings (JSON)`で次を設定しても構いません。**既存の設定全体を置き換えず、同じキーがあれば更新してください。** UIから設定した場合は、こちらの操作は不要です。

```json
{
  "strataCoder.connectionMode": "direct",
  "strataCoder.executionMode": "queued",
  "strataCoder.depth": "auto",
  "strataCoder.coordinatorUrl": "http://127.0.0.1:18091/v1",
  "strataCoder.workerConcurrency": 2,
  "strataCoder.testConcurrency": 1,
  "strataCoder.pythonPath": "python3"
}
```

Worker ConcurrencyとTest Concurrencyは、そのワークスペースの実行枠です。複数フォルダーを開く場合は、それぞれに枠があるためPC全体の負荷も考えて設定してください。

### 3-4. Coordinator Tokenを登録する【必須】

1. コマンドパレットで **`Strata-Coder: Set Coordinator Token`** を実行します。
2. 2-3のtokenファイルの内容を入力します。

拡張の秘密情報ストレージへ保存されます。Settings JSONやChatには書きません。`Set API Key`はsingleモード用で、この手順では使いません。

### 3-5. 登録と接続確認をする

コマンドパレットから、順番に実行します。

1. **`Strata-Coder: Register / Reconnect`**
2. **`Strata-Coder: Check Connection`**

`Strata-Coder connected.`と表示されれば、拡張からStrataへ接続できています。Output／出力パネルの`Strata-Coder`には、`execution_mode: queued`、モデル名、キュー設定を確認してください。

接続先などの設定を変更したときは、タスクが動いていない状態で、この２つを再実行してください。

### 3-6. Chatから使う

1. CursorのChat／Agentパネルを開きます。
2. ツールを使える**Agentモード**を選びます。
3. Cursorのモデルは普段使っているものを選びます。Strataの名前に置き換える必要はありません。
4. 次をChat欄へ入力します。

> Strata-Coderを使ってhello.pyを調査してください。最初にstrata_healthで接続を確認し、strata_submitのresearchモードで、owner="demo-agent-1"、request_key="demo-research-1"を指定して処理の内容を調べてください。タスクIDを記録し、待機中は短い間隔で状態を問い合わせ続けないでください。ファイルは変更しないでください。あなたは監督として結果を確認し、短く説明してください。

CursorがMCPツールの実行許可を求めた場合は、対象がStrata-Coderであることと内容を確認して進めます。

**正常な流れ**：接続確認 → タスクIDの発行 → 調査結果の取得 → Cursorによる説明、です。Strataは初回の応答に時間がかかる場合があります。

`@Strata-Coder`という新しいチャット参加者を追加する方式ではありません。**いつものCursor Agentが、Strata-Coderのツールを呼び出します。**

ステータスバーと `Strata-Coder: Show Task Status` で進捗を確認できます。この監視はCursorモデルを呼びません。完了通知はChatを自動再開しないため、Chatが終了していたら「先ほどのタスクIDの結果を取得して」と依頼してください。

複数Agentでは各Agentに別のowner、各依頼に別のrequest_keyを付けます。同じ依頼の受付応答が不明で再送するときだけ同じキーを使います。詳しい調査・編集・取消・負荷試験の指示は[テスト用指示集](test-prompts-ja.md)にあります。

### 3-7. 編集を試す前にテストを登録する

テストの設定はプロジェクトごとに内容が異なります。最初の動作確認は3-6の調査だけで十分です。

例えばPythonの`unittest`を使うプロジェクトでは、ユーザー設定の`strataCoder.testCommands`へ次のような対応を登録します。

```json
{
  "strataCoder.testCommands": {
    "unit": ["python3", "-m", "unittest", "discover", "-s", "tests"]
  }
}
```

`python`を使う環境では配列の先頭も`python`に変更します。この例は**`tests`フォルダーに実際のテストがあるプロジェクト向け**です。上のお試しフォルダーにはテストがないため、そのまま登録しても修正の正しさは確認できません。

設定後、`Register / Reconnect`を実行します。Chatでは、変更するファイル、満たすべき条件、テストID（この例では`unit`）を指定して依頼します。Strataの変更は別の作業場所に保管され、Cursorが差分をレビューしてから元のフォルダーへ適用します。`apply_queued`は適用待ちです。`applied`を確認してください。基準コミットが変わった場合は、新しい差分とテストの再レビューが必要です。適用後は未commitの変更が残ります。自動commit・pushはしません。

---

## 次回から使うとき

1. 未起動なら1-3でStrataを起動し、1-4で応答を確認します。起動用ターミナルは残します。
2. 2-3のコーディネーターが起動していることを確認します。未起動なら同じ状態ディレクトリで起動します。
3. 手元のターミナルで2-5のSSHトンネルを開いたままにします。
4. Cursorで対象のGitリポジトリを開きます。
5. `Strata-Coder: Check Connection`を実行します。
6. Agent ChatでStrata-Coderを使うよう依頼します。

作業を終了し、Strata-Coderのタスクが止まってから、トンネルのターミナルで`Ctrl + C`を押すと接続を閉じられます。

## 慣れてきたら：SSH鍵認証でトンネルを自動化する

この手順は任意です。パスワードによる手動トンネルが動いていれば、急いで変更する必要はありません。

すでにSSH鍵やSSHエージェントを設定している場合、手元のターミナルで次を確認します。

```sh
ssh -o BatchMode=yes gdx-spark true
```

パスワード入力なしでエラーなく終了したら、Cursorのユーザー設定を次へ変更できます。

- **Connection Mode**：`ssh`
- **Ssh Host**：`gdx-spark`
- **Coordinator Port**：`8091`
- **Execution Mode**：`queued`のまま。Coordinator Tokenも必要です。

`Register / Reconnect`と`Check Connection`を実行します。この方式では拡張が通路を作るので、手動のトンネル用ターミナルは不要です。鍵認証が未設定の状態では動きません。Strata-CoderはSSHパスワードを保存・自動入力しません。

## 困ったとき

### `Strata-Coder:`で始まるコマンドが見つからない

拡張機能一覧でインストールされていることを確認します。Gitのフォルダーを開き、信頼設定を確認し、`Developer: Reload Window`を実行してください。ZIPではなく`.vsix`を選んだかも確認します。

### `This Cursor version lacks the MCP extension API`と出る

使用中のCursorが、この拡張で使うAPIに対応していません。Cursorを更新して再確認します。対応版が使えない場合は、[READMEの手動MCP設定](../README.md#manual-mcp-setup)が代替になります。このエラーはStrataの故障ではありません。

### `Could not resolve hostname gdx-spark`

2-4のSSH設定を確認します。設定を作る場所は、gdx-spark側ではなく**手元のPC側**です。

### `Permission denied` / `SSH tunnel failed`

まず通常の`ssh gdx-spark`でログインできるか確認します。パスワードなら2-5の手動トンネルと`direct`設定を使ってください。`ssh`モードは鍵／エージェント認証が前提です。

### `Address already in use` / `18091`が使えない

すでにトンネルが動いている場合は、それを利用します。別のアプリが使っている場合は、トンネルの**左側**を`18081`へ変更し、CursorのCoordinator Urlも`http://127.0.0.1:18081/v1`に変更します。右側の`8091`は変更しません。

### `Connection refused` / `Strata-Coder connection failed`

次の順に確認します。

1. 1-3〜1-4：gdx-sparkでStrataを起動し、APIが応答するか。
2. 2-3：コーディネーターが起動しているか。
3. 2-5：手元のトンネル用ターミナルが残っているか。
4. 3-3：Execution Mode、Python Path、Coordinator Url、Connection Modeが正しいか。
5. 3-4：Coordinator Tokenを登録したか。認証エラーなら接続先のtokenファイルと照合します。

推論が停止状態になった場合やWorker切断後の復旧は、[障害時の手順](multi-agent-setup-ja.md#7-停止障害時)を確認してください。実行中の仕事は、再起動だけで自動再実行されません。

### `Repository has uncommitted/untracked changes`

対象フォルダーで`git status --short`を確認します。既存の変更は、内容を確認して自分でcommitするか、別のお試しrepoを使ってください。**エラーを消す目的でファイルを削除したり、`git reset --hard`を実行したりしないでください。**

### ChatがStrata-Coderのツールを見つけない

Agentモードか確認し、`Register / Reconnect`を実行してください。CursorのMCP設定／ツール一覧に`strata-coder-`で始まるサーバーがあるか確認します。Chatで`strata_healthを使って`と明示して再度試します。

### 調査できるが、期待した変更ができない

接続成功と、AIが正しく修正できることは別です。まず１ファイルの小さな作業へ絞ってください。`review_ready`は「レビュー待ち」であり、正しさが保証された状態ではありません。Cursorに差分とテスト結果を確認させます。

それでも進めない場合は、**何番の手順で止まったか・手元のOS・エラー文**を伝えてください。パスワードやAPIキーは含めないでください。

## LLMの深さを選ぶ

User Settingsで`strataCoder.depth`を検索し、`auto / low / medium / high`を選びます。変更後は実行中の仕事がない状態でRegister / Reconnectを実行してください。既存タスクの深さは変更されません。

- auto：Cursorが委譲時に難しさを判断し、深さと短い理由を指定します。判定だけの追加LLM呼び出しは行いません。
- low：限定された調査、原因が分かっている小さな修正。
- medium：複数ファイルの修正、調査が必要な不具合。
- high：設計・並行処理・複雑な原因調査。

Chatで「今回はhighで調べて」と指定すると、そのタスクでは設定の既定値より優先します。明示指定を勝手に引き上げません。autoは失敗の根拠をCursorが確認してから、最大１回の再委譲で深さを上げる運用です。この再委譲回数は監督Skillの指示であり、別Chatをまたいだ強制的な予算管理ではありません。

`Strata-Coder: Show Task Status`に`auto -> medium`などの選択結果と理由が表示されます。`strata_summary`にも保存されます。autoで理由や深さが欠ける依頼はエラーとなり、lowへ黙って変更しません。

深さとは別に`max_steps`（1〜30、標準12）と`max_output_tokens`（128〜8192、標準2048）をタスクに指定できます。`strataCoder.maxOutputTokens`は未指定時の既定値で、queuedでも反映されます。highでも短い出力上限では途中で打ち切られることがあります。

現在のStrataソースにはlow／medium／highの処理がありますが、モデルごとの効果まで自動判定できるAPIではありません。`strata_health`のreasoning_supportは既定でunverified（未検証）です。管理者がモデルを検証した場合だけコーディネーター起動時に`--reasoning-support supported`を指定します。非対応と分かった場合は`--reasoning-support unsupported`を指定し、推論をエラーで停止させます。HTTP成功だけで対応済みとは扱いません。
