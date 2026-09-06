# ハンズオン

各言語のREADMEでビルドしてから実行します。コマンドは各実装リポジトリのルートで実行します。Python 3.10以上を用意してください。

## 1. Providerを起動

ターミナルA:

```bash
python3 fixtures/provider.py
```

`provider.db`へ結果が残ります。模擬決済会社は127.0.0.1:9090で起動します。API側は別の`payments.db`を使用するため、片側だけ成功する状態を再現できます。

## 2. 決済APIを起動

ターミナルBではREADME記載の`npm start`、`go run .`、または`java -jar ...`を実行します。デフォルトのAPIは127.0.0.1:8080です。3言語を同時比較する場合はPORTとDB_PATHを分けます。

## 3. 応答消失から回復

ターミナルC:

```bash
python3 scripts/demo.py
```

順に、Providerをcommit後の遅延モードへ変更、決済作成、同じキーで再試行、Provider正常化、照合、GET、Provider件数確認を行います。

期待する状態:

| 操作 | 結果 |
| --- | --- |
| 最初のPOST | 202 UNKNOWN |
| 同じキーの再試行 | 同じid、202 UNKNOWN |
| 照合後のGET | 200 SUCCEEDED |
| Provider | この操作に対応するchargeは1件 |

以前の実験データがある場合、Providerの総件数は1にはなりません。実験前後の増分が1であることを確認してください。テストは毎回一時DBを使います。

## 4. 定期的な復旧worker

```bash
python3 scripts/reconcile.py
```

Ctrl+Cで停止します。最初のバッチは即実行し、その後1〜60秒の範囲で指数backoffとjitterを使います。キーを変えずに結果照会を行い、照会で存在しないと確認できた操作だけ同じIDで再送します。

## 5. 負荷を変える

```bash
python3 scripts/load.py --requests 100 --concurrency 8
python3 scripts/load.py --requests 100 --concurrency 32
```

これは模擬Providerに100個ずつ別の決済操作を作ります。req/sだけでなくHTTPの429/202とSUCCEEDED件数を比較します。PCやDB、プロセス起動直後のウォームアップによって測定値は変わります。

## 6. 明細を照合

```bash
python3 scripts/export_statement.py --output statement.csv
python3 scripts/settlement.py --statement statement.csv
```

1行のamountを変更して再実行すると`statement_mismatch`が残ります。行を削除すると`missing_provider_record`、未知のIDを追加すると`provider_only_record`、同じIDを二度書くと`duplicate_statement_row`です。照合は金額や決済状態を勝手に修正しません。

## 7. 故障テスト

READMEのcontract testコマンドを実行すると、模擬ProviderとAPIを自動起動し、終了時に停止します。8080/9090固定ではなく空きポートを使うため、手動起動したデモと分離できます。

テストに含まれるもの:

- 同時リクエストと2プロセスの同じキー競合。
- 同じキーで異なる金額、加盟店ごとのキー範囲。
- Providerの成功直後のtimeout、処理中の強制終了、再起動。
- 照合成功後に戻る古いtimeout、重複照合。
- BreakerのOPENと回復、容量超過、429、正常なDECLINED。
- 本文が途中で止まるHTTP、不正応答、Providerの金額不一致。
- 照会503では再送しないこと、明細の4種の差分保存。
- 入力validation、管理トークン、metricsとJSONログ。

## 8. 面接練習

1. `interview-en.md`の30秒回答を声に出す。
2. 応答消失のsequence diagramを見ずに描く。
3. 「なぜ新しいキーで再送しないか」を1文で答える。
4. 2分回答を話し、SQLiteをPostgreSQLへ替える理由を説明する。
5. ULID、rate limiter、Breaker、bulkheadの役割の違いを説明する。
