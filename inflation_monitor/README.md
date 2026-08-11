# 日本のインフレ期待モニター

日本のインフレ期待を示す3指標を自動で定点観測し、動きがあったときに GitHub Issue で通知するツールです。

## 監視対象

| # | 指標 | 頻度 | 出所 |
|---|---|---|---|
| ① | **BEI**（10年ブレークイーブンインフレ率） | 日次（営業日） | [日本相互証券 ヒストリカルデータ](https://www.bb.jbts.co.jp/ja/historical/marketdata05.html) |
| ② | **日銀短観「企業の物価見通し」** 物価全般・5年後・全規模全産業 | 四半期（1/4/7/10月公表） | [日本銀行](https://www.boj.or.jp/statistics/tk/bukka/index.htm) |
| ③ | **生活意識に関するアンケート調査** 5年後の物価「かなり上がる」回答割合 | 四半期 | [日本銀行](https://www.boj.or.jp/research/o_survey/index.htm) |

## 仕組み

```
GitHub Actions（平日 09:15 JST）
  └─ python -m inflation_monitor.monitor run
       ├─ 各出所ページを巡回 → 最新の Excel を取得・解析
       ├─ data/history.json に履歴を追記（コミットで永続化）
       ├─ data/latest.md にダッシュボードを再生成
       └─ 通知条件に該当 → GitHub Issue を自動作成
```

### 通知条件（`config.py` で調整可能）

- **②③の新しい四半期公表を検知**したとき（前回との差分つき）
- **BEI が 2.0% をまたいだ**とき（上抜け・下抜け）
- **BEI が1観測で ±0.10pt 以上**動いたとき
- 生活意識アンケート「かなり上がる」が **50% をまたいだ**とき
- 取得が **3回連続で失敗**したとき（サイト構成変更の検知）
- 四半期指標が **110日以上更新されない**とき（公表の取り逃し検知）

GitHub の通知設定（Watch → Issues）をオンにすれば、Issue 作成時にメール/プッシュ通知が届きます。

## 有効化の手順

1. このブランチをデフォルトブランチにマージする（`schedule` 実行はデフォルトブランチのワークフローのみ動きます）
2. リポジトリの Actions が有効なことを確認
3. 動作確認は Actions タブ → `Japan Inflation Expectations Monitor` → `Run workflow`（手動実行）

## ローカル/手動での利用

```bash
pip install -r inflation_monitor/requirements.txt

# 3指標を取得して履歴・ダッシュボードを更新
python -m inflation_monitor.monitor run

# 1指標のみ
python -m inflation_monitor.monitor run --only bei      # bei / tankan / survey

# 自動抽出に失敗したときなどの手動登録
python -m inflation_monitor.monitor add tankan_5y 2026-10-01 2.7 --note "2026年9月調査"

# テスト
pytest inflation_monitor/tests/
```

## 注意事項・限界

- **Excel のレイアウト変更に対する頑健性は完全ではありません。** 抽出はヒューリスティック（「5年後」「全産業」「かなり上がる」等のラベル探索）で行い、失敗した場合も「新規公表の検知」だけは Issue で通知します（`値の自動抽出に失敗` と表示。リンク先で確認のうえ `add` コマンドで手動登録できます）。
- 初回の Actions 実行では、実データに対する抽出結果を一度目視確認してください（Issue / `data/latest.md` に出ます）。
- 日本相互証券・日本銀行のデータは各サイトの利用条件の範囲（個人の調査・研究目的）で利用してください。取得は1日1回・数リクエストのみで、サーバーに負荷はかけません。
- `data/history.json` には初期値として 2026年6月調査分（短観 +2.6%、アンケート 51.3%）を登録済みです。次回10月の公表で自動的に新規検知の通知が出ます。
