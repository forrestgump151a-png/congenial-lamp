#!/usr/bin/env python3
"""
聖書釈義ツール (Bible Exegesis Tool)

聖書箇所を指定し、歴史的・文化的・地理的・考古学的背景を多角的に分析するツール。
各資料の信ぴょう性スコアも提示します。
"""

import anthropic
import json
import os
import sys
from dataclasses import dataclass


def _get_client() -> anthropic.Anthropic:
    token_file = os.environ.get(
        "CLAUDE_CODE_SESSION_TOKEN_FILE",
        "/home/claude/.claude/remote/.session_ingress_token",
    )
    if os.path.exists(token_file):
        with open(token_file) as f:
            token = f.read().strip()
        return anthropic.Anthropic(auth_token=token)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    raise RuntimeError(
        "Anthropic認証情報が見つかりません。ANTHROPIC_API_KEY 環境変数を設定してください。"
    )


@dataclass
class Source:
    title: str
    category: str
    description: str
    credibility_score: int
    credibility_reason: str


@dataclass
class ExegesisResult:
    passage: str
    text_summary: str
    historical_background: str
    cultural_context: str
    geographical_context: str
    economic_context: str
    archaeological_evidence: list[Source]
    world_history_connections: str
    israel_history_context: str
    theological_notes: str
    sources: list[Source]


EXEGESIS_SYSTEM_PROMPT = """あなたは聖書学者・考古学者・古代史家としての深い知識を持つ釈義の専門家です。
聖書箇所について以下の観点から包括的に分析し、必ず有効なJSONのみを出力してください。
JSON以外のテキスト（前置き・説明文・コードブロック記法）は一切含めないでください。

分析観点：
1. 歴史的背景：イスラエルの歴史および世界史における位置づけ
2. 文化的文脈：当時の社会制度、宗教慣行、日常生活
3. 地理的文脈：地名、地形、気候、交通路
4. 経済的文脈：農業、貿易、通貨、産業
5. 考古学的証拠：発掘資料、碑文、遺物（具体的な発掘地・資料名を含める）
6. 世界史との接点：メソポタミア、エジプト、ギリシャ、ローマとの関連

信ぴょう性スコア基準（1-100点）：
- 90-100：複数の独立した一次資料で確認済み
- 70-89：考古学的証拠または複数の文献で支持
- 50-69：限られた証拠、学術的議論あり
- 30-49：仮説段階、証拠不足
- 1-29：推測的、主流学術から外れる

出力形式（このJSONのみを返すこと）：
{
  "text_summary": "箇所の簡潔な内容説明",
  "historical_background": "歴史的背景の詳細説明",
  "israel_history_context": "イスラエル史における文脈",
  "world_history_connections": "世界史との接点",
  "cultural_context": "文化的・社会的文脈",
  "geographical_context": "地理的文脈",
  "economic_context": "経済的文脈",
  "theological_notes": "神学的・宗教的注釈",
  "archaeological_evidence": [
    {
      "title": "資料名",
      "category": "碑文または遺跡または遺物または文書",
      "description": "資料の説明と聖書箇所との関連",
      "credibility_score": 85,
      "credibility_reason": "スコアの根拠"
    }
  ],
  "sources": [
    {
      "title": "参考資料名",
      "category": "文献または碑文または考古学または歴史記録",
      "description": "資料の説明",
      "credibility_score": 75,
      "credibility_reason": "信ぴょう性の根拠"
    }
  ]
}"""


def _extract_json(text: str) -> dict:
    """応答テキストからJSONオブジェクトを抽出してパースする。"""
    # コードブロック除去
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    # 最初の { から対応する } を見つける
    start = text.find("{")
    if start == -1:
        raise ValueError("JSONオブジェクトが応答中に見つかりませんでした")

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("JSONオブジェクトの終端が見つかりませんでした")


