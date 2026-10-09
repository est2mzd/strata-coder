> 最新のv0.3検証は[判断方式の検証](decision-verification-ja.md)を参照してください。Pythonテストはローカル・gdx-sparkの両方で58件成功しました（13.488秒／12.235秒）。拡張のモックテストも成功しています。以下はv0.2時点の41件の履歴です。

# 検証記録：深度選択・共有キュー（2026-10-09）

## 1. 検証目的

「ローカル・gdx-spark両方で41テスト成功」は、以下のPython自動テストを各環境で独立して実行し、41件すべてが成功したという意味です。41個のCursor Agentを実際に起動した、あるいは41件を実LLMで解決したという意味ではありません。

目的は、共有キューによる可変数の依頼受付、作業範囲の制約、レビュー済み差分の適用、障害時の停止と、auto／low／medium／highの設定伝達が、深度選択の追加後も動作することの確認です。Cursor総トークン削減と回答精度の改善は、別の実測が必要です。

## 2. 対象と環境

- 対象：Strata-Coder v0.2.0開発版、作業ブランチ `feature/scalable-task-queue`。検証時は未commitの変更を含み、pushしていません。公開mainのソースとは異なります。
- ローカル：Linux x86_64。Pythonでユニット／統合テストを実施しました。
- gdx-spark：Linux aarch64、Python 3.12。配置先 `~/work/llm/strata-coder` で同じテストを実施しました。
- 依存：Python 3.10以上、Git、一時ディレクトリへの書込みとローカルループバック通信。Pythonテストは標準ライブラリで動作します。
- 検証対象ファイルの識別：[SHA-256一覧](verification-source-sha256.json)。ソース・テスト・拡張の主要ファイルを収録しています。文書全体や依存環境の完全なスナップショットではありません。

## 3. 手法と41件の内訳

`unittest`で`tests/test*.py`を探索します。一時Gitリポジトリ、実際のworktree・差分適用、SQLite、スレッド、ループバックHTTPサーバーを使用します。LLMの応答は模擬応答で制御し、再現可能な条件で正常系と異常系を確認します。各試験の正確な条件・期待値はリンク先のコードが基準です。

- [test_core.py](../tests/test_core.py)：16件。編集の分離とレビュー後の適用、未commit変更の保護、researchでの書込み禁止、範囲外パス・symlink・秘密情報パス制限、古いハッシュ拒否、基準commit変更、最終テスト失敗、時間制限、証拠のページ取得、出力打切り、取消、再起動時の証拠保持、MCP初期化／スキーマ、直接接続の制約、新規ファイルの差分。
- [test_queue.py](../tests/test_queue.py)：13件。可変依頼元数、容量制限、同じ依頼の重複防止、公平な順番、待機取消、リース失効、再起動、適用の直列化と承認順、不確定な適用の隔離、複数workspaceの公平性、推論枠の独立制御、推論結果不明時の受付停止、イベント重複取得防止。
- [test_distributed.py](../tests/test_distributed.py)：5件。17依頼元の共有キュー、auto深度・理由・出力上限のHTTPキュー→Worker→模擬推論への伝達、編集から適用まで、基準変更後の新しいハッシュと再レビュー、認証とworkspace境界。１台のホスト内で通信経路を構成し、複数の実PCを使う試験ではありません。
- [test_depth.py](../tests/test_depth.py)：4件。autoの選択・理由の必須化、明示指定の優先と矛盾拒否、出力予算の検証、推論要求ペイロード、タスク間の設定分離、非対応指定時の停止。非対応の宣言は管理者設定であり、モデル能力の自動判別ではありません。
- [test_transport.py](../tests/test_transport.py)：3件。HTTP接続・モデル取得、SSH起動引数と所有プロセスの後片付け、URL内の認証情報拒否。SSH起動はモックで検証します。

この41件では実際のStrataサーバー、AIモデル、Cursor、GitHub接続は不要です。ただし一時的なローカルHTTPサーバーを使うため、socket作成を禁止するサンドボックスでは失敗します。

## 4. 結果

深度選択を追加した後、2026-10-09に次の結果を確認しました。以下は実行出力の末尾です。全件の詳細ログは保存していないため、再確認には5章のコマンドを使用してください。

ローカル：終了コード0。

```text
Ran 41 tests in 14.054s

OK
```

gdx-spark：終了コード0。

