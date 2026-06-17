#!/usr/bin/env python3
"""
聖書釈義ツール (Bible Exegesis Tool)

聖書箇所を指定し、歴史的・文化的・地理的・考古学的背景を多角的に分析するツール。
各資料の信ぴょう性スコアと独立した信頼性チェックも提供します。
"""

import anthropic
import json
import os
import re
import readline
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ── 認証 ──────────────────────────────────────────────────────────────────

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
        "認証情報が見つかりません。ANTHROPIC_API_KEY 環境変数を設定してください。"
    )


# ── データ構造 ────────────────────────────────────────────────────────────

@dataclass
class Source:
    title: str
    category: str
    description: str
    credibility_score: int          # モデルが付与したスコア
    credibility_reason: str
    verified_score: int = 0         # 独立検証後スコア
    verification_notes: str = ""    # 検証コメント
    flags: list[str] = field(default_factory=list)  # 警告フラグ


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
    overall_credibility: float = 0.0
    created_at: str = ""


# ── プロンプト ────────────────────────────────────────────────────────────

EXEGESIS_SYSTEM_PROMPT = """あなたは聖書学者・考古学者・古代史家としての深い知識を持つ釈義の専門家です。
聖書箇所について以下の観点から包括的に分析し、必ず有効なJSONのみを出力してください。
JSON以外のテキスト（前置き・説明文・コードブロック記法 ``` など）は一切含めないでください。

分析観点：
1. 歴史的背景：イスラエルの歴史および世界史における位置づけ
2. 文化的文脈：当時の社会制度、宗教慣行、日常生活
3. 地理的文脈：地名、地形、気候、交通路
4. 経済的文脈：農業、貿易、通貨、産業
5. 考古学的証拠：具体的な発掘地・碑文名・遺物名を含む資料（最低4件）
6. 世界史との接点：メソポタミア、エジプト、ギリシャ、ローマとの関連
7. 参考文献：学術注解書・歴史記録・一次資料（最低4件）

信ぴょう性スコア基準（1-100点）：
- 90-100：複数の独立した一次資料・査読済み発掘報告で確認済み
- 70-89：考古学的証拠または複数の学術文献で支持
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
      "credibility_reason": "スコアの根拠（何が確認済みで何が未確認か）"
    }
  ],
  "sources": [
    {
      "title": "参考資料名（著者・出版年も含める）",
      "category": "文献または碑文または考古学または歴史記録",
      "description": "資料の説明と信頼性の根拠",
      "credibility_score": 75,
      "credibility_reason": "信ぴょう性の根拠（著者の権威・検証状況）"
    }
  ]
}"""

CREDIBILITY_CHECK_PROMPT = """あなたは独立した資料批評の専門家です。
以下の資料リストについて、元のスコアとは独立して信ぴょう性を評価し直してください。

評価観点：
- 資料の実在性・確認可能性
- 一次資料 vs 二次資料 vs 推測的解釈
- 学術的コンセンサスの有無
- 確認済みの事実と解釈の混在度
- 誇張・過大評価の可能性

以下のJSON形式のみで回答してください（他のテキストは不要）：
{
  "verified_sources": [
    {
      "title": "資料名（元のタイトルと完全一致）",
      "verified_score": 80,
      "notes": "検証コメント（元スコアとの差異と理由）",
      "flags": ["FLAG1", "FLAG2"]
    }
  ],
  "overall_assessment": "全体的な信ぴょう性評価コメント"
}

フラグの種類：
- CONFIRMED: 独立した複数資料で確認済み
- DISPUTED: 学術的に議論中
- SPECULATIVE: 推測的・証拠不足
- OVERSTATED: 元スコアが過大評価の可能性
- UNDERSTATED: 元スコアが過小評価の可能性
- PRIMARY_SOURCE: 一次資料として高い価値
- SECONDARY_SOURCE: 二次資料・解釈に基づく"""


