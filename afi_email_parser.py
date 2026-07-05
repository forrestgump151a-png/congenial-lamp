#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安達ファイナンシャルインスティテュート（AFI）メール配信 解析スクリプト

Gmail から保存した AFI メルマガのプレーンテキスト本文を読み込み、
以下を自動抽出して Markdown レポートとして出力する。

  1. メタ情報（配信日・タイトル）
  2. 有料会員限定記事のリンク一覧
  3. 《リミテッド会員限定》で伏せられた箇所（＜＜＜リミテッド会員のみ閲覧可能＞＞＞）
     の位置と前後文脈、および伏せ字の内容タイプの推定
  4. 大切なポイント（金融政策・物価・景気などのキーワードで文をスコアリング）
  5. 投資ポイント（売買・リスク管理などのアクション系キーワードを含む文）

使い方:
    python afi_email_parser.py mail1.txt mail2.txt ...
    cat mail.txt | python afi_email_parser.py
    python afi_email_parser.py --json mail.txt      # JSON 出力
    python afi_email_parser.py -o report.md mail.txt

依存: 標準ライブラリのみ
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# 定数・キーワード辞書
# ---------------------------------------------------------------------------

# 伏せ字マーカー（表記ゆれを許容）
MASK_PATTERN = re.compile(
    r"[＜<]{2,}\s*リミテッド会員(?:のみ閲覧可能|限定)\s*[＞>]{2,}"
)

# 会員記事リンク（タイトル行 + URL 行のペア）
ARTICLE_LINK_PATTERN = re.compile(
    r"^(?P<title>[^\n]+)\n(?P<url>https://afi\.cd-pf\.net/thread/\S+)$",
    re.MULTILINE,
)

DATE_PATTERN = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")

# 「大切なポイント」抽出用: カテゴリ別キーワードと重み
KEY_TOPIC_KEYWORDS: dict[str, tuple[int, list[str]]] = {
    "金融政策": (3, [
        "日銀", "利上げ", "利下げ", "金融政策", "決定会合", "出口政策",
        "FRB", "FOMC", "政策金利", "国債買い入れ", "量的",
    ]),
    "物価": (3, [
        "インフレ", "CPI", "物価", "企業物価", "価格判断", "デフレ",
        "販売価格", "仕入価格",
    ]),
    "景気・企業": (2, [
        "短観", "業況", "DI", "設備投資", "収益計画", "経常利益",
        "GDP", "雇用", "消費", "貿易統計", "機械受注",
    ]),
    "市場": (2, [
        "日経平均", "株価", "暴落", "急落", "調整", "為替", "円安", "円高",
        "金利", "クレジットスプレッド", "半導体", "バブル",
    ]),
    "見通し・見解": (2, [
        "見通し", "予想", "考えている", "見立て", "推測", "可能性", "リスク",
        "と考える", "ではなかろうか",
    ]),
}

# 「投資ポイント」抽出用: 売買・リスク管理などのアクション系キーワード
INVEST_ACTION_KEYWORDS: list[str] = [
    "利確", "撤退", "買い", "売り", "避難", "逃げ", "守り", "警戒",
    "シグナル", "臨界点", "見極め", "ポジション", "エントリー", "損切り",
    "アップグレード前に", "供給過剰", "崩壊", "反転", "タイムリミット",
]

# 伏せ字の内容タイプを推定するための文脈パターン
MASK_CONTEXT_HINTS: list[tuple[str, str]] = [
    (r"DI|判断|指数|係数", "指標の具体的な数値・変化幅"),
    (r"前年比|前期比|前回から|上昇|低下|修正", "具体的な変化率・数値"),
    (r"見立て|考え|推測|判断していい|ではなかろうか", "筆者（安達氏）の相場・政策判断"),
    (r"利上げ|利下げ|政策|出口", "金融政策の予想（時期・回数・水準）"),
    (r"設備投資|収益|業績", "業績・投資計画への影響の解釈"),
    (r"理由|背景|要因", "変動の背景・理由の解説"),
]

SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s*")

FOOTER_MARKERS = ("■━━", "入退会について", "配信解除", "unsubscribe")

# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------


@dataclass
class MaskedSection:
    index: int
    before: str
    after: str
    guessed_content: str


@dataclass
class ScoredSentence:
    text: str
    score: int
    topics: list[str] = field(default_factory=list)


@dataclass
class ParsedEmail:
    source: str
    date: str = ""
    title: str = ""
    member_articles: list[dict] = field(default_factory=list)
    masked_sections: list[MaskedSection] = field(default_factory=list)
    key_points: list[ScoredSentence] = field(default_factory=list)
    invest_points: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 解析ロジック
# ---------------------------------------------------------------------------


