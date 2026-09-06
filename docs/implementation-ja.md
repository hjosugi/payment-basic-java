# 実装を読む順序

最初にHTTP層の細かい処理を全部読む必要はありません。`schema.sql`、決済service、store、Provider、HTTP入口、テストの順に読むと、何を守るコードなのか追いやすくなります。

| 責務 | TypeScript | Go | Java |
| --- | --- | --- | --- |
| HTTP入口・validation | `src/server.ts` | `main.go` | `Main.java` |
| 決済・復旧の流れ | `src/service.ts` | `service.go` | `PaymentService.java` |
| 永続化・台帳 | `src/store.ts` | `store.go` | `Store.java` |
| 依存先呼び出し | `src/resilience.ts` | `resilience.go` | `Provider.java` |
| Circuit Breaker | `src/resilience.ts` | `resilience.go` | `CircuitBreaker.java` |
| Metrics | `src/server.ts` | `main.go` | `Metrics.java` |
| DB制約 | `schema.sql` | `schema.sql` | `schema.sql` |
| ブラックボックステスト | `tests/contract.py` | `tests/contract.py` | `tests/contract.py` |

Javaのソースは`src/main/java/dev/payment/`配下です。3言語のAPI契約は共通ですが、無理に同じクラス構造へ揃えず、それぞれの並行処理とDB APIを使います。

## createの流れ

1. 加盟店、キー、金額、通貨、余分なプロパティ、本文サイズを検証する。
2. 外部処理が満杯なら429を返す。
3. DBへPENDINGをINSERTする。加盟店とキーの競合は既存行を使う。
4. 既存行の金額・通貨と一致しなければ409を返す。
5. INSERTした呼び出しだけがProviderのPOSTを行う。
6. 応答を検証し、SUCCEEDED/DECLINEDまたはUNKNOWNを保存する。
7. 現在のDB状態を読み返して返す。

同時リクエストを全て成功まで待たせません。処理中なら202 PENDINGを返し、利用者はGETで追跡します。成功後の同じPOSTは200、初回で即確定すれば201です。

## DBの責務

`payments`の一意制約が、同じ操作の所有権を確定します。HTTP外部呼び出し中はDBトランザクションを保持しません。

`finish`では未確定状態からだけ更新できます。SUCCEEDED/DECLINEDをUNKNOWNに戻しません。SUCCEEDEDなら台帳の2行を同じトランザクションで追加します。台帳も一意制約で重複しません。

`recordBreak`も未確定状態に限ってINSERTします。照合で既に確定したあとに古いtimeoutが帰ってきても、新しい未解決breakを残さないためです。テスト`test_late_timeout_does_not_reopen_resolved_break`で確認します。

## 言語ごとの判断

### TypeScript

Node.js 24のTypeScript型除去を利用し、`node src/server.ts`で実行します。これは型検査ではありません。`npm run typecheck`を別に実行します。`erasableSyntaxOnly`を使い、parameter propertiesなど実行時の変換が必要な構文を避けています。

DBは`node:sqlite`の`DatabaseSync`です。Node 24系では実験的APIの表示が出る場合があります。同期SQLは小規模ローカル教材として採用し、大量の並行アクセス向けの性能推奨ではありません。

依存先のHTTPは非同期ですが、カウンター更新はawaitの前に同期的に行います。そのため同一イベントループ内のProvider枠管理ではmutexを使いません。複数プロセス間ではカウンターは共有されず、DB制約とProviderのキーで重複副作用を防ぎます。

公式: [TypeScript in Node](https://nodejs.org/docs/latest-v24.x/api/typescript.html), [SQLite API](https://nodejs.org/api/sqlite.html)

### Go

HTTPは標準`net/http`、DBは`database/sql`とpure-Go SQLite driverです。DB接続は1本に設定し、SQLiteの書き込み特性とPRAGMA設定を単純に扱います。

外部同時実行数はbuffered channelで制限します。Breakerの内部状態はmutex、reconciliationの同時実行フラグはatomicです。Provider側の期限付きcontextは、クライアントが切断しても保存済み操作の結果を書き戻せるよう独立させています。

`go test -race ./...`は単体テストで実行された範囲のraceを検出します。システム全体のすべてのraceが存在しないことを証明するものではありません。HTTP共通テストでは同時リクエストと2プロセスのDB競合を別途実行します。

公式: [modernc.org/sqlite](https://pkg.go.dev/modernc.org/sqlite), [net/http](https://pkg.go.dev/net/http), [database/sql](https://pkg.go.dev/database/sql)

### Java

Java 21のHttpServer、HttpClient、virtual threadsを使います。Spring Bootを使わず、HTTP・transaction・deadlineの境界を直接追えるようにしました。JSONはJackson、SQLiteはXerial JDBCです。

virtual threadsでも並行実行枠は別に必要です。SemaphoreでProviderの同時実行を制限し、Storeは1本のJDBC connectionをsynchronizedメソッドで保護します。DBの保護中にHTTP呼び出しを行いません。

HttpClientの非同期Futureはレスポンス本文完了まで期限付きで待ちます。本文サイズは独自Subscriberで16KiBに制限します。標準のrequest timeoutだけでどのフェーズまで制限されるかを曖昧にしないためです。

公式: [Java HttpClient](https://docs.oracle.com/en/java/javase/21/docs/api/java.net.http/java/net/http/HttpClient.html), [SQLite JDBC](https://github.com/xerial/sqlite-jdbc), [Jackson](https://github.com/FasterXML/jackson-databind)

## 意図的に実装していないもの

- 実際のカード決済、カード情報保管、PCI対応、銀行送金。
- authorization/captureの分離、refund、chargeback、通貨換算、手数料。
- 本番認証、権限制御、Webhook署名検証、イベントinbox/outbox。
- 分散DB、HA、スケジュールの永続化、Providerごとのkey retention管理。
- 本番向けの接続・スレッド・DB待ち行列の包括的な容量制御。

これらは「完成済み」と見なさず、面接の拡張設計として説明します。`interview-en.md`のFollow-upに回答例があります。

## 次に拡張するなら

1. Providerアダプターにkey retentionと照会の整合性契約を持たせる。
2. 期限切れのUNKNOWNを自動再送せず、手動確認へ送る。
3. 個別のnext_attempt_atとretry budgetを持つworkerを追加する。
4. 100件の固定順バッチで古い不良レコードが後続を飢餓させないようにする。
5. PostgreSQLとoutboxを使い、操作作成と作業通知を原子的に保存する。
6. Webhookを追加する場合、署名、イベント重複、順序逆転をテストする。

本教材の`reconcile.py`はバッチ単位の指数backoffとjitterです。プロセスを再起動するとbackoff回数はリセットされます。個別retry budgetや永続スケジュールの代替ではありません。
