"""②日銀短観「企業の物価見通し」5年後・物価全般・全規模全産業の取得。

出所: 日本銀行「短観（企業の物価見通し）」
      https://www.boj.or.jp/statistics/tk/bukka/<年>/ に四半期ごとの公表物
      （例: tkc2506.pdf / 同名の Excel）が置かれる。ファイル名の4桁 YYMM
      （調査年月）で最新公表を判定する。

抽出は Excel から「全規模合計×全産業」の行と「5年後」の列の交点を探す
ヒューリスティック。失敗しても「新規公表の検知」だけは成立させ、
value=None で通知する（リンク先を人が確認できれば監視目的は果たせる）。
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
    today_jst,
)

BASE = "https://www.boj.or.jp"
PLAUSIBLE_RANGE = (-2.0, 10.0)

# 公表物ファイル名に含まれる調査年月コード（例 2506 = 2025年6月調査）
CODE_RE = re.compile(r"(?:tk|bukka)[a-z]*?(\d{4})\.(?:htm|html|pdf|xlsx?|zip)", re.IGNORECASE)


def _index_urls() -> list[str]:
    year = today_jst().year
    return [
        f"{BASE}/statistics/tk/bukka/{y}/index.htm" for y in (year, year - 1)
    ] + [f"{BASE}/statistics/tk/bukka/index.htm"]


def _valid_code(code: str) -> bool:
    month = int(code[2:])
    return month in (3, 6, 9, 12)


def fetch_latest() -> Observation:
    links: list[str] = []
    errors: list[str] = []
    for index_url in _index_urls():
        try:
            links.extend(find_links(get_html(index_url), index_url))
        except Exception as exc:  # noqa: BLE001 - 年ページが無い場合もある
            errors.append(str(exc))
    coded = [(m.group(1), url) for url in links if (m := CODE_RE.search(url)) and _valid_code(m.group(1))]
    if not coded:
        raise FetchError("短観物価見通し: 公表物リンクが見つかりません / " + " ; ".join(errors[:2]))

    latest_code = max(code for code, _ in coded)
    year = 2000 + int(latest_code[:2])
    month = int(latest_code[2:])
    obs_date = f"{year}-{month:02d}-01"
    label_note = f"{year}年{month}月調査"

    candidate_urls = [url for code, url in coded if code == latest_code]
    excel_urls = [u for u in candidate_urls if re.search(r"\.xlsx?$", u, re.IGNORECASE)]
    # 一覧ページに Excel が無ければ、公表ページ(htm)の中から探す
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
            import pandas as pd

            sheets = pd.read_excel(
                __import__("io").BytesIO(http_get(excel_url).content),
                sheet_name=None,
                header=None,
            )
            value, note = extract_tankan_5y(sheets)
            return Observation(
                date=obs_date,
                value=value,
                source_url=excel_url,
                note=f"{label_note}。{note}".strip("。 ") + "。",
                confidence="high" if note == "" else "low",
            )
        except Exception:  # noqa: BLE001 - 次の候補ファイルへ
            continue

    # 抽出失敗でも公表検知としては返す
    return Observation(
        date=obs_date,
        value=None,
        source_url=source_url,
        note=f"{label_note}。自動抽出に失敗しました。リンク先で値を確認してください。",
        confidence="low",
    )


def extract_tankan_5y(sheets: dict) -> tuple[float, str]:
    """「全規模合計×全産業」行 ×「5年後」列（平均）の値を探す。

    戻り値: (値, 注記)。注記が空文字なら高信頼。見つからなければ FetchError。
    """
    for frame in sheets.values():
        grid = frame.values.tolist()
        n_rows = len(grid)
        if n_rows == 0:
            continue
        n_cols = max(len(r) for r in grid)

        # 「5年後」を含む列（ヘッダーは上部20行以内を想定）
        five_year_cols = [
            c
            for c in range(n_cols)
            for r in range(min(20, n_rows))
            if c < len(grid[r]) and "5年後" in normalize_text(grid[r][c])
        ]
        if not five_year_cols:
            continue

        # 「全産業」を含む行。同じ行か直近上方に「全規模」があるものを優先
        zen_sangyo_rows = [
            r for r in range(n_rows)
            if any("全産業" in normalize_text(cell) for cell in grid[r])
        ]
        if not zen_sangyo_rows:
            continue

        def near_zenkibo(r: int) -> bool:
            for rr in range(max(0, r - 15), r + 1):
                if any("全規模" in normalize_text(cell) for cell in grid[rr]):
                    return True
            return False

        ordered_rows = [r for r in zen_sangyo_rows if near_zenkibo(r)] or zen_sangyo_rows
        used_fallback_row = not any(near_zenkibo(r) for r in zen_sangyo_rows)

        for row_idx in ordered_rows:
            for col_idx in sorted(set(five_year_cols)):
                # ヘッダー列とその近傍（結合セル対応で +0..+2）を試す
                for offset in (0, 1, 2):
                    c = col_idx + offset
                    if c >= len(grid[row_idx]):
                        continue
                    value = as_number(grid[row_idx][c])
                    if value is not None and PLAUSIBLE_RANGE[0] <= value <= PLAUSIBLE_RANGE[1]:
                        note = (
                            "「全規模」表記を確認できない行から抽出しました。原典を確認してください。"
                            if used_fallback_row
                            else ""
                        )
                        return round(value, 2), note

    raise FetchError("短観物価見通し: 5年後×全産業の値を抽出できませんでした")
