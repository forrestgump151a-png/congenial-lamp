"""③生活意識に関するアンケート調査「5年後の物価はかなり上がる」割合の取得。

出所: 日本銀行「生活意識に関するアンケート調査」
      https://www.boj.or.jp/research/o_survey/index.htm
      公表物のファイル名は ishikiYYMM（YYMM は公表年月。調査月はその前月頃）。

抽出は Excel（集計データ）から「5年後」の設問ブロック内の「かなり上がる」
行を探し、その行の最右端の数値（最新調査回の値）を返すヒューリスティック。
失敗しても新規公表の検知は成立させ、value=None で通知する。
"""

from __future__ import annotations

import re

from .base import (
    FetchError,
    Observation,
    as_number,
    find_links,
    get_html,
    http_get,
    normalize_text,
)

INDEX_URL = "https://www.boj.or.jp/research/o_survey/index.htm"
PLAUSIBLE_RANGE = (0.0, 100.0)

CODE_RE = re.compile(r"ishiki[a-z_]*?(\d{4})[a-z_]*\.(?:htm|html|pdf|xlsx?|zip)", re.IGNORECASE)


def fetch_latest() -> Observation:
    links = find_links(get_html(INDEX_URL), INDEX_URL)
    coded = [(m.group(1), url) for url in links if (m := CODE_RE.search(url))]
    coded = [(c, u) for c, u in coded if 1 <= int(c[2:]) <= 12]
    if not coded:
        raise FetchError(f"生活意識アンケート: 公表物リンクが見つかりません: {INDEX_URL}")

    latest_code = max(code for code, _ in coded)
    release_year = 2000 + int(latest_code[:2])
    release_month = int(latest_code[2:])
    # 調査月は公表月の前月（例: 7月公表 → 6月調査）
    survey_year, survey_month = (
        (release_year - 1, 12) if release_month == 1 else (release_year, release_month - 1)
    )
    obs_date = f"{survey_year}-{survey_month:02d}-01"
    label_note = f"{survey_year}年{survey_month}月調査"

    candidate_urls = [url for code, url in coded if code == latest_code]
    excel_urls = [u for u in candidate_urls if re.search(r"\.xlsx?$", u, re.IGNORECASE)]
    if not excel_urls:
        for page_url in [u for u in candidate_urls if u.lower().endswith((".htm", ".html"))]:
            try:
                excel_urls.extend(
                    u for u in find_links(get_html(page_url), page_url)
                    if re.search(r"\.xlsx?$", u, re.IGNORECASE)
                )
            except Exception:  # noqa: BLE001
                continue

    source_url = excel_urls[0] if excel_urls else candidate_urls[0]
    for excel_url in excel_urls[:4]:
        try:
            import io

            import pandas as pd

            sheets = pd.read_excel(io.BytesIO(http_get(excel_url).content), sheet_name=None, header=None)
            value, note = extract_survey_kanari_5y(sheets)
            return Observation(
                date=obs_date,
                value=value,
                source_url=excel_url,
                note=f"{label_note}。{note}".strip("。 ") + "。",
                confidence="high" if note == "" else "low",
            )
        except Exception:  # noqa: BLE001
            continue

    return Observation(
        date=obs_date,
        value=None,
        source_url=source_url,
        note=f"{label_note}。自動抽出に失敗しました。リンク先で値を確認してください。",
        confidence="low",
    )


def extract_survey_kanari_5y(sheets: dict) -> tuple[float, str]:
    """「5年後」設問ブロック内の「かなり上がる」行の最右端数値を返す。

    集計 Excel は行方向に設問・選択肢、列方向に調査回（時系列）が並ぶ想定。
    最右端の数値 = 最新調査回の値。
    """
    for frame in sheets.values():
        grid = frame.values.tolist()
        five_year_rows = [
            r for r, row in enumerate(grid)
            if any("5年後" in normalize_text(cell) for cell in row)
        ]
        for block_start in five_year_rows:
            # 設問ブロックは通常直後の十数行に選択肢が並ぶ
            for r in range(block_start, min(block_start + 40, len(grid))):
                row = grid[r]
                if not any("かなり上がる" in normalize_text(cell) for cell in row):
                    continue
                numbers = [
                    v for cell in row
                    if (v := as_number(cell)) is not None
                    and PLAUSIBLE_RANGE[0] <= v <= PLAUSIBLE_RANGE[1]
                ]
                if numbers:
                    return round(numbers[-1], 1), ""
    raise FetchError("生活意識アンケート: 5年後×かなり上がる の値を抽出できませんでした")
