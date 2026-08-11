"""監視オーケストレーター。

使い方:
    python -m inflation_monitor.monitor run            # 3指標を取得・履歴更新・通知判定
    python -m inflation_monitor.monitor run --only bei # 1指標のみ
    python -m inflation_monitor.monitor add tankan_5y 2026-07-01 2.6  # 手動で値を登録

出力（--data-dir、既定 inflation_monitor/data/）:
    history.json    観測履歴（コミットして永続化する）
    latest.md       最新値ダッシュボード（毎回再生成）
    alert_title.txt / alert_body.md
                    通知すべき事象があった場合のみ生成。
                    GitHub Actions がこのファイルの有無で Issue を立てる。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import config
from .fetchers import bei, survey, tankan
from .fetchers.base import FetchError, Observation, today_jst

DEFAULT_DATA_DIR = Path(__file__).parent / "data"

FETCHERS = {
    "bei_10y": bei.fetch_latest,
    "tankan_5y": tankan.fetch_latest,
    "survey_5y_kanari": survey.fetch_latest,
}

ALIASES = {"bei": "bei_10y", "tankan": "tankan_5y", "survey": "survey_5y_kanari"}


# ---------------------------------------------------------------- state I/O

def load_history(data_dir: Path) -> dict:
    path = data_dir / "history.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        key: {"label": meta["label"], "observations": [], "consecutive_failures": 0}
        for key, meta in config.INDICATORS.items()
    }


def save_history(data_dir: Path, history: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def latest_obs(entry: dict) -> dict | None:
    return entry["observations"][-1] if entry["observations"] else None


# ---------------------------------------------------------------- alert rules

def crossed(thresholds: list[float], prev: float, new: float) -> list[float]:
    return [t for t in thresholds if (prev < t <= new) or (prev >= t > new)]


def evaluate(key: str, entry: dict, new_obs: Observation | None, error: str | None) -> list[str]:
    """新観測を履歴に反映し、通知メッセージのリストを返す。"""
    alerts: list[str] = []
    meta = config.INDICATORS[key]
    label = meta["label"]

    if error is not None:
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        if entry["consecutive_failures"] == config.FAILURE_ALERT_AFTER:
            alerts.append(
                f"⚠️ **{label}**: 取得が{config.FAILURE_ALERT_AFTER}回連続で失敗しています。"
                f"サイト構成が変わった可能性があります。\n  - エラー: {error}\n"
                f"  - 出所ページ: {meta['source_page']}"
            )
        return alerts

    entry["consecutive_failures"] = 0
    prev = latest_obs(entry)
    is_new = prev is None or new_obs.date > prev["date"]
    same_date_changed = prev is not None and new_obs.date == prev["date"] and new_obs.value != prev["value"]

    if same_date_changed:
        entry["observations"][-1] = new_obs.to_dict()
    elif is_new:
        entry["observations"].append(new_obs.to_dict())
        entry["observations"] = entry["observations"][-3000:]

    value_str = f"{new_obs.value}{meta['unit']}" if new_obs.value is not None else "（値の自動抽出に失敗）"

    if is_new and meta["frequency"] == "quarterly":
        # 四半期モノは新規公表そのものがニュース
        line = f"🆕 **{label}**: 新しい公表を検知しました — {new_obs.date[:7]} 分: **{value_str}**"
        if prev and prev.get("value") is not None and new_obs.value is not None:
            diff = round(new_obs.value - prev["value"], 2)
            line += f"（前回 {prev['value']}{meta['unit']}、{'+' if diff >= 0 else ''}{diff}pt）"
        line += f"\n  - 出所: {new_obs.source_url}"
        if new_obs.note:
            line += f"\n  - 注記: {new_obs.note}"
        alerts.append(line)

    if is_new and prev and prev.get("value") is not None and new_obs.value is not None:
        thresholds = {
            "bei_10y": config.BEI_LEVEL_THRESHOLDS,
            "survey_5y_kanari": config.SURVEY_LEVEL_THRESHOLDS,
        }.get(key, [])
        for t in crossed(thresholds, prev["value"], new_obs.value):
            direction = "上抜け" if new_obs.value >= t else "下抜け"
            alerts.append(
                f"🚨 **{label}**: {t}{meta['unit']} を{direction}しました "
                f"（{prev['date']}: {prev['value']} → {new_obs.date}: {new_obs.value}）"
            )
        if key == "bei_10y":
            move = round(new_obs.value - prev["value"], 3)
            if abs(move) >= config.BEI_MOVE_ALERT_PP:
                alerts.append(
                    f"📈 **{label}**: 1観測で {'+' if move >= 0 else ''}{move}pt の大きな変動 "
                    f"（{prev['date']}: {prev['value']} → {new_obs.date}: {new_obs.value}）"
                )

    # 四半期指標の公表遅延チェック
    obs_now = latest_obs(entry)
    if meta["frequency"] == "quarterly" and obs_now:
        last_date = dt.date.fromisoformat(obs_now["date"])
        overdue = (today_jst() - last_date).days
        if overdue > config.QUARTERLY_OVERDUE_DAYS and not entry.get("overdue_alerted"):
            entry["overdue_alerted"] = True
            alerts.append(
                f"⏰ **{label}**: 前回観測（{obs_now['date'][:7]}）から{overdue}日経過。"
                f"新しい公表を取得できていない可能性があります。出所: {meta['source_page']}"
            )
        elif overdue <= config.QUARTERLY_OVERDUE_DAYS:
            entry.pop("overdue_alerted", None)

    return alerts


# ---------------------------------------------------------------- outputs

def render_dashboard(history: dict) -> str:
    lines = [
        "# 日本のインフレ期待モニター",
        "",
        f"最終更新: {dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')}",
        "",
        "| 指標 | 最新値 | 基準日 | 前回 | 出所 |",
        "|---|---|---|---|---|",
    ]
    for key, meta in config.INDICATORS.items():
        entry = history.get(key, {"observations": []})
        obs = latest_obs(entry)
        if obs:
            value = f"**{obs['value']}{meta['unit']}**" if obs["value"] is not None else "抽出失敗"
            prev = entry["observations"][-2] if len(entry["observations"]) >= 2 else None
            prev_str = f"{prev['value']}{meta['unit']} ({prev['date']})" if prev and prev.get("value") is not None else "—"
            lines.append(
                f"| {meta['label']} | {value} | {obs['date']} | {prev_str} | [{meta['source_name']}]({meta['source_page']}) |"
            )
        else:
            lines.append(
                f"| {meta['label']} | （未取得） | — | — | [{meta['source_name']}]({meta['source_page']}) |"
            )
    lines += [
        "",
        "- BEI は日次（営業日）、短観・生活意識アンケートは四半期公表。",
        "- 値の注記・履歴は `history.json` を参照。",
        "",
    ]
    return "\n".join(lines)


def write_alerts(data_dir: Path, alerts: list[str]) -> None:
    title_path = data_dir / "alert_title.txt"
    body_path = data_dir / "alert_body.md"
    if not alerts:
        title_path.unlink(missing_ok=True)
        body_path.unlink(missing_ok=True)
        return
    today = today_jst().isoformat()
    title_path.write_text(f"インフレ期待モニター通知 ({today})", encoding="utf-8")
    body = "\n\n".join(alerts) + "\n\n---\n自動生成: inflation_monitor（詳細は `inflation_monitor/data/latest.md`）\n"
    body_path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- commands

def cmd_run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    history = load_history(data_dir)
    targets = list(FETCHERS)
    if args.only:
        targets = [ALIASES.get(args.only, args.only)]
        if targets[0] not in FETCHERS:
            print(f"不明な指標: {args.only}", file=sys.stderr)
            return 2

    all_alerts: list[str] = []
    for key in targets:
        entry = history.setdefault(
            key, {"label": config.INDICATORS[key]["label"], "observations": [], "consecutive_failures": 0}
        )
        obs, error = None, None
        try:
            obs = FETCHERS[key]()
            print(f"[ok] {key}: {obs.date} = {obs.value} ({obs.confidence})")
        except Exception as exc:  # noqa: BLE001 - 失敗も監視対象
            error = str(exc)
            print(f"[fail] {key}: {error}", file=sys.stderr)
        all_alerts.extend(evaluate(key, entry, obs, error))

    save_history(data_dir, history)
    (data_dir / "latest.md").write_text(render_dashboard(history), encoding="utf-8")
    write_alerts(data_dir, all_alerts)
    if all_alerts:
        print(f"通知 {len(all_alerts)} 件を alert_body.md に出力しました")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    key = ALIASES.get(args.indicator, args.indicator)
    if key not in config.INDICATORS:
        print(f"不明な指標: {args.indicator}", file=sys.stderr)
        return 2
    history = load_history(data_dir)
    entry = history.setdefault(
        key, {"label": config.INDICATORS[key]["label"], "observations": [], "consecutive_failures": 0}
    )
    obs = Observation(
        date=args.date, value=float(args.value), source_url="manual", note=args.note or "手動入力"
    )
    entry["observations"] = [o for o in entry["observations"] if o["date"] != args.date]
    entry["observations"].append(obs.to_dict())
    entry["observations"].sort(key=lambda o: o["date"])
    save_history(data_dir, history)
    (data_dir / "latest.md").write_text(render_dashboard(history), encoding="utf-8")
    print(f"[ok] {key}: {args.date} = {args.value} を登録しました")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inflation_monitor")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="全指標を取得して履歴・通知を更新")
    p_run.add_argument("--only", help="bei / tankan / survey のいずれか")
    p_run.set_defaults(func=cmd_run)

    p_add = sub.add_parser("add", help="観測値を手動登録")
    p_add.add_argument("indicator")
    p_add.add_argument("date", help="ISO形式 (YYYY-MM-DD)")
    p_add.add_argument("value", type=float)
    p_add.add_argument("--note", default="")
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