# ── JSON 抽出 ─────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    text = text.strip()
    # コードブロック除去
    if "```" in text:
        lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

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
                return json.loads(text[start: i + 1])

    raise ValueError("JSONオブジェクトの終端が見つかりませんでした")


def _stream_with_progress(client: anthropic.Anthropic, **kwargs) -> str:
    """ストリーミングしながらドット進捗を表示し、全文を返す。"""
    full = ""
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            full += text
            print(".", end="", flush=True)
    return full


# ── 釈義分析 ──────────────────────────────────────────────────────────────

def _make_sources(items: list) -> list[Source]:
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


def _run_exegesis(client: anthropic.Anthropic, passage: str) -> dict:
    prompt = (
        f"聖書箇所「{passage}」について釈義分析を行い、"
        "指定のJSON形式のみで回答してください。"
        "考古学的証拠は具体的な発掘地・碑文名・遺物名を含め最低4件、"
        "参考資料も最低4件挙げてください。"
        "全テキストフィールド内のダブルクォートは必ずバックスラッシュでエスケープしてください。"
    )
    print("  釈義分析中", end="", flush=True)
    raw = _stream_with_progress(
        client,
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=EXEGESIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    print(" 完了")
    return _extract_json(raw)


def _run_credibility_check(
    client: anthropic.Anthropic,
    all_sources: list[Source],
    passage: str,
) -> dict:
    """全資料を独立した視点で再評価する。"""
    source_list = json.dumps(
        [
            {
                "title": s.title,
                "category": s.category,
                "original_score": s.credibility_score,
                "description": s.description,
                "credibility_reason": s.credibility_reason,
            }
            for s in all_sources
        ],
        ensure_ascii=False,
        indent=2,
    )
    prompt = (
        f"聖書箇所「{passage}」の釈義に関して以下の資料が提示されました。\n"
        f"元のスコアとは独立して、各資料の信ぴょう性を批判的に再評価してください。\n\n"
        f"資料リスト：\n{source_list}"
    )
    print("  信頼性チェック中", end="", flush=True)
    raw = _stream_with_progress(
        client,
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=CREDIBILITY_CHECK_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    print(" 完了")
    return _extract_json(raw)


def _apply_verification(sources: list[Source], verification: dict) -> list[Source]:
    """検証結果を各 Source オブジェクトに適用する。"""
    verified_map = {
        v["title"]: v for v in verification.get("verified_sources", [])
    }
    for src in sources:
        v = verified_map.get(src.title)
        if v:
            src.verified_score = int(v.get("verified_score", src.credibility_score))
            src.verification_notes = v.get("notes", "")
            src.flags = v.get("flags", [])
        else:
            src.verified_score = src.credibility_score
    return sources


def analyze_passage(passage: str, max_retries: int = 2) -> ExegesisResult:
    client = _get_client()
    print()

    # --- ステップ1: 釈義分析（失敗時リトライ）---
    data = None
    for attempt in range(1, max_retries + 2):
        try:
            data = _run_exegesis(client, passage)
            break
        except (json.JSONDecodeError, ValueError) as e:
            if attempt <= max_retries:
                print(f"\n  [警告] JSON解析失敗 ({e})。リトライ {attempt}/{max_retries}...")
            else:
                raise RuntimeError(f"釈義分析に失敗しました（{max_retries}回リトライ後）: {e}") from e

    arch = _make_sources(data.get("archaeological_evidence", []))
    srcs = _make_sources(data.get("sources", []))
    all_sources = arch + srcs

    # --- ステップ2: 独立信頼性チェック ---
    try:
        verification = _run_credibility_check(client, all_sources, passage)
        all_sources = _apply_verification(all_sources, verification)
        overall_comment = verification.get("overall_assessment", "")
    except Exception as e:
        print(f"\n  [警告] 信頼性チェックに失敗しました: {e}")
        overall_comment = ""
        for s in all_sources:
            s.verified_score = s.credibility_score

    arch = all_sources[: len(arch)]
    srcs = all_sources[len(arch):]

    # 総合スコア = 検証後スコアの平均
    avg = (
        sum(s.verified_score for s in all_sources) / len(all_sources)
        if all_sources else 0.0
    )

    result = ExegesisResult(
        passage=passage,
        text_summary=data.get("text_summary", ""),
        historical_background=data.get("historical_background", ""),
        cultural_context=data.get("cultural_context", ""),
        geographical_context=data.get("geographical_context", ""),
        economic_context=data.get("economic_context", ""),
        archaeological_evidence=arch,
        world_history_connections=data.get("world_history_connections", ""),
        israel_history_context=data.get("israel_history_context", ""),
        theological_notes=data.get("theological_notes", ""),
        sources=srcs,
        overall_credibility=avg,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    # overall_comment を theological_notes に付記（別フィールドなし）
    result._overall_comment = overall_comment  # type: ignore[attr-defined]
    return result


# ── 表示ユーティリティ ────────────────────────────────────────────────────

WIDTH = 70
INNER = WIDTH - 4


def _score_bar(score: int, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _score_stars(score: int) -> str:
    if score >= 90:
        return "★★★★★"
    elif score >= 70:
        return "★★★★☆"
    elif score >= 50:
        return "★★★☆☆"
    elif score >= 30:
        return "★★☆☆☆"
    else:
        return "★☆☆☆☆"


def _score_label(score: int) -> str:
    if score >= 90:
        return "非常に高い"
    elif score >= 70:
        return "高い"
    elif score >= 50:
        return "中程度"
    elif score >= 30:
        return "低い"
    else:
        return "非常に低い"


def _wrap(text: str, indent: int = 0) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=WIDTH - indent, initial_indent=prefix, subsequent_indent=prefix)


def _section(title: str, body: str):
    print(f"\n{'─' * WIDTH}")
    print(f"  ▌ {title}")
    print(f"{'─' * WIDTH}")
    if body:
        print(_wrap(body, indent=2))


def _print_source(i: int, src: Source):
    diff = src.verified_score - src.credibility_score
    diff_str = f"({'+' if diff >= 0 else ''}{diff:+d})" if diff != 0 else ""

    print(f"\n  ┌─[{i:02d}] {src.title}")
    print(f"  │  カテゴリ    : {src.category}")

    # スコア表示：元スコア → 検証後スコア
    bar = _score_bar(src.verified_score)
    stars = _score_stars(src.verified_score)
    label = _score_label(src.verified_score)
    orig = f"元:{src.credibility_score}点" if diff != 0 else ""
    print(f"  │  信ぴょう性  : {src.verified_score}点 {diff_str}  {stars} {label}")
    print(f"  │  [{bar}] {orig}")

    # フラグ表示
    if src.flags:
        flag_line = "  ".join(f"[{f}]" for f in src.flags)
        print(f"  │  フラグ      : {flag_line}")

    # 根拠
    reason_lines = textwrap.wrap(src.credibility_reason, width=INNER - 16)
    if reason_lines:
        print(f"  │  根拠        : {reason_lines[0]}")
        for l in reason_lines[1:]:
            print(f"  │               {l}")

    # 検証コメント（元スコアと差がある場合）
    if src.verification_notes and diff != 0:
        note_lines = textwrap.wrap(src.verification_notes, width=INNER - 16)
        print(f"  │  検証コメント: {note_lines[0]}")
        for l in note_lines[1:]:
            print(f"  │               {l}")

    # 説明
    desc_lines = textwrap.wrap(src.description, width=INNER - 16)
    if desc_lines:
        print(f"  │  説明        : {desc_lines[0]}")
        for l in desc_lines[1:]:
            print(f"  │               {l}")
    print(f"  └{'─' * (WIDTH - 4)}")


def _print_sources_section(sources: list[Source], heading: str):
    if not sources:
        return
    print(f"\n{'═' * WIDTH}")
    print(f"  ◆ {heading}  （{len(sources)}件）")
    print(f"{'═' * WIDTH}")
    for i, src in enumerate(sources, 1):
        _print_source(i, src)


def print_result(result: ExegesisResult):
    print(f"\n{'═' * WIDTH}")
    print(f"  聖書釈義レポート  ─  {result.passage}")
    print(f"  作成日時：{result.created_at}")
    print(f"{'═' * WIDTH}")

    print(f"\n{'─' * WIDTH}")
    print("  ▌ 本文概要")
    print(f"{'─' * WIDTH}")
    print(_wrap(result.text_summary, indent=2))

    _section("イスラエル史における文脈", result.israel_history_context)
    _section("世界史との接点", result.world_history_connections)
    _section("歴史的背景", result.historical_background)
    _section("文化的・社会的文脈", result.cultural_context)
    _section("地理的文脈", result.geographical_context)
    _section("経済的文脈", result.economic_context)
    _section("神学的注釈", result.theological_notes)

    _print_sources_section(result.archaeological_evidence, "考古学的証拠・資料")
    _print_sources_section(result.sources, "参考資料・文献")

    # ── 総合信頼性サマリー ──
    all_sources = result.archaeological_evidence + result.sources
    print(f"\n{'═' * WIDTH}")
    print("  ◆ 信頼性チェック サマリー")
    print(f"{'═' * WIDTH}")

    if all_sources:
        avg = result.overall_credibility
        bar = _score_bar(int(avg), width=30)
        print(f"\n  総合スコア（検証後平均）：{avg:.1f}点  {_score_stars(int(avg))} {_score_label(int(avg))}")
        print(f"  [{bar}]")

        # フラグ集計
        flag_counts: dict[str, int] = {}
        for s in all_sources:
            for f in s.flags:
                flag_counts[f] = flag_counts.get(f, 0) + 1
        if flag_counts:
            print("\n  フラグ集計：")
            for flag, count in sorted(flag_counts.items(), key=lambda x: -x[1]):
                print(f"    [{flag}] × {count}件")

        # スコア修正が大きい資料を警告表示
        adjusted = [
            s for s in all_sources if abs(s.verified_score - s.credibility_score) >= 10
        ]
        if adjusted:
            print("\n  ⚠ スコア大幅修正（±10点以上）：")
            for s in adjusted:
                diff = s.verified_score - s.credibility_score
                print(f"    ・{s.title[:40]}  {s.credibility_score}点 → {s.verified_score}点 ({diff:+d})")

    # overall_comment
    comment = getattr(result, "_overall_comment", "")
    if comment:
        print(f"\n  総評：")
        print(_wrap(comment, indent=4))

    print(f"\n{'═' * WIDTH}\n")


# ── ファイル保存 ──────────────────────────────────────────────────────────

def save_result(result: ExegesisResult, output_dir: str = ".") -> str:
    """分析結果をJSONファイルに保存し、ファイルパスを返す。"""
    safe_name = re.sub(r"[^\w぀-ヿ一-鿿]", "_", result.passage)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"exegesis_{safe_name}_{ts}.json"
    path = Path(output_dir) / filename

    def src_to_dict(s: Source) -> dict:
        return {
            "title": s.title,
            "category": s.category,
            "description": s.description,
            "credibility_score": s.credibility_score,
            "credibility_reason": s.credibility_reason,
            "verified_score": s.verified_score,
            "verification_notes": s.verification_notes,
            "flags": s.flags,
        }

    data = {
        "passage": result.passage,
        "created_at": result.created_at,
        "overall_credibility": result.overall_credibility,
        "overall_comment": getattr(result, "_overall_comment", ""),
        "text_summary": result.text_summary,
        "israel_history_context": result.israel_history_context,
        "world_history_connections": result.world_history_connections,
        "historical_background": result.historical_background,
        "cultural_context": result.cultural_context,
        "geographical_context": result.geographical_context,
        "economic_context": result.economic_context,
        "theological_notes": result.theological_notes,
        "archaeological_evidence": [src_to_dict(s) for s in result.archaeological_evidence],
        "sources": [src_to_dict(s) for s in result.sources],
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


# ── インタラクティブモード ────────────────────────────────────────────────

# ── 聖書書物データ ───────────────────────────────────────────────────────

# (日本語名, 英語名, 略称リスト, 総章数)
BIBLE_BOOKS: list[tuple[str, str, list[str], int]] = [
    # 旧約聖書
    ("創世記",      "Genesis",          ["Gen", "創"],   50),
    ("出エジプト記","Exodus",            ["Exo", "出"],   40),
    ("レビ記",      "Leviticus",         ["Lev", "レビ"], 27),
    ("民数記",      "Numbers",           ["Num", "民"],   36),
    ("申命記",      "Deuteronomy",       ["Deu", "申"],   34),
    ("ヨシュア記",  "Joshua",            ["Jos", "ヨシュ"],24),
    ("士師記",      "Judges",            ["Jdg", "士師"], 21),
    ("ルツ記",      "Ruth",              ["Rut", "ルツ"],  4),
    ("サムエル記上","1 Samuel",          ["1Sa", "サム上"],31),
    ("サムエル記下","2 Samuel",          ["2Sa", "サム下"],24),
    ("列王記上",    "1 Kings",           ["1Ki", "王上"], 22),
    ("列王記下",    "2 Kings",           ["2Ki", "王下"], 25),
    ("歴代誌上",    "1 Chronicles",      ["1Ch", "代上"], 29),
    ("歴代誌下",    "2 Chronicles",      ["2Ch", "代下"], 36),
    ("エズラ記",    "Ezra",              ["Ezr", "エズ"], 10),
    ("ネヘミヤ記",  "Nehemiah",          ["Neh", "ネヘ"], 13),
    ("エステル記",  "Esther",            ["Est", "エス"], 10),
    ("ヨブ記",      "Job",               ["Job", "ヨブ"], 42),
    ("詩篇",        "Psalms",            ["Psa", "詩"],  150),
    ("箴言",        "Proverbs",          ["Pro", "箴"],   31),
    ("伝道の書",    "Ecclesiastes",      ["Ecc", "伝"],   12),
    ("雅歌",        "Song of Solomon",   ["Son", "雅"],    8),
    ("イザヤ書",    "Isaiah",            ["Isa", "イザ"], 66),
    ("エレミヤ書",  "Jeremiah",          ["Jer", "エレ"], 52),
    ("哀歌",        "Lamentations",      ["Lam", "哀"],    5),
    ("エゼキエル書","Ezekiel",           ["Eze", "エゼ"], 48),
    ("ダニエル書",  "Daniel",            ["Dan", "ダニ"], 12),
    ("ホセア書",    "Hosea",             ["Hos", "ホセ"], 14),
    ("ヨエル書",    "Joel",              ["Joe", "ヨエ"],  3),
    ("アモス書",    "Amos",              ["Amo", "アモ"],  9),
    ("オバデヤ書",  "Obadiah",           ["Oba", "オバ"],  1),
    ("ヨナ書",      "Jonah",             ["Jon", "ヨナ"],  4),
    ("ミカ書",      "Micah",             ["Mic", "ミカ"],  7),
    ("ナホム書",    "Nahum",             ["Nah", "ナホ"],  3),
    ("ハバクク書",  "Habakkuk",          ["Hab", "ハバ"],  3),
    ("ゼパニヤ書",  "Zephaniah",         ["Zep", "ゼパ"],  3),
    ("ハガイ書",    "Haggai",            ["Hag", "ハガ"],  2),
    ("ゼカリヤ書",  "Zechariah",         ["Zec", "ゼカ"], 14),
    ("マラキ書",    "Malachi",           ["Mal", "マラ"],  4),
    # 新約聖書
    ("マタイ福音書","Matthew",           ["Mat", "マタイ","マタ"],28),
    ("マルコ福音書","Mark",              ["Mar", "マルコ","マル"],16),
    ("ルカ福音書",  "Luke",              ["Luk", "ルカ"], 24),
    ("ヨハネ福音書","John",              ["Joh", "ヨハネ","ヨハ"],21),
    ("使徒言行録",  "Acts",              ["Act", "使徒"], 28),
    ("ローマ書",    "Romans",            ["Rom", "ロマ"], 16),
    ("コリント一",  "1 Corinthians",     ["1Co", "コリ一"],16),
    ("コリント二",  "2 Corinthians",     ["2Co", "コリ二"],13),
    ("ガラテヤ書",  "Galatians",         ["Gal", "ガラ"],  6),
    ("エフェソ書",  "Ephesians",         ["Eph", "エフ"],  6),
    ("フィリピ書",  "Philippians",       ["Phi", "フィリ"], 4),
    ("コロサイ書",  "Colossians",        ["Col", "コロ"],  4),
    ("テサロニケ一","1 Thessalonians",   ["1Th", "テサ一"], 5),
    ("テサロニケ二","2 Thessalonians",   ["2Th", "テサ二"], 3),
    ("テモテ一",    "1 Timothy",         ["1Ti", "テモ一"], 6),
    ("テモテ二",    "2 Timothy",         ["2Ti", "テモ二"], 4),
    ("テトス書",    "Titus",             ["Tit", "テト"],  3),
    ("ピレモン書",  "Philemon",          ["Phm", "ピレ"],  1),
    ("ヘブライ書",  "Hebrews",           ["Heb", "ヘブ"], 13),
    ("ヤコブ書",    "James",             ["Jam", "ヤコ"],  5),
    ("ペテロ一",    "1 Peter",           ["1Pe", "ペテ一"], 5),
    ("ペテロ二",    "2 Peter",           ["2Pe", "ペテ二"], 3),
    ("ヨハネ一",    "1 John",            ["1Jo", "ヨハ一"], 5),
    ("ヨハネ二",    "2 John",            ["2Jo", "ヨハ二"], 1),
    ("ヨハネ三",    "3 John",            ["3Jo", "ヨハ三"], 1),
    ("ユダ書",      "Jude",              ["Jud", "ユダ"],  1),
    ("黙示録",      "Revelation",        ["Rev", "黙"],   22),
]

# 検索用フラット辞書 {正規化キー → (日本語名, 総章数)}
_BOOK_LOOKUP: dict[str, tuple[str, int]] = {}
for _jp, _en, _abbrs, _chaps in BIBLE_BOOKS:
    for _key in [_jp, _en] + _abbrs:
        _BOOK_LOOKUP[_key.lower()] = (_jp, _chaps)

# タブ補完用候補リスト（日本語名 + 英語名）
_COMPLETION_WORDS = (
    [b[0] for b in BIBLE_BOOKS]
    + [b[1] for b in BIBLE_BOOKS]
    + ["save", "books", "help", "quit"]
)


def _setup_readline():
    """タブ補完と入力履歴を設定する。"""
    def completer(text: str, state: int):
        options = [w for w in _COMPLETION_WORDS if w.lower().startswith(text.lower())]
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    # 履歴ファイル
    history_file = Path.home() / ".bible_exegesis_history"
    try:
        if history_file.exists():
            readline.read_history_file(str(history_file))
    except Exception:
        pass

    import atexit
    atexit.register(lambda: readline.write_history_file(str(history_file)))


def _normalize_passage(text: str) -> str:
    """様々な表記を正規化する。

    対応パターン：
      詩篇23篇        → 詩篇23
      ヨハネ3章16節   → ヨハネ3:16
      John 3:16       → John 3:16（そのまま）
      ヨハネ三書1:1   → ヨハネ三1:1
    """
    t = text.strip()
    # 全角コロン → 半角
    t = t.replace("：", ":").replace("　", " ")
    # 「章」→「:」、「節」除去、「篇」除去
    # 「N篇M節」→「N:M」（詩篇23篇1節 → 詩篇23:1）
    t = re.sub(r"(\d+)篇(\d+)節?", r"\1:\2", t)
    # 「N篇」（節なし）→「N」
    t = re.sub(r"(\d+)篇", r"\1", t)
    # 「章」→「:」、「節」除去
    t = re.sub(r"章\s*", ":", t)
    t = re.sub(r"節", "", t)
    # 重複コロン除去
    t = re.sub(r":+", ":", t)
    t = t.strip(":")
    return t.strip()


def _lookup_book(name: str) -> tuple[str, int] | None:
    """書物名（日本語・英語・略称）から (正規日本語名, 総章数) を返す。"""
    return _BOOK_LOOKUP.get(name.lower())


def _show_books():
    """全書物を旧約・新約に分けて表示する。"""
    ot = BIBLE_BOOKS[:39]
    nt = BIBLE_BOOKS[39:]

    print(f"\n{'─' * WIDTH}")
    print("  旧約聖書  （39書）")
    print(f"{'─' * WIDTH}")
    for i, (jp, en, abbrs, chaps) in enumerate(ot, 1):
        print(f"  {i:2d}. {jp:<12} {en:<22} {chaps:3d}章")

    print(f"\n{'─' * WIDTH}")
    print("  新約聖書  （27書）")
    print(f"{'─' * WIDTH}")
    for i, (jp, en, abbrs, chaps) in enumerate(nt, 40):
        print(f"  {i:2d}. {jp:<12} {en:<22} {chaps:3d}章")

    print(f"\n  番号を入力すると書物を選択できます（例：1 → 創世記）\n")


def _select_by_number(num: int) -> str | None:
    """番号から書物日本語名を返す（1-66）。"""
    if 1 <= num <= len(BIBLE_BOOKS):
        return BIBLE_BOOKS[num - 1][0]
    return None


def _guide_chapter_verse(book_jp: str, total_chapters: int) -> str:
    """書物選択後の章節入力ガイド文字列を返す。"""
    if total_chapters == 1:
        return f"{book_jp}（1章のみ） → 例：{book_jp}1:1"
    return (
        f"{book_jp}（全{total_chapters}章） → "
        f"例：{book_jp}1:1 / {book_jp}{total_chapters}:1 / "
        f"{book_jp}1（章全体）"
    )


HELP_TEXT = """
使い方：
  聖書箇所を直接入力、または番号で書物を選択してから章節を指定

入力形式（すべて対応）：
  ヨハネ3:16          ← 標準形式
  マタイ5:3-12        ← 範囲指定
  創世記1:1           ← 日本語書物名
  Genesis 1:1         ← 英語書物名
  詩篇23篇            ← 「篇」付き
  ルカ2章14節         ← 「章・節」表記
  ローマ8:28-39       ← 範囲
  ヨハネ3（章全体）   ← 章全体を分析
  19                  ← 番号で書物選択（19=詩篇）

コマンド：
  books     全書物一覧を表示
  save      直前の結果をJSONファイルに保存
  help      このヘルプを表示
  quit      終了

タブキーで書物名・コマンドを補完できます。
"""


def _validate_passage(text: str) -> tuple[bool, str]:
    """聖書箇所として最低限有効かチェックする。"""
    if not text:
        return False, "箇所が空です"
    if len(text) > 100:
        return False, "入力が長すぎます（100文字以内）"
    return True, ""


def _run_analysis(passage: str, last_result_ref: list) -> bool:
    """釈義を実行し結果を表示。last_result_ref[0] に格納。True=成功。"""
    try:
        result = analyze_passage(passage)
        print_result(result)
        last_result_ref[0] = result
        print("  ヒント：'save' で結果をJSONファイルに保存できます。")
        return True
    except json.JSONDecodeError as e:
        print(f"\nJSON解析エラー: {e}\n再度お試しください。")
    except anthropic.APIError as e:
        print(f"\nAPIエラー: {e}")
    except RuntimeError as e:
        print(f"\nエラー: {e}")
    except Exception as e:
        print(f"\n予期せぬエラー: {e}")
    return False


def interactive_mode():
    _setup_readline()

    print("═" * WIDTH)
    print("  聖書釈義ツール (Bible Exegesis Tool)")
    print("  歴史・文化・地理・経済・考古学の多角的分析 ＋ 信頼性チェック")
    print("═" * WIDTH)
    print("  書物名・章節を入力　／　番号で書物選択　／　Tab補完対応")
    print("  'books' で全書物一覧　'help' でヘルプ　'quit' で終了")
    print()

    last_result: list = [None]   # mutable wrapper

    while True:
        try:
            user_input = input("聖書箇所 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        # ── コマンド処理 ──
        if cmd in ("quit", "exit", "終了", "q"):
            print("終了します。")
            break

        if cmd == "help":
            print(HELP_TEXT)
            continue

        if cmd == "books":
            _show_books()
            continue

        if cmd == "save":
            if last_result[0] is None:
                print("保存できる結果がありません。先に釈義を実行してください。")
            else:
                try:
                    path = save_result(last_result[0])
                    print(f"保存しました：{path}")
                except Exception as e:
                    print(f"保存エラー：{e}")
            print()
            continue

        # ── 番号入力（書物選択） ──
        if user_input.isdigit():
            num = int(user_input)
            book = _select_by_number(num)
            if book is None:
                print(f"  1〜{len(BIBLE_BOOKS)} の番号を入力してください。")
                continue
            _, total = _BOOK_LOOKUP[book.lower()]
            guide = _guide_chapter_verse(book, total)
            print(f"  選択：{guide}")
            try:
                spec = input(f"  章節 > {book}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            passage_raw = book + spec
            passage = _normalize_passage(passage_raw)
            print()
            _run_analysis(passage, last_result)
            print()
            continue

        # ── 書物名だけの入力（章節ガイド表示） ──
        normalized = _normalize_passage(user_input)
        # 数字・コロンなしで書物名だけっぽい場合
        if not any(c.isdigit() for c in normalized):
            info = _lookup_book(normalized)
            if info:
                jp_name, total = info
                guide = _guide_chapter_verse(jp_name, total)
                print(f"  {guide}")
                try:
                    spec = input(f"  章節 > {jp_name}").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                passage_raw = jp_name + spec
                passage = _normalize_passage(passage_raw)
                print()
                _run_analysis(passage, last_result)
                print()
                continue

        # ── 通常の聖書箇所入力 ──
        passage = normalized
        valid, msg = _validate_passage(passage)
        if not valid:
            print(f"  入力エラー：{msg}")
            print("  例：ヨハネ3:16 / 19（番号）/ books（一覧）")
            print()
            continue

        print()
        _run_analysis(passage, last_result)
        print()


# ── エントリポイント ──────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    save_flag = "--save" in args
    if save_flag:
        args = [a for a in args if a != "--save"]

    if args:
        passage = " ".join(args).strip()
        valid, msg = _validate_passage(passage)
        if not valid:
            print(f"エラー：{msg}")
            sys.exit(1)
        try:
            result = analyze_passage(passage)
            print_result(result)
            if save_flag:
                path = save_result(result)
                print(f"結果を保存しました：{path}")
        except Exception as e:
            print(f"エラー: {e}")
            sys.exit(1)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
