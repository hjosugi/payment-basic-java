# 決済障害のrunbook

## UNKNOWNが増えた

1. Incident担当を決め、開始時刻と顧客影響を記録する。
2. `/metrics`で未確定件数、Breaker、同時実行数、HTTPエラーを確認する。
3. `/admin/breaks`で`transport_or_timeout`、`provider_http`、`provider_mismatch`などを区別する。
4. 決済会社側の処理結果を内部payment IDで確認する。キーを変更して再請求しない。
5. Providerが正常なら`python3 scripts/reconcile.py --once`を実行する。
6. 不一致が残る場合は担当が証拠を確認する。成功を推測してDBを書き換えない。
7. `UNKNOWN/PENDING`解消、台帳の重複なし、明細照合結果を確認して回復とする。

模擬障害は`python3 scripts/demo.py`で再現できます。APIとfixtureの起動が前提です。

## DB停止・容量不足

DBへ操作を予約できなければ、APIは新しいProvider呼び出しを開始しません。Providerで成功後に最終保存だけ失敗した場合はPENDINGが残り、再起動後に照合します。DBファイルだけでなくSQLite WALを含む正しいバックアップを使います。

一時的なSQLiteの書き込み待ちは最大5秒設定です。TypeScriptでは同期DB APIがイベントループを止めるため、ローカル学習向けの設計です。実運用のイベントループ遅延、DB pool、共有DBへの移行は別途評価します。

## 429が増えた

Providerが遅い場合はMAX_INFLIGHTを増やす前に原因を確認します。並行度を増やしてもProviderの処理能力やDBが増えるわけではありません。クライアントは`Retry-After`を読み、同じキーで再試行します。リクエストが予約済みの場合は202になり、GETまたは照合で進捗確認します。

## 明細照合

```bash
python3 scripts/export_statement.py --db provider.db --output statement.csv
python3 scripts/settlement.py --db payments.db --statement statement.csv
```

終了コード0は差分なし、2は差分あり。実行結果と入力ハッシュはDBに保存されます。全教材DBと比較するため、入力はそのProvider DBの完全な明細にします。期間限定明細や別実験のDBを混ぜません。`settlement_breaks`は実行時点の履歴なので、過去行を書き換えて消しません。

## 運用上の境界

管理APIはローカル固定トークンを使います。`X-Merchant-Id`は教材用の識別子で、認証ではありません。全サーバーは127.0.0.1にbindします。公開サービスにする際は認証済みprincipalから加盟店を決定し、管理者権限、TLS、入口の接続数・本文受信期限、監査を追加します。

Javaの軽量HTTPサーバーはインターネット向けの入口保護を備えた構成ではありません。仮想スレッド数は無制限に増やせるという意味ではなく、外部呼び出しには別のSemaphore制限があります。

## 振り返り

`ops/retrospective-template.md`を複製し、原因となった前提と改善の検証方法を記載します。模擬障害の再現手順をテストへ残します。
