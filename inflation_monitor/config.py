"""監視ルールの設定。値を変えるだけで通知条件を調整できる。"""

# BEI: 前回観測値からこの幅（%ポイント）以上動いたら通知
BEI_MOVE_ALERT_PP = 0.10

# BEI: この水準（%）をまたいだら通知
BEI_LEVEL_THRESHOLDS = [2.0]

# 生活意識アンケート「かなり上がる」割合: この水準（%）をまたいだら通知
SURVEY_LEVEL_THRESHOLDS = [50.0]

# 四半期指標: 前回観測からこの日数を超えて新データが無ければ「公表遅延？」通知
QUARTERLY_OVERDUE_DAYS = 110

# 取得失敗がこの回数連続したら通知（一時的な障害でのノイズを防ぐ）
FAILURE_ALERT_AFTER = 3

INDICATORS = {
    "bei_10y": {
        "label": "BEI（10年ブレークイーブンインフレ率）",
        "unit": "%",
        "frequency": "daily",
        "source_page": "https://www.bb.jbts.co.jp/ja/historical/marketdata05.html",
        "source_name": "日本相互証券 ヒストリカルデータ",
    },
    "tankan_5y": {
        "label": "日銀短観 企業の物価見通し（物価全般・5年後・全規模全産業）",
        "unit": "%",
        "frequency": "quarterly",
        "source_page": "https://www.boj.or.jp/statistics/tk/bukka/index.htm",
        "source_name": "日本銀行「短観（企業の物価見通し）」",
    },
    "survey_5y_kanari": {
        "label": "生活意識アンケート 5年後の物価「かなり上がる」回答割合",
        "unit": "%",
        "frequency": "quarterly",
        "source_page": "https://www.boj.or.jp/research/o_survey/index.htm",
        "source_name": "日本銀行「生活意識に関するアンケート調査」",
    },
}
