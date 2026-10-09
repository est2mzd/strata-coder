# はじめてのStrata-Coder導入ガイド

このガイドでは、**gdx-sparkで動いているStrataを、手元のPCのCursorから利用する**ところまで設定します。最初はパスワードでSSH接続できれば進められる方法を説明します。

Strata-Coderは開発初期版です。LinuxでのWorker動作とSSH経由の推論は検証済みですが、Cursorの実画面での連携、Windows・macOSは検証中です。画面名が違ったり、エラーが出たりした場合は、末尾の「困ったとき」を確認してください。

## 最初に：何をどこへ入れるのか

- **Strata**：AIモデルを動かすサーバー。**gdx-spark側**で動かします。
- **Strata-Coder**：Strataに調査や修正を任せるプログラム。**Cursorを使う手元のPC側**へ拡張機能として入れます。
- **Cursor**：あなたが依頼を入力するエディタ。方針の決定と、Strataが作った変更のレビューを担当します。
- **SSHトンネル**：手元のPCからgdx-sparkのStrataへつなぐ通路です。最初はターミナルで起動します。

手元のPCにAIモデルをダウンロードする必要はありません。Cursorの通常のモデルは引き続き使用します。Strataに詳しい調査や修正作業を任せることで、Cursorが読む情報量を減らす構成です。削減率はまだ測定していません。

**このガイドの範囲**：Cursorで手元のPCのフォルダーを開く場合です。Cursorの「Remote SSH」で別のPCのフォルダーを開く場合は実行場所が変わるので、まずこの構成で接続を確認してください。

---

## 1. Strataのセットアップ概要【gdx-spark側】

### 1-1. すでにStrataが動いているか確認する

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

接続できたら、**このターミナルはgdx-spark上で操作している状態**です。次を実行します。

```sh
curl http://127.0.0.1:8080/v1/models
```

次のように`data`とモデルの`id`が表示されれば、StrataのAPIへ接続できています。モデル名は環境によって異なります。

```json
{"object":"list","data":[{"id":"使用中のモデル名"}]}
```

**これが表示されたら、Strataを再インストールせずに1-3へ進んでください。**

`401`や認証エラーの場合は、APIキーを設定している可能性があります。Strata管理者へ確認し、後の3-4で同じAPIキーを登録してください。`Connection refused`の場合は、未起動か、ポート番号が違います。

### 1-2. Strataが未起動・未導入の場合

Strataの準備は、次の順に行います。

1. Strata本体を入手する。
2. gdx-sparkのARM環境で動くエンジンを用意する。
3. メモリ・ディスク容量に合うモデルをダウンロードする。
4. エンジンとモデルを指定してStrataサーバーを起動する。
5. 1-1の`/v1/models`が応答することを確認する。

**注意：Strata-Coderを入れても、Strata本体やモデルはインストールされません。** また、gdx-sparkはARM環境です。Strataの一般的なPC向けセットアップをそのまま実行すれば動くとは限りません。このガイドは、ARM対応済みのStrataを利用する前提です。

