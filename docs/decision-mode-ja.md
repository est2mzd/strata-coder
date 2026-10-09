# v0.3：短い判断資料と指令で使う

**段階目標：Step 1＝1/10以下（10%）、Step 2＝1/50以下（2%）、Step 3＝1/100以下（1%）。現在はStep 1を実装・検証中です。品質を維持した実測で合格してから次へ進みます。**


この方式ではCursorが実装を逐次進行しません。短い依頼では利用者の原文と実測状態から資料を作成し、長い依頼だけStrataで要約します。Strataが実装・テスト・別コンテキストでのレビューを行い、Cursorは短い資料から次の指令を返します。**1/100以下は合格目標で、達成保証ではありません。** 特に小さい課題ではCursorの固定入力だけで1%を超える可能性があります。

## 起動と接続

Strataと共有コーディネーターを[既存の起動手順](multi-agent-setup-ja.md)で起動し、SSHトンネルとCoordinator Tokenを設定します。v0.3 VSIXをインストールしてください。設定`strataCoder.supervisionMode`は`decision`（新しい既定値）です。この方式は共有コーディネーターを使います。

従来のMCPによる逐次監督を使う場合だけ`legacy`へ戻します。decisionでは旧Workerツールと旧Skillを自動登録しません。設定変更後は`Register / Reconnect`を実行します。以前手動で登録したMCPは自動削除しないため、評価時は利用者が無効化してください。

## 1. 利用者が依頼契約を用意

作業repoの外に`missions.json`を作ります。モデルへ渡す前の原本で、編集範囲とテストIDは利用者が決めます。実際のファイル・テストへ置き換えてください。

```json
[
  {
    "background": "ページ分割を行うPython関数",
    "purpose": "入力の末尾を欠落させない",
    "objective": "subject.pyのpagesを修正。全要素を順番どおり分割し、空入力は空リスト、sizeが0以下ならValueError。",
    "allowed_paths": ["subject.py"],
    "acceptance": ["全要素を保持", "空入力に対応", "不正sizeを拒否"],
    "test_ids": ["unit"],
    "depth": "auto",
    "allow_apply": false
  }
]
```

`unit`はUser SettingsのTest Commandsへ登録しておきます。実際の受入条件を検証するテストが必要です。`allow_apply: false`なら結果は検証済みの差分として保管し、元repoへ適用しません。`true`は「この契約の範囲内で、最終テストと独立レビューを通った変更の適用を許可する」指定です。commit・pushは行いません。

1バッチは1〜32依頼です。同じrepoの複数依頼をまとめる場合は全て`allow_apply: false`にします。現段階では複数差分の統合・適用は自動化していません。独立したworkspaceは別のバッチとして処理します。

## 2. 判断資料を準備する

コマンドパレットで`Strata-Coder: Prepare Decision Batch`を選び、依頼契約JSONを指定します。処理はプログラムで待機し、Cursorモデルへ状態確認を繰り返し依頼しません。

準備できたら`Strata-Coder: Copy Decision Brief`を実行します。コピーされるものは次だけです。

- 背景（background）
- 目的（purpose）
- 現状・計画・不確実性（current）
- 判断してほしいこと（request）
- 計画ID、revision、固定された深度

4項目は合計800文字以内。超えた要約はStrata側で一度だけ圧縮し、それでも収まらなければ黙って切らず停止します。全文・ログ・証拠はローカルに保存します。短い要約に必要な情報が全て含まれるかはモデルの品質に依存するため、疑問がある場合はinspectを選びます。

## 3. Cursorには短い指令だけを返させる

新しいChatへ資料を貼り、コードや長い履歴を追加しません。Cursorの返答はJSON配列だけです。

```json
[{"id":"資料のID","revision":1,"plan":"資料の計画ID","action":"run","depth":"low"}]
```

`run / revise / inspect / stop`から選択します。reviseとinspectには120文字以内のinstructionを付けます。1指令はJSON全体で240文字以内。利用者が指定した深度を勝手に変更できません。

この初期実装では、IDE Chatの返答を自動で取り込むAPIは使っていません。コピーと貼り付けが必要です。IDE Chatのトークン量はこの操作だけでは取得できず、利用明細などによる別計測が必要です。新しいChatでもCursor内部の固定コンテキストは残ります。

## 4. 指令を実行する

`Strata-Coder: Execute Decision`を選び、CursorのJSON配列を貼ります。プログラムが以下を実施します。

1. ID・revision・実行済み状態・利用者の深度指定を検証。
2. Strataが別worktreeで実装し、登録された最終テストを実施。
3. 別タスク・別コンテキストのStrataが全文差分と条件をレビュー。機械判定に添えられた根拠はローカルへ保存し、Cursorへ送らない。
4. テスト成功・レビュー承認・正確な差分ハッシュ・利用者の適用許可がそろった場合だけ適用。

完了はOutputに表示します。Cursorへ完了報告を書かせる必要はありません。失敗時は証拠を残して停止し、勝手に再実行しません。大きい差分（現状4,500文字超）や大きいレビュー入力は切り捨てず、追加のレビューが必要な状態として停止します。長い変更を扱う分割レビューは未実装です。

## CLIでバッチ判断とトークンを計測

設定JSONには既存のqueued設定、接続先、テストIDを入れます。トークンは環境変数または非公開のcoordinator_token_fileで指定してください。

```sh
python3 tools/decision.py prepare --repo /absolute/project --state /absolute/private/batch --config /absolute/private/config.json --missions /absolute/private/missions.json
python3 tools/decision.py cursor --state /absolute/private/batch --cli /absolute/path/to/cursor-agent --model composer-2.5 --baseline-tokens 2000000 --step 1
python3 tools/decision.py execute --repo /absolute/project --state /absolute/private/batch --config /absolute/private/config.json --decisions /absolute/private/batch/decisions.json
python3 tools/decision.py status --state /absolute/private/batch
```

`--step 1`（既定）／`--step 2`／`--step 3`で段階を指定します。

baseline-tokensは同じ課題のCursor単独実測値であり、合格させるために任意の大きな値を設定しません。入力＋出力＋キャッシュ読込＋書込を保存し、合計が選択した段階の上限以下か判定します。既定では16,000トークンの予約枠が残予算に収まらなければCursorを呼びません。これは見積りによる事前停止で、CLIに厳密な総トークン生成上限を強制できるわけではありません。

評価だけで固定負担を確認する場合はcursorコマンドに`--measure-over-budget`を付けられます。この場合は予算不足でも1回の計測を行い、そのバッチの機能検証を続けられますが、目標を満たしたとは判定しません。Cursorのツール使用・無効JSON・使用量不明を検出すると指令を採用しません。1バッチのCursor呼出しは最大2回です。

UI方式とCLI方式は別です。CLIはソースを置かない空のworkspaceで、判断資料のみを1回の呼出しへまとめます。IDE Chatの初期指示トークンを除いてCLIだけを測った結果を、IDE全体の1/100達成と称しません。