def analyze_passage(passage: str) -> ExegesisResult:
    client = _get_client()

    prompt = (
        f"聖書箇所「{passage}」について釈義分析を行い、"
        "指定のJSON形式のみで回答してください。"
        "考古学的証拠は具体的な発掘地・碑文名・遺物名を含め、最低3件以上挙げてください。"
        "参考資料も最低3件以上挙げてください。"
        "テキストフィールドの値に二重引用符を含む場合は必ずバックスラッシュでエスケープしてください。"
    )

    print("\n分析中...", end="", flush=True)

    full_response = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=EXEGESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_response += text
            print(".", end="", flush=True)

    print(" 完了\n")

    data = _extract_json(full_response)

    def make_sources(items: list) -> list[Source]:
        return [
            Source(
                title=item.get("title", "不明"),
                category=item.get("category", "不明"),
                description=item.get("description", ""),
                credibility_score=int(item.get("credibility_score", 50)),
                credibility_reason=item.get("credibility_reason", ""),
            )
            for item in items
        ]

    return ExegesisResult(
        passage=passage,
        text_summary=data.get("text_summary", ""),
        historical_background=data.get("historical_background", ""),
        cultural_context=data.get("cultural_context", ""),
        geographical_context=data.get("geographical_context", ""),
        economic_context=data.get("economic_context", ""),
        archaeological_evidence=make_sources(data.get("archaeological_evidence", [])),
        world_history_connections=data.get("world_history_connections", ""),
        israel_history_context=data.get("israel_history_context", ""),
        theological_notes=data.get("theological_notes", ""),
        sources=make_sources(data.get("sources", [])),
    )


def score_to_badge(score: int) -> str:
    if score >= 90:
        return "★★★★★ 非常に高い"
    elif score >= 70:
        return "★★★★☆ 高い"
    elif score >= 50:
        return "★★★☆☆ 中程度"
    elif score >= 30:
        return "★★☆☆☆ 低い"
    else:
        return "★☆☆☆☆ 非常に低い"


def _print_section(title: str, body: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")
    print(body)


def _print_sources(sources: list[Source], heading: str):
    if not sources:
        return
    print(f"\n{'='*60}")
    print(f"  {heading}")
    print(f"{'='*60}")
    for i, src in enumerate(sources, 1):
        badge = score_to_badge(src.credibility_score)
        print(f"\n  [{i}] {src.title}")
        print(f"      カテゴリ  : {src.category}")
        print(f"      信ぴょう性: {src.credibility_score}点  {badge}")
        print(f"      根拠      : {src.credibility_reason}")
        print(f"      説明      : {src.description}")


def print_result(result: ExegesisResult):
    sep = "=" * 70
    print(f"\n{sep}")
    print("  聖書釈義レポート")
    print(f"  箇所：{result.passage}")
    print(sep)

    print(f"\n【本文概要】\n{result.text_summary}")

    _print_section("イスラエル史における文脈", result.israel_history_context)
    _print_section("世界史との接点", result.world_history_connections)
    _print_section("歴史的背景", result.historical_background)
    _print_section("文化的・社会的文脈", result.cultural_context)
    _print_section("地理的文脈", result.geographical_context)
    _print_section("経済的文脈", result.economic_context)
    _print_section("神学的注釈", result.theological_notes)

    _print_sources(result.archaeological_evidence, "考古学的証拠・資料")
    _print_sources(result.sources, "参考資料・文献")

    all_sources = result.archaeological_evidence + result.sources
    if all_sources:
        avg = sum(s.credibility_score for s in all_sources) / len(all_sources)
        print(f"\n{'='*60}")
        print(f"  総合信ぴょう性スコア：{avg:.1f}点  {score_to_badge(int(avg))}")
        print(f"{'='*60}\n")


def interactive_mode():
    print("=" * 70)
    print("  聖書釈義ツール (Bible Exegesis Tool)")
    print("=" * 70)
    print("聖書箇所を入力してください")
    print("例：ヨハネ3:16 / マタイ5:3-12 / 創世記1:1 / Genesis 1:1")
    print("終了：quit または exit")
    print()

    while True:
        try:
            passage = input("聖書箇所 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not passage:
            continue
        if passage.lower() in ("quit", "exit", "終了"):
            print("終了します。")
            break

        try:
            result = analyze_passage(passage)
            print_result(result)
        except json.JSONDecodeError as e:
            print(f"\nJSON解析エラー: {e}\n応答が不完全でした。もう一度お試しください。")
        except anthropic.APIError as e:
            print(f"\nAPIエラー: {e}")
        except Exception as e:
            print(f"\nエラー: {e}")

        print("\n" + "─" * 70)
        print("次の聖書箇所を入力するか、quit で終了してください。")
        print()


def main():
    if len(sys.argv) > 1:
        passage = " ".join(sys.argv[1:]).strip()
        try:
            result = analyze_passage(passage)
            print_result(result)
        except Exception as e:
            print(f"エラー: {e}")
            sys.exit(1)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