Strataの概要・通常のインストール方法は[Strata本体の日本語README](https://github.com/Niko1221/Strata/blob/main/README.ja.md)と[インストールガイド](https://github.com/Niko1221/Strata/blob/main/docs/INSTALL.md)を参照してください。ARM対応のエンジンをまだ用意していない場合は、先にその準備が必要です。

すでにインストール済みで、起動だけ必要な場合は、**gdx-spark側**でStrataを置いたフォルダーを開きます。以下のパスは一例です。

```sh
cd ~/work/llm/strata
ls run-*.sh
```

表示された起動スクリプトから、設定済みモデルのものを実行します。例えば`run-iq3_s.sh`がある場合は次のようにします。

```sh
bash ./run-iq3_s.sh
```

モデルを読み込むまで待ち、別のターミナルからSSH接続して1-1を確認します。起動中のサーバーがある場合に、同じものを重ねて起動しないでください。起動用ターミナルを閉じると停止する場合があります。

Strataは基本的にgdx-sparkの`127.0.0.1:8080`で待ち受けます。ネットワーク公開設定へ変更する必要はありません。APIキーを使う構成では、後でCursor拡張にも登録します。

### 1-3. 手元のPCへ戻る

確認用のSSHターミナルで次を入力します。

```sh
exit
```

以降の手順は、特に断りがなければ**手元のPC側**で行います。

---

## 2. Strata-Coderのセットアップ詳細【手元のPC側】

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

### 2-2. 拡張ファイルをダウンロードする

Cursorに入れるファイルの拡張子は**`.vsix`**です。GitHubの「Code → Download ZIP」で入手できるソースコードのZIPとは異なります。

1. ブラウザーで[Strata-Coderのビルド一覧](https://github.com/est2mzd/strata-coder/actions/workflows/ci.yml)を開きます。
2. GitHubにログインします。ビルド成果物のダウンロードにはログインが必要です。
3. `main`の最新の実行で、**緑色のチェックが付いたもの**を開きます。
4. 開いたページの下部にある**Artifacts**を探します。
5. **`strata-coder-vsix`**をクリックしてZIPをダウンロードします。
6. ZIPを展開します。中にある**`strata-coder-0.1.0.vsix`**を分かりやすい場所へ保存します。バージョンが更新されると数字部分は変わります。

まだ実行中なら緑のチェックになるまで待ちます。Artifactsがない場合は、失敗した実行や保存期限が過ぎた実行を開いていないか確認してください。

**利用するだけなら、Strata-Coderのソースコードをcloneしたり、gdx-sparkへ拡張機能をインストールしたりする必要はありません。**

### 2-3. SSHの接続名を確認する

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

### 2-4. SSHトンネルを開く【まずはこの方法を使用】

手元のターミナルで、次を１行で実行します。

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:8080 gdx-spark
```

パスワードを求められたら入力します。

**入力後に何も表示されず、そのまま待ち続ければ正常です。** このターミナルは閉じずに残します。CursorでStrataを使っている間、通路を維持するためです。

- `18080`：手元のPC側で使うポート番号。
- `8080`：gdx-spark側のStrataのポート番号。
- `-N`：接続先の操作画面を開かず、通路だけを作る指定。

Strataのポートを変更している場合は、右側の`8080`をその値へ変更してください。

### 2-5. 通路が使えるか確認する

ブラウザーで、次を開きます。

[http://127.0.0.1:18080/v1/models](http://127.0.0.1:18080/v1/models)

1-1と同じように`data`とモデルの`id`が表示されれば成功です。APIキーを使う構成では認証エラーになる場合があります。その場合は3-4でキーを設定し、3-5の接続確認を行います。

---

## 3. CursorでのStrata-Coderのセットアップ詳細【手元のPC側】

### 3-1. VSIXをインストールする

1. Cursorを起動します。
2. **コマンドパレット**を開きます。Windows／Linuxは`Ctrl + Shift + P`、macOSは`Command + Shift + P`です。これはChat欄ではなく、エディタの操作を検索する入力欄です。
3. `Extensions: Install from VSIX`と入力し、該当する項目を選びます。
4. 2-2で展開した**`.vsix`ファイル**を選びます。ZIPファイルは選びません。
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

最後のコマンドが**何も表示しなければ準備完了**です。Strata-Coder v0.1は、変更が保存済み・commit済みのGitリポジトリを前提にしています。

`Author identity unknown`が出た場合は、このお試しrepo内だけのGitの記録用名前を設定して、commitを再実行できます。

```sh
git config user.name "Demo User"
git config user.email "demo@example.invalid"
git commit -m "Add demo file"
```

この設定はお試し用です。実際のプロジェクトでは、自分が使用するGitの名前とメールアドレスを設定してください。

### 3-3. Strata-Coderの接続先を設定する

SSHトンネルは2-4のターミナルで動かしたままにします。

1. コマンドパレットを開きます。
2. **`Preferences: Open Settings (UI)`**を選びます。
3. 設定画面の**User／ユーザー**側を選びます。Workspace側ではありません。
4. 検索欄に`strataCoder`と入力します。
5. 次の値に設定します。

- **Connection Mode**：`direct`
- **Base Url**：`http://127.0.0.1:18080/v1`
- **Python Path**：2-1で動いたコマンド。通常は`python3`、Windowsで`python`を確認した場合は`python`。
- **Model**：空欄のまま。Strataにロードされた１モデルを自動選択します。
- **Test Commands**：最初のお試しでは空のまま。

**directでも通信はSSHトンネルを通ります。** この設定は「拡張機能自身はトンネルを作らず、2-4で開いた通路につなぐ」という意味です。

設定をJSONで編集することに慣れている場合は、コマンドパレットの`Preferences: Open User Settings (JSON)`で次を設定しても構いません。**既存の設定全体を置き換えず、同じキーがあれば更新してください。** UIから設定した場合は、こちらの操作は不要です。

```json
{
  "strataCoder.connectionMode": "direct",
  "strataCoder.baseUrl": "http://127.0.0.1:18080/v1",
  "strataCoder.pythonPath": "python3",
  "strataCoder.model": ""
}
```

### 3-4. StrataがAPIキーを要求する場合だけ登録する

1. コマンドパレットで**`Strata-Coder: Set API Key`**を実行します。
2. Strataサーバーに設定されているAPIキーを入力します。

SSHのログインパスワードとは別物です。APIキーは拡張機能の秘密情報ストレージへ保存されます。Chat欄や公開Gitリポジトリへ書かないでください。APIキーを設定していないStrataの場合、この手順は不要です。

### 3-5. 登録と接続確認をする

コマンドパレットから、順番に実行します。

1. **`Strata-Coder: Register / Reconnect`**
2. **`Strata-Coder: Check Connection`**

`Strata-Coder connected.`と表示されれば、拡張からStrataへ接続できています。Output／出力パネルの`Strata-Coder`には、モデル一覧が表示されます。

接続先などの設定を変更したときは、タスクが動いていない状態で、この２つを再実行してください。

### 3-6. Chatから使う

1. CursorのChat／Agentパネルを開きます。
2. ツールを使える**Agentモード**を選びます。
3. Cursorのモデルは普段使っているものを選びます。Strataの名前に置き換える必要はありません。
4. 次をChat欄へ入力します。

> Strata-Coderを使ってhello.pyを調査してください。最初にstrata_healthで接続を確認し、strata_submitのresearchモードで処理の内容を調べてください。ファイルは変更しないでください。あなたは監督として結果を確認し、短く説明してください。

CursorがMCPツールの実行許可を求めた場合は、対象がStrata-Coderであることと内容を確認して進めます。

**正常な流れ**：接続確認 → タスクIDの発行 → 調査結果の取得 → Cursorによる説明、です。Strataは初回の応答に時間がかかる場合があります。

`@Strata-Coder`という新しいチャット参加者を追加する方式ではありません。**いつものCursor Agentが、Strata-Coderのツールを呼び出します。**

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

設定後、`Register / Reconnect`を実行します。Chatでは、変更するファイル、満たすべき条件、テストID（この例では`unit`）を指定して依頼します。Strataの変更は別の作業場所に保管され、Cursorが差分をレビューしてから元のフォルダーへ適用します。自動commit・pushはしません。

---

## 次回から使うとき

1. gdx-sparkでStrataが起動していることを確認します。
2. 手元のターミナルで2-4のSSHトンネルを開いたままにします。
3. Cursorで対象のGitリポジトリを開きます。
4. `Strata-Coder: Check Connection`を実行します。
5. Agent ChatでStrata-Coderを使うよう依頼します。

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
- **Remote Port**：`8080`

`Register / Reconnect`と`Check Connection`を実行します。この方式では拡張が通路を作るので、手動のトンネル用ターミナルは不要です。鍵認証が未設定の状態では動きません。Strata-CoderはSSHパスワードを保存・自動入力しません。

## 困ったとき

### `Strata-Coder:`で始まるコマンドが見つからない

拡張機能一覧でインストールされていることを確認します。Gitのフォルダーを開き、信頼設定を確認し、`Developer: Reload Window`を実行してください。ZIPではなく`.vsix`を選んだかも確認します。

### `This Cursor version lacks the MCP extension API`と出る

使用中のCursorが、この拡張で使うAPIに対応していません。Cursorを更新して再確認します。対応版が使えない場合は、[READMEの手動MCP設定](../README.md#manual-mcp-setup)が代替になります。このエラーはStrataの故障ではありません。

### `Could not resolve hostname gdx-spark`

2-3のSSH設定を確認します。設定を作る場所は、gdx-spark側ではなく**手元のPC側**です。

### `Permission denied` / `SSH tunnel failed`

まず通常の`ssh gdx-spark`でログインできるか確認します。パスワードなら2-4の手動トンネルと`direct`設定を使ってください。`ssh`モードは鍵／エージェント認証が前提です。

### `Address already in use` / `18080`が使えない

すでにトンネルが動いている場合は、それを利用します。別のアプリが使っている場合は、トンネルの**左側**を`18081`へ変更し、CursorのBase Urlも`http://127.0.0.1:18081/v1`に変更します。右側の`8080`は変更しません。

### `Connection refused` / `Strata-Coder connection failed`

次の順に確認します。

1. 1-1：gdx-spark上でStrataのAPIが応答するか。
2. 2-4：手元のトンネル用ターミナルが残っているか。
3. 2-5：手元のブラウザーからAPIへ到達するか。
4. 3-3：Python Path、Base Url、Connection Modeが正しいか。
5. APIキーを設定している場合は3-4を済ませたか。

### `Repository has uncommitted/untracked changes`

対象フォルダーで`git status --short`を確認します。既存の変更は、内容を確認して自分でcommitするか、別のお試しrepoを使ってください。**エラーを消す目的でファイルを削除したり、`git reset --hard`を実行したりしないでください。**

### ChatがStrata-Coderのツールを見つけない

Agentモードか確認し、`Register / Reconnect`を実行してください。CursorのMCP設定／ツール一覧に`strata-coder-`で始まるサーバーがあるか確認します。Chatで`strata_healthを使って`と明示して再度試します。

### 調査できるが、期待した変更ができない

接続成功と、AIが正しく修正できることは別です。まず１ファイルの小さな作業へ絞ってください。`review_ready`は「レビュー待ち」であり、正しさが保証された状態ではありません。Cursorに差分とテスト結果を確認させます。

それでも進めない場合は、**何番の手順で止まったか・手元のOS・エラー文**を伝えてください。パスワードやAPIキーは含めないでください。
