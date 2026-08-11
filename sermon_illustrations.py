#!/usr/bin/env python3
"""
説教例話・素材収集エンジン
"""

import json
import re
from typing import Generator

CATEGORIES = [
    "時事ニュース",
    "歴史的事件",
    "人物伝記・実話",
    "ユーモア・ジョーク",
    "科学・自然",
    "名言・格言・書籍・新書・論文",
]

ILLUSTRATION_SYSTEM_PROMPT = """あなたは説教準備を支援する神学専門家です。
説教のための例話・素材を収集・生成してください。

【重要なルール】
1. すべてノンフィクション（実在の人物・出来事・事実）を使用すること
2. エビデンス（出典・根拠）を必ず明示すること
3. ユーモアは上品・品位ある内容のみ
4. 内容は150〜200字（日本語）で具体的に記述
5. 説教への適用方法は50〜80字で記述
6. 各例話にカテゴリを明記

以下のJSON形式で厳密に回答してください：
{
  "illustrations": [
    {
      "number": 1,
      "category": "カテゴリ名",
      "title": "タイトル（15字以内）",
      "content": "内容（150〜200字、具体的な人物・出来事・事実・エビデンスを含む）",
      "application": "説教への適用方法（50〜80字）",
      "evidence": "出典・根拠（書籍名・発表年・著者名など）"
    }
  ]
}

カテゴリは以下から選択：
- 時事ニュース
- 歴史的事件
- 人物伝記・実話
- ユーモア・ジョーク
- 科学・自然
- 名言・格言・書籍・新書・論文

30件の例話を生成してください。各カテゴリから最低4〜5件ずつ含めること。
テキストフィールド内のダブルクォートは必ずバックスラッシュでエスケープしてください。"""


def _build_illustration_prompt(
    passage: str,
    theme: str,
    key_points: str,
    audience: str,
    selected_categories: list[str],
) -> str:
    parts = []
    if passage:
        parts.append(f"【聖書箇所】{passage}")
    if theme:
        parts.append(f"【説教テーマ】{theme}")
    if key_points:
        parts.append(f"【キーポイント】{key_points}")
    parts.append(f"【対象聴衆】{audience or '一般会衆'}")
    if selected_categories:
        parts.append(f"【素材カテゴリ】{'、'.join(selected_categories)}")

    context = "\n".join(parts)
    return (
        f"{context}\n\n"
        "上記の条件で説教の例話・素材を30件生成してください。"
        "実在の人物・出来事・研究データを用い、エビデンスを必ず明示してください。"
        "指定のJSON形式のみで回答してください。"
    )


def _extract_illustrations_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("JSONが見つかりません")

    raw = text[start:end]
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    return json.loads(raw)


def generate_illustrations(
    client,
    passage: str,
    theme: str,
    key_points: str,
    audience: str,
    selected_categories: list[str],
) -> Generator[dict, None, None]:
    """SSE用ジェネレーター: progressとresultイベントを生成"""
    prompt = _build_illustration_prompt(
        passage, theme, key_points, audience, selected_categories
    )

    yield {"event": "progress", "data": {"message": "例話を生成中…", "pct": 5}}

    full = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=12000,
        system=ILLUSTRATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for i, text in enumerate(stream.text_stream):
            full += text
            if i % 40 == 0:
                count = full.count('"number"')
                pct = min(5 + int(count / 30 * 85), 90)
                yield {
                    "event": "progress",
                    "data": {"message": f"例話生成中… {count}/30件", "pct": pct},
                }

    yield {"event": "progress", "data": {"message": "整理中…", "pct": 95}}

    data = _extract_illustrations_json(full)
    illustrations = data.get("illustrations", [])

    yield {"event": "progress", "data": {"message": "完了", "pct": 100}}
    yield {
        "event": "result",
        "data": {
            "passage": passage,
            "theme": theme,
            "key_points": key_points,
            "audience": audience,
            "illustrations": illustrations,
        },
    }
    yield {"event": "done", "data": {}}
