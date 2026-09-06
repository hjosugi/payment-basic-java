# payment-basic-java

Javaで実装する、障害に強い決済APIの学習プロジェクト。日本語解説・英語面接スクリプト・故障テスト付きです。

## 必要環境

JDK 21以上、Maven 3.9以上、Python 3.10以上。実際の決済資格情報は不要です。

## ビルドと単体テスト

```bash
mvn verify
```

## 起動

ターミナルA:

```bash
python3 fixtures/provider.py
```

ターミナルB:

```bash
java -jar target/payment-basic-java-0.1.0.jar
```

ターミナルC:

```bash
python3 scripts/demo.py
```

APIは127.0.0.1:8080、模擬Providerは127.0.0.1:9090。`payments.db`と`provider.db`へ永続化します。`demo.py`は応答消失からの復旧を実行します。

## 共通の障害テスト

上のビルド後に実行します。API・Providerを別途起動する必要はありません。

```bash
python3 tests/contract.py -- java -jar target/payment-basic-java-0.1.0.jar
```

WindowsではPython実行名が`python`の場合があります。Goバイナリは`payment-server.exe`としてビルドし、テストコマンドも対応するパスへ変更します。

## API

| Method | Path | 用途 |
| --- | --- | --- |
| POST | `/payments` | 決済操作を作成・再取得 |
| GET | `/payments/{id}` | 現在状態を取得 |
| POST | `/admin/reconcile` | 未確定操作を最大100件復旧 |
| GET | `/admin/breaks` | 保存済み照合問題を取得 |
| GET | `/metrics` | Prometheus形式のmetrics |
| GET | `/health` | Liveness |

POSTのヘッダーは`X-Merchant-Id: demo`と`Idempotency-Key: order-1`、本文は次のJSONです。

```json
{"amount":1000,"currency":"JPY"}
```

JPYの1000は1000円、USDの1000は1000 centsです。整数の最小通貨単位で1〜1,000,000,000を受け付けます。GETも`X-Merchant-Id`が必要です。管理APIは`X-Admin-Token`を使います。

| Status | 意味 |
| --- | --- |
| 201 | 初回で確定。bodyのstatusはSUCCEEDEDまたはDECLINED |
| 200 | 既存結果、取得、管理処理の完了 |
| 202 | PENDINGまたはUNKNOWN。Retry-AfterとLocationを返す |
| 400 | 不正な入力 |
| 403 | 管理トークンが一致しない |
| 404 | 対象がない、または別加盟店の決済 |
| 409 | 同じキーでamountまたはcurrencyが異なる |
| 429 | 実行枠が満杯。Retry-Afterを返す |
| 500 | 永続化または内部のエラー |

初回202の後、同じPOSTが200へ変わることがあります。このAPIは最初のHTTPレスポンスのキャッシュではなく、同じ業務操作の現在状態を返します。

## 設定

| 環境変数 | 既定値 | 用途 |
| --- | --- | --- |
| PORT | 8080 | APIポート |
| DB_PATH | payments.db | ローカルDB |
| PROVIDER_URL | http://127.0.0.1:9090 | 模擬Provider |
| PROVIDER_TIMEOUT_MS | 300 | 外部呼び出し1回の予算 |
| MAX_INFLIGHT | 8 | Providerの同時実行上限 |
| ADMIN_TOKEN | local-admin | ローカル管理API用 |

3言語を同時起動する場合はPORTとDB_PATHを分けます。キーの有効期限は教材では無期限です。実Providerの期限を越えた安全性は保証しません。

## 学習資料

- [10原則の日本語解説](docs/guide-ja.md)
- [実装の読み方・言語比較](docs/implementation-ja.md)
- [ハンズオン](docs/lab-ja.md)
- [英語面接スクリプト](docs/interview-en.md)
- [障害対応runbook](docs/runbook-ja.md)
- [検証結果](docs/verification.md)
- [OpenAPI](openapi.json)

`fixtures/`と`tests/`は3言語共通のPythonコード、`scripts/`は実験・負荷・照合ツール、`ops/`はアラートとincident/retrospectiveテンプレートです。集中ログ基盤、Prometheus/Alertmanager本体は起動しません。

## 学習用の境界

模擬Providerだけを使います。認証・実カード・返金・Webhook・本番決済会社への接続は実装外です。`X-Merchant-Id`は認証ではありません。127.0.0.1で動かす教材として扱います。詳細は[拡張方針](docs/implementation-ja.md)を参照してください。
