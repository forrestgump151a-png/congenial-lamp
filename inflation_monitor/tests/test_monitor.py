"""通知判定ロジックのテスト。"""

from inflation_monitor import config
from inflation_monitor.fetchers.base import Observation
from inflation_monitor.monitor import evaluate, latest_obs


def make_entry(observations=None):
    return {"label": "x", "observations": observations or [], "consecutive_failures": 0}


def obs(date, value, **kw):
    return Observation(date=date, value=value, source_url="u", **kw)


def test_first_bei_observation_no_alert():
    entry = make_entry()
    alerts = evaluate("bei_10y", entry, obs("2026-08-07", 2.05), None)
    assert alerts == []
    assert latest_obs(entry)["value"] == 2.05


def test_bei_threshold_cross_down():
    entry = make_entry([obs("2026-08-06", 2.03).to_dict()])
    alerts = evaluate("bei_10y", entry, obs("2026-08-07", 1.97), None)
    assert any("下抜け" in a for a in alerts)


def test_bei_small_move_no_alert():
    entry = make_entry([obs("2026-08-06", 2.05).to_dict()])
    alerts = evaluate("bei_10y", entry, obs("2026-08-07", 2.06), None)
    assert alerts == []


def test_bei_big_move_alert():
    entry = make_entry([obs("2026-08-06", 2.05).to_dict()])
    alerts = evaluate("bei_10y", entry, obs("2026-08-07", 2.20), None)
    assert any("大きな変動" in a for a in alerts)


def test_quarterly_new_release_alert_with_diff():
    entry = make_entry([obs("2026-06-01", 2.6).to_dict()])
    alerts = evaluate("tankan_5y", entry, obs("2026-09-01", 2.7), None)
    assert any("新しい公表" in a and "+0.1pt" in a for a in alerts)


def test_quarterly_same_release_no_alert():
    entry = make_entry([obs("2026-06-01", 2.6).to_dict()])
    alerts = evaluate("tankan_5y", entry, obs("2026-06-01", 2.6), None)
    assert alerts == []


def test_survey_crossing_50():
    entry = make_entry([obs("2026-03-01", 49.0).to_dict()])
    alerts = evaluate("survey_5y_kanari", entry, obs("2026-06-01", 51.3), None)
    assert any("50.0" in a and "上抜け" in a for a in alerts)


def test_failure_alert_after_threshold():
    entry = make_entry()
    for i in range(config.FAILURE_ALERT_AFTER - 1):
        assert evaluate("bei_10y", entry, None, "boom") == []
    alerts = evaluate("bei_10y", entry, None, "boom")
    assert any("連続で失敗" in a for a in alerts)
    # 4回目以降は再通知しない（同一障害でのスパム防止）
    assert evaluate("bei_10y", entry, None, "boom") == []


def test_success_resets_failures():
    entry = make_entry()
    evaluate("bei_10y", entry, None, "boom")
    evaluate("bei_10y", entry, obs("2026-08-07", 2.0), None)
    assert entry["consecutive_failures"] == 0