```text
Ran 41 tests in 11.887s

OK
```

所要時間は今回の実行値です。環境や負荷で変わり、両環境の性能比較を目的とした測定ではありません。

別枠でNode.jsによる拡張のモックテストも成功しました。登録・秘密情報の引渡し・workspaceの信頼設定・通知の重複防止などを検証しています。これは上記41件に含みません。VSIXのパッケージ作成にも成功しましたが、インストールしたCursorの実画面での動作保証ではありません。

## 5. 再現方法

### 5-1. 同じソースを用意する

今回の未公開作業ブランチのファイルを使います。公開mainをcloneしただけでは同じ内容になりません。gdx-sparkでは次を実行します。

```sh
ssh gdx-spark
cd ~/work/llm/strata-coder
git branch --show-current
git status --short
python3 --version
git --version
uname -sm
```

ローカルでは、同じ開発版ソースを配置したStrata-Coderリポジトリのルートへ移動します。実機Strataやコーディネーターを起動する必要はありません。

任意で、文書に記録した対象ファイルと一致するかを確認します。

```sh
python3 - <<'PYHASH'
import hashlib, json
from pathlib import Path
expected = json.loads(Path('docs/verification-source-sha256.json').read_text())
changed = [name for name, digest in expected.items()
           if not Path(name).is_file()
           or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
if changed:
    raise SystemExit('検証時と異なるファイル: ' + ', '.join(changed))
print('検証対象ファイルのSHA-256が一致しました')
PYHASH
```

### 5-2. Pythonの41件を実行する

```sh
python3 -m unittest discover -s tests -v
```

全件が`ok`となり、末尾が`Ran 41 tests ...`、`OK`、終了コード0であることを確認します。今後テストを追加すると件数は変わります。`FAILED`や`ERROR`があれば成功とは扱いません。

Bashでログを保存し、テスト自体の終了コードも保つ場合：

```bash
set -o pipefail
python3 -m unittest discover -s tests -v 2>&1 | tee /tmp/strata-coder-tests.log
```

深度関連だけを確認する場合は、次をそれぞれ実行します。これは全41件の代替ではありません。

```sh
python3 -m unittest discover -s tests -p test_depth.py -v
python3 -m unittest discover -s tests -p test_distributed.py -v
```

### 5-3. 拡張のモックテストを実行する

開発検証にはNode.jsも必要です。通常の拡張利用では不要です。

```sh
node --version
node --check extension/extension.js
node tests/extension.test.js
```

最後に次が表示され、終了コード0なら成功です。

```text
Extension registration, secret forwarding, workspace trust and deduplicated progress notification tests passed
```

### 5-4. Agent数を変えた合成負荷試験

```sh
python3 tools/load_test.py --agents 7 --workers 3 --inference 1 --tasks-per-agent 2
python3 tools/load_test.py --agents 73 --workers 4 --inference 2 --tasks-per-agent 2
```

`completed == tasks`、`peak_inference <= inference_limit`、`errors`が空であることを確認します。過去のv0.2実行では14件／146件が完了し、推論ピークはそれぞれ1／2でした。この結果は41件の集計外で、深度追加後の再実行結果ではありません。模擬モデルのため、実LLMの速度・品質・トークン削減量を示しません。

## 6. 実機検証との区別・残っている検証

以前のv0.2では実SSHと実Strataを用い、調査と編集の2件について、レビュー待ち→差分確認→適用→独立したテスト成功まで確認しました。これは下記の過去記録です。41件の自動テストとは別で、今回の深度ごとの実LLM比較を実施した証拠ではありません。実機で再確認する際は、[セットアップ](quickstart-ja.md)と[テスト用指示](test-prompts-ja.md)を使い、モデル・深度・課題・差分・テスト結果を記録してください。過去の一時スクリプトはリポジトリに含まれないため、このガイドから同一ハーネスをそのまま再実行はできません。

以下は未検証、または本テストでは保証しません。