def strip_footer(text: str) -> str:
    """署名・配信解除などのフッターを本文から除去する。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(marker in line for marker in FOOTER_MARKERS):
            return "\n".join(lines[:i])
    return text


def extract_meta(text: str) -> tuple[str, str]:
    """配信日とタイトルをヘッダー枠から抽出する。"""
    date = ""
    title = ""
    m = DATE_PATTERN.search(text)
    if m:
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # ━ 罫線に挟まれた行をタイトルとみなす
    header = re.search(r"━{5,}[^\n]*\n\s*(?P<title>[^\n]+)\n━{5,}", text)
    if header:
        title = header.group("title").strip()
    return date, title


def extract_member_articles(text: str) -> list[dict]:
    """有料会員限定記事の「タイトル + URL」ペアを抽出する。"""
    articles = []
    for m in ARTICLE_LINK_PATTERN.finditer(text):
        title = m.group("title").strip()
        if title.startswith(("http", "※", "【")):
            continue
        articles.append({"title": title, "url": m.group("url").strip()})
    return articles


def guess_masked_content(before: str, after: str) -> str:
    """伏せ字の前後文脈から、隠されている内容のタイプを推定する。"""
    context = before + after
    for pattern, guess in MASK_CONTEXT_HINTS:
        if re.search(pattern, context):
            return guess
    return "詳細な分析・数値（文脈から特定できず）"


def extract_masked_sections(text: str, context_chars: int = 60) -> list[MaskedSection]:
    """伏せ字マーカーの位置と前後文脈を抽出する。"""
    sections = []
    for i, m in enumerate(MASK_PATTERN.finditer(text), start=1):
        before = text[max(0, m.start() - context_chars):m.start()]
        after = text[m.end():m.end() + context_chars]
        before = re.sub(r"\s+", " ", before).strip()
        after = re.sub(r"\s+", " ", after).strip()
        sections.append(
            MaskedSection(
                index=i,
                before=before,
                after=after,
                guessed_content=guess_masked_content(before, after),
            )
        )
    return sections


def split_sentences(text: str) -> list[str]:
    body = re.sub(r"\s+", "", text) and text
    sentences = []
    for paragraph in body.splitlines():
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith(("http", "━", "■", "※")):
            continue
        sentences.extend(s.strip() for s in SENTENCE_SPLIT.split(paragraph) if s.strip())
    return sentences


def score_sentences(sentences: list[str]) -> list[ScoredSentence]:
    """キーワード辞書に基づき文をスコアリングし、降順で返す。"""
    results = []
    seen: set[str] = set()
    for sent in sentences:
        # 重複文・伏せ字マーカーだけの文はスキップ
        if sent in seen or MASK_PATTERN.fullmatch(sent.rstrip("。")):
            continue
        seen.add(sent)
        score = 0
        topics = []
        for topic, (weight, words) in KEY_TOPIC_KEYWORDS.items():
            hits = sum(1 for w in words if w in sent)
            if hits:
                score += weight * hits
                topics.append(topic)
        if score > 0:
            results.append(ScoredSentence(text=sent, score=score, topics=topics))
    results.sort(key=lambda s: s.score, reverse=True)
    return results


def extract_invest_points(sentences: list[str]) -> list[str]:
    """売買・リスク管理などアクションに直結する文を抽出する。"""
    return [s for s in sentences if any(w in s for w in INVEST_ACTION_KEYWORDS)]


def parse_email(text: str, source: str = "-") -> ParsedEmail:
    body = strip_footer(text)
    date, title = extract_meta(body)
    sentences = split_sentences(body)
    return ParsedEmail(
        source=source,
        date=date,
        title=title,
        member_articles=extract_member_articles(body),
        masked_sections=extract_masked_sections(body),
        key_points=score_sentences(sentences),
        invest_points=extract_invest_points(sentences),
    )


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------


def render_markdown(parsed: ParsedEmail, top_n: int = 7) -> str:
    lines = [
        f"# AFI メルマガ解析: {parsed.title or '(タイトル不明)'}",
        "",
        f"- **配信日**: {parsed.date or '不明'}",
        f"- **ソース**: {parsed.source}",
        "",
    ]

    if parsed.member_articles:
        lines.append("## 有料会員限定記事")
        for a in parsed.member_articles:
            lines.append(f"- [{a['title']}]({a['url']})")
        lines.append("")

    if parsed.masked_sections:
        lines.append(f"## 《リミテッド会員限定》伏せ字箇所 ({len(parsed.masked_sections)} 箇所)")
        for s in parsed.masked_sections:
            lines.append(f"### 箇所 {s.index}")
            lines.append(f"- 直前: `…{s.before[-40:]}`")
            lines.append(f"- 直後: `{s.after[:40]}…`")
            lines.append(f"- **推定内容**: {s.guessed_content}")
        lines.append("")

    if parsed.key_points:
        lines.append(f"## 大切なポイント (上位 {min(top_n, len(parsed.key_points))} 件)")
        for sp in parsed.key_points[:top_n]:
            topics = "・".join(sp.topics)
            lines.append(f"- [{topics} / score {sp.score}] {sp.text}")
        lines.append("")

    if parsed.invest_points:
        lines.append("## 投資ポイント（アクション系）")
        for p in parsed.invest_points:
            lines.append(f"- {p}")
        lines.append("")

    return "\n".join(lines)


def to_json(parsed: ParsedEmail) -> str:
    return json.dumps(asdict(parsed), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="安達ファイナンシャルインスティテュート メルマガ解析ツール"
    )
    ap.add_argument("files", nargs="*", help="メール本文のテキストファイル（省略時は標準入力）")
    ap.add_argument("--json", action="store_true", help="JSON 形式で出力する")
    ap.add_argument("-o", "--output", help="出力先ファイル（省略時は標準出力）")
    ap.add_argument("--top", type=int, default=7, help="大切なポイントの表示件数 (default: 7)")
    args = ap.parse_args(argv)

    inputs: list[tuple[str, str]] = []
    if args.files:
        for f in args.files:
            path = Path(f)
            inputs.append((str(path), path.read_text(encoding="utf-8")))
    else:
        inputs.append(("stdin", sys.stdin.read()))

    outputs = []
    for source, text in inputs:
        parsed = parse_email(text, source=source)
        outputs.append(to_json(parsed) if args.json else render_markdown(parsed, top_n=args.top))

    result = "\n\n---\n\n".join(outputs)
    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
        print(f"書き込み完了: {args.output}", file=sys.stderr)
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
