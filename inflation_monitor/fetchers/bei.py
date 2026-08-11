"""①BEI（10年ブレークイーブンインフレ率）の取得。

出所: 日本相互証券「ヒストリカルデータ > BEI（ブレークイーブンインフレ率）の推移」
      https://www.bb.jbts.co.jp/ja/historical/marketdata05.html

ページ上の Excel ファイル（日付 + 利回り + BEI の時系列）をダウンロードし、
最新日付の行の BEI 値を返す。列構成の変更に備えて「日付列の右側にある
最右端の数値列」を BEI とみなすヒューリスティックで抽出する。
"""

from __future__ import annotations

import datetime as dt
import io
import re

from .base import FetchError, Observation, as_date, as_number, find_links, get_html, http_get

INDEX_URL = "https://www.bb.jbts.co.jp/ja/historical/marketdata05.html"

# BEI としてあり得る範囲（%）。利回り列を誤って拾った場合の暴走を防ぐ緩い検査。
PLAUSIBLE_RANGE = (-3.0, 6.0)


def fetch_latest() -> Observation:
    html = get_html(INDEX_URL)
    excel_links = [
        url for url in find_links(html, INDEX_URL)
        if re.search(r"\.xlsx?(\?.*)?$", url, flags=re.IGNORECASE)
    ]
    if not excel_links:
        raise FetchError(f"BEI: Excelリンクが見つかりません: {INDEX_URL}")

    # ファイル名に bei を含むものを優先。無ければ全候補を試す。
    preferred = [u for u in excel_links if "bei" in u.lower()] or excel_links

    best: Observation | None = None
    errors: list[str] = []
    for url in preferred[:6]:
        try:
            obs = parse_bei_excel(http_get(url).content, url)
        except Exception as exc:  # noqa: BLE001 - 候補を順に試す
            errors.append(f"{url}: {exc}")
            continue
        if best is None or obs.date > best.date:
            best = obs
    if best is None:
        raise FetchError("BEI: どのExcelも解析できませんでした / " + " ; ".join(errors))
    return best


def parse_bei_excel(content: bytes, source_url: str) -> Observation:
    import pandas as pd

    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    return extract_latest_bei(sheets, source_url)


def extract_latest_bei(sheets: dict, source_url: str) -> Observation:
    """全シートを走査し、日付行の最右端の数値を BEI として最新日を返す。"""
    latest_date: dt.date | None = None
    latest_value: float | None = None
    value_col_counts: set[int] = set()

    for frame in sheets.values():
        for row in frame.itertuples(index=False):
            cells = list(row)
            date = None
            date_idx = None
            for idx in range(min(3, len(cells))):  # 日付は先頭3列以内を想定
                date = as_date(cells[idx])
                if date is not None:
                    date_idx = idx
                    break
            if date is None:
                continue
            numbers = [
                (idx, as_number(cell))
                for idx, cell in enumerate(cells[date_idx + 1:], start=date_idx + 1)
                if as_number(cell) is not None
            ]
            if not numbers:
                continue
            col, value = numbers[-1]  # 最右端の数値列 = BEI（末尾列に置かれる慣行）
            if not (PLAUSIBLE_RANGE[0] <= value <= PLAUSIBLE_RANGE[1]):
                continue
            value_col_counts.add(col)
            if latest_date is None or date > latest_date:
                latest_date = date
                latest_value = value

    if latest_date is None or latest_value is None:
        raise FetchError("BEI: 日付+数値の行を検出できませんでした")

    confidence = "high" if len(value_col_counts) == 1 else "low"
    note = "" if confidence == "high" else "値の列位置が行によって揺れています。原典を確認してください。"
    return Observation(
        date=latest_date.isoformat(),
        value=round(latest_value, 3),
        source_url=source_url,
        note=note,
        confidence=confidence,
    )