- Cursorへインストールした状態のChat／MCP／Skill連携とライフサイクル。
- 深度による実モデルの品質差・推論量の差。Strataのソースには指定値の処理がありますが、HTTP成功だけでモデルの効果は確認できません。
- autoの選択の妥当性、再委譲ポリシーをCursorが常に守ること。再委譲回数の制限はSkillの指示で、独立Chat間の強制的な予算管理ではありません。
- 複数の実PCからの同時利用、Windows／macOS、Cursor Remote SSHでの動作。
- Cursor総トークン削減と成功率の改善。レビュー・再指示・失敗時の引取りも含め、同じ課題のCursor単独実行と比較する必要があります。StrataのusageはCursor使用量ではありません。
- 信頼できない利用者間の隔離。共有トークンは信頼できる同一利用者のPC向けで、テストコマンドも利用者権限で動作します。

## 7. 過去の検証記録

以下は実施時点の記録を保存したものです。19件・36件という件数や当時の未検証事項は、それぞれのバージョンの状態です。

# Reasoning-depth update — 2026-10-09

Added task-scoped auto/low/medium/high selection, immutable queue contracts, output-budget forwarding, progress reasons, and explicit unsupported-model handling. Depth tests cover conflicting choices, missing auto decisions, invalid budgets, transport payloads, coordinator isolation, and the full HTTP queue/worker path. The installed Strata source accepts these efforts (high maps to its xhigh template setting); actual model quality differences and Cursor savings remain unmeasured. Auto escalation is a bounded supervisor Skill policy, not a global hard quota across independent Chats. No push performed.

# v0.2 verification — 2026-10-09

- 36 Python unit/integration tests cover variable owners, queue limits, fairness, deduplication, leases, restart recovery, inference admission, isolated worktrees, cancellation, serialized apply and re-review after a base change.
- Mocked extension tests cover registration, secrets, workspace trust, progress and deduplicated notifications. These do not prove installed Cursor behavior.
- Synthetic load: 73 owners × 2 tasks = 146 completions; worker limit 4, inference limit 2, observed inference peak 2, no errors. A second run with 7 owners and inference limit 1 also passed. Synthetic timings do not predict real model throughput.
- Real SSH integration: local Git workspace → temporary coordinator on gdx-spark → existing Strata. Two owners performed research and an edit with worker limit 2 / inference limit 1. Both reached review-ready; the inspected edit was applied and independently tested successfully. Reported Strata usage was 1,278/144 and 3,999/389 input/output tokens. Cursor usage was not measured.

Still requires validation: installed Cursor Chat/MCP discovery and lifecycle, real multiple client computers, Windows/macOS, key-authenticated extension-owned tunnels, and measured Cursor token savings/quality against a Cursor-only baseline. The coordinator only controls requests routed through it. A shared token assumes trusted clients, not multi-user isolation. All v0.2 changes remain unpublished until push is authorized.

---

# v0.1 verification — 2026-10-09

Verified during implementation:

- 19 Python tests passed on Linux x86_64 and DGX Spark Linux aarch64 / Python 3.12. Tests cover isolated edits and reviewed apply, dirty destination/base conflicts, denied paths/symlinks, stale hashes, failing tests, timeouts, cancellation, evidence pagination, MCP initialization/schema, HTTP integration and SSH command construction.
- Node syntax check and mocked extension registration/SecretStorage forwarding/workspace-trust checks passed.
- Supervisor Skill metadata validation passed.
- Official `@vscode/vsce@3.6.2` produced the VSIX.
- **Real SSH + real Strata smoke test:** opened a temporary password-authenticated SSH tunnel to the existing loopback Strata API and connected using `direct` mode. The loaded model was `qwen3.8-flash-next-iq3_s`. In a temporary Git fixture, the worker read code, changed `return a - b` to `return a + b`, and ran the configured tests. The gateway reran final tests; the test harness inspected the patch, applied the exact hash, and independently reran the fixture tests. All passed. Four model turns, 4,604 input and 517 output Strata tokens were reported by the API.

The smoke-test token figures are **Strata tokens**, not Cursor usage, and the fixture is deliberately small. This is not a benchmark or a general coding-quality claim.

Not yet verified:

- Actual installed Cursor Chat discovery, Skill loading and lifecycle behavior (extension tests use mocks).
- Real key/agent authentication with the extension-owned SSH tunnel (command construction/cleanup tested; the live smoke used a manually managed password tunnel).
- Windows, macOS, or Cursor Remote SSH extension-host behavior.
- Client hardware, concurrent clients, or global Spark admission control.
- Cursor token savings or accuracy improvement compared with Cursor-only work.

The CI workflow repeats offline/local fixture tests and packages a VSIX. It does not connect to a private Strata server.
