"""抽出ヒューリスティックのテスト（公表Excelを模した合成データ）。"""

import datetime as dt

import pandas as pd
import pytest

from inflation_monitor.fetchers.base import as_date, as_number, normalize_text
from inflation_monitor.fetchers.bei import extract_latest_bei
from inflation_monitor.fetchers.survey import extract_survey_kanari_5y
from inflation_monitor.fetchers.tankan import extract_tankan_5y


def test_as_number():
    assert as_number("2.6") == 2.6
    assert as_number("△0.5") == -0.5
    assert as_number(2) == 2.0
    assert as_number("全産業") is None
    assert as_number(float("nan")) is None
    assert as_number(None) is None


def test_as_date():
    assert as_date("2026/8/7") == dt.date(2026, 8, 7)
    assert as_date("2026年8月7日") == dt.date(2026, 8, 7)
    assert as_date(dt.datetime(2026, 8, 7, 15, 0)) == dt.date(2026, 8, 7)
    assert as_date("2.6") is None
    assert as_date("BEI") is None


def test_normalize_text_fullwidth():
    assert "5年後" in normalize_text("５年後の物価")
    assert normalize_text("全 産 業") == "全産業"


def test_extract_bei_latest_row():
    frame = pd.DataFrame(
        [
            ["日付", "物価連動国債利回り", "10年利付国債利回り", "BEI"],
            [dt.datetime(2026, 8, 6), -0.45, 1.60, 2.05],
            [dt.datetime(2026, 8, 7), -0.44, 1.62, 2.06],
        ]
    )
    obs = extract_latest_bei({"Sheet1": frame}, "http://example.com/bei.xlsx")
    assert obs.date == "2026-08-07"
    assert obs.value == 2.06
    assert obs.confidence == "high"


def test_extract_bei_rejects_no_dates():
    frame = pd.DataFrame([["a", "b"], ["c", "d"]])
    with pytest.raises(Exception):
        extract_latest_bei({"Sheet1": frame}, "u")


def test_extract_tankan_5y():
    frame = pd.DataFrame(
        [
            ["物価全般の見通し（平均）", None, None, None],
            [None, "1年後", "3年後", "5年後"],
            ["大企業", None, None, None],
            ["全産業", 2.4, 2.3, 2.2],
            ["全規模合計", None, None, None],
            ["全産業", 2.8, 2.7, 2.6],
        ]
    )
    value, note = extract_tankan_5y({"Sheet1": frame})
    assert value == 2.6
    assert note == ""


def test_extract_survey_kanari_5y_takes_rightmost():
    frame = pd.DataFrame(
        [
            ["Q. 1年後の物価", None, None],
            ["かなり上がる", 30.0, 31.5],
            ["Q. ５年後の物価", None, None],
            ["かなり上がる", 49.8, 51.3],
            ["少し上がる", 30.0, 29.0],
        ]
    )
    value, note = extract_survey_kanari_5y({"Sheet1": frame})
    assert value == 51.3


def test_extract_survey_fails_without_block():
    frame = pd.DataFrame([["1年後", None], ["かなり上がる", 30.0]])
    with pytest.raises(Exception):
        extract_survey_kanari_5y({"Sheet1": frame})
