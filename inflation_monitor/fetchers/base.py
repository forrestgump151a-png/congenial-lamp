"""フェッチャー共通のユーティリティ。"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import time
import unicodedata
from urllib.parse import urljoin

import requests

USER_AGENT = (
    "inflation-expectations-monitor/1.0 "
    "(personal research; run on GitHub Actions)"
)


class FetchError(RuntimeError):
    """データ取得・解析の失敗。monitor 側で連続失敗回数を数える。"""


@dataclasses.dataclass
class Observation:
    """1つの観測値。date は指標の基準日（調査月・営業日）を ISO 形式で持つ。"""

    date: str
    value: float | None
    source_url: str
    note: str = ""
    confidence: str = "high"  # "high" | "low"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def http_get(url: str, timeout: int = 60, retries: int = 3) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if resp.status_code == 200:
                return resp
            last_error = FetchError(f"HTTP {resp.status_code}: {url}")
        except requests.RequestException as exc:  # DNS・タイムアウト等
            last_error = exc
        if attempt < retries - 1:
            time.sleep(5 * (attempt + 1))
    raise FetchError(f"取得失敗: {url} ({last_error})")


def get_html(url: str) -> str:
    resp = http_get(url)
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def find_links(html: str, base_url: str) -> list[str]:
    """href をすべて絶対URLにして返す。"""
    hrefs = re.findall(r'href\s*=\s*["\']([^"\'#>]+)["\']', html, flags=re.IGNORECASE)
    return [urljoin(base_url, h.strip()) for h in hrefs]


def normalize_text(cell) -> str:
    """セル値を比較用に正規化（全角→半角、空白除去）。非文字列は空文字。"""
    if cell is None:
        return ""
    if isinstance(cell, float) and cell != cell:  # NaN
        return ""
    text = str(cell)
    return unicodedata.normalize("NFKC", text).replace(" ", "").replace("　", "")


def as_number(cell) -> float | None:
    """セル値を float にできれば返す。日付やラベルは None。"""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        if cell != cell:  # NaN
            return None
        return float(cell)
    if isinstance(cell, str):
        text = unicodedata.normalize("NFKC", cell).strip().replace(",", "")
        text = text.replace("△", "-").replace("▲", "-")  # 和文のマイナス記号
        if re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
            return float(text)
    return None


def as_date(cell) -> dt.date | None:
    """セル値を日付にできれば返す。"""
    if isinstance(cell, dt.datetime):
        return cell.date()
    if isinstance(cell, dt.date):
        return cell
    if isinstance(cell, str):
        text = unicodedata.normalize("NFKC", cell).strip()
        for pattern in (
            r"(\d{4})[/.\-年](\d{1,2})[/.\-月](\d{1,2})日?",
        ):
            m = re.fullmatch(pattern, text)
            if m:
                try:
                    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    return None
    return None


def today_jst() -> dt.date:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
