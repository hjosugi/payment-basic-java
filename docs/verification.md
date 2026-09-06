# 検証結果

実行日: 2026-09-06。Linuxのローカル環境で実行しました。GitHub Actions上では未実行です。

## 実行結果

| 実装 | 型検査・ビルド | Circuit Breaker単体テスト | 共通HTTP・復旧テスト |
| --- | --- | --- | --- |
| TypeScript | PASS | 2 / 2 | 20 / 20 |
| Go | PASS | 2 / 2（race detector付き） | 20 / 20 |
| Java | PASS | 2 / 2 | 20 / 20 |

合計66件。共通テストは実際のHTTP接続、別プロセス、SQLiteの永続化を使います。各ケースは独立した一時DBで実行します。

特に確認した不変条件は、同じ操作に対するProviderの副作用が1回であること、確定後にUNKNOWNへ戻らないこと、台帳が2行で合計0であることです。2プロセスの同時予約、プロセス強制終了、本文のタイムアウトもテストしました。

## 実行バージョン

- TypeScript: Node.js 24.19.0 / TypeScript 7.0.2 / @types/node 24.13.3
- Go: Go 1.27.1 / modernc.org/sqlite 1.58.0
- Java: Temurin JDK 21.0.12.1+1 / Maven 3.9.11 / sqlite-jdbc 3.53.4.0 / Jackson 2.22.2

バージョンは取得・実行で確認したものです。「常に最新版」という意味ではありません。TypeScriptはpackage-lock.json、Goはgo.mod/go.sum、Javaはpom.xmlにバージョンを固定しています。

## ハンズオンの確認

各言語で`demo.py`、20件・並行度2の`load.py`、`export_statement.py`、`settlement.py`を実行しました。デモのUNKNOWNは照合でSUCCEEDEDへ回復し、負荷の20操作もすべてSUCCEEDED、全件明細照合は差分0でした。これは操作手順の動作確認であり、性能比較や容量保証ではありません。

## 実行していないもの

- GitHubリポジトリの作成・push、GitHub Actionsの実行。
- 実際の決済会社、カード、送金、Webhook、認証連携。
- Prometheus/Alertmanager本体、通知配送。設定ファイルは同梱。
- 長時間・分散地域の負荷試験、HA、障害復旧時間の保証。
- Windows/macOSでの実行、最低対応バージョンすべてのmatrixテスト。

## 再実行

各READMEのbuild・testコマンドを使用してください。`tests/contract.py`は3言語で同じ内容です。模擬ProviderとAPIを自動起動・停止します。GitHub公開用スクリプトはpreviewのみ確認し、実際の新規作成はしていません。
