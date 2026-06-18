#!/usr/bin/env python3
"""
聖書釈義ツール Webアプリ
"""

import json
import os
import sys
import traceback
from pathlib import Path

from flask import Flask, Response, render_template_string, request, stream_with_context

sys.path.insert(0, str(Path(__file__).parent))
from bible_exegesis import (
    BIBLE_BOOKS,
    _get_client,
    _normalize_passage,
    _validate_passage,
    _run_exegesis,
    _run_credibility_check,
    _apply_verification,
    _make_sources,
    ExegesisResult,
    Source,
)
from datetime import datetime

app = Flask(__name__)

# ── HTML テンプレート ────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>聖書釈義ツール</title>
<style>
  :root {
    --bg: #1a1a2e; --card: #16213e; --accent: #0f3460;
    --gold: #e2b96f; --text: #e8e8e8; --muted: #8a8a9a;
    --green: #4caf82; --red: #e05c5c; --border: #2d3561;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', 'Noto Sans JP', sans-serif; min-height: 100vh; }

  header { background: var(--accent); padding: 1.2rem 2rem; border-bottom: 2px solid var(--gold); display: flex; align-items: center; gap: 1rem; }
  header h1 { font-size: 1.4rem; color: var(--gold); letter-spacing: .05em; }
  header span { color: var(--muted); font-size: .85rem; }

  .layout { display: grid; grid-template-columns: 320px 1fr; min-height: calc(100vh - 64px); }

  /* サイドバー */
  .sidebar { background: var(--card); border-right: 1px solid var(--border); padding: 1.2rem; overflow-y: auto; max-height: calc(100vh - 64px); }
  .sidebar h2 { color: var(--gold); font-size: .9rem; letter-spacing: .08em; margin-bottom: .8rem; text-transform: uppercase; }

  .input-group { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1.2rem; }
  .passage-input {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); font-size: 1rem; padding: .7rem 1rem;
    transition: border-color .2s;
  }
  .passage-input:focus { outline: none; border-color: var(--gold); }
  .passage-input::placeholder { color: var(--muted); }

  .btn {
    background: var(--gold); color: #1a1a2e; border: none; border-radius: 6px;
    font-size: .95rem; font-weight: 700; padding: .7rem;
    cursor: pointer; transition: opacity .2s;
  }
  .btn:hover { opacity: .85; }
  .btn:disabled { opacity: .4; cursor: not-allowed; }
  .btn-outline {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    border-radius: 4px; font-size: .8rem; padding: .3rem .7rem; cursor: pointer;
  }
  .btn-outline:hover { border-color: var(--gold); color: var(--gold); }

  .hint { color: var(--muted); font-size: .78rem; line-height: 1.5; }

  .book-list { display: flex; flex-direction: column; gap: 2px; }
  .book-section-title { color: var(--gold); font-size: .75rem; font-weight: 700; letter-spacing: .1em; padding: .6rem .3rem .2rem; text-transform: uppercase; }
  .book-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: .35rem .6rem; border-radius: 4px; cursor: pointer;
    font-size: .82rem; transition: background .15s;
  }
  .book-item:hover { background: var(--accent); color: var(--gold); }
  .book-item .chaps { color: var(--muted); font-size: .72rem; }

  /* メインエリア */
  .main { padding: 1.5rem 2rem; overflow-y: auto; max-height: calc(100vh - 64px); }

  .welcome { text-align: center; padding: 4rem 2rem; color: var(--muted); }
  .welcome .big { font-size: 3rem; margin-bottom: 1rem; }
  .welcome h2 { color: var(--gold); margin-bottom: .5rem; font-size: 1.2rem; }

  /* ストリーミング進捗 */
  #progress { display: none; margin-bottom: 1rem; }
  .progress-bar-wrap { background: var(--border); border-radius: 99px; height: 4px; margin: .5rem 0; overflow: hidden; }
  .progress-bar { height: 100%; background: var(--gold); border-radius: 99px; transition: width .3s; }
  .progress-label { color: var(--muted); font-size: .82rem; }

  /* 結果カード */
  .result-header { border-bottom: 2px solid var(--gold); padding-bottom: .8rem; margin-bottom: 1.2rem; }
  .result-header .passage-title { font-size: 1.6rem; color: var(--gold); }
  .result-header .meta { color: var(--muted); font-size: .8rem; margin-top: .3rem; }

  .section { background: var(--card); border-radius: 8px; border-left: 3px solid var(--gold); padding: 1rem 1.2rem; margin-bottom: 1rem; }
  .section h3 { color: var(--gold); font-size: .85rem; letter-spacing: .06em; text-transform: uppercase; margin-bottom: .6rem; }
  .section p { line-height: 1.75; font-size: .92rem; }

  /* スコアバッジ */
  .score-badge {
    display: inline-flex; align-items: center; gap: .4rem;
    padding: .2rem .6rem; border-radius: 99px; font-size: .78rem; font-weight: 700;
  }
  .score-s1 { background: #4caf8222; color: #4caf82; }
  .score-s2 { background: #8bc34a22; color: #8bc34a; }
  .score-s3 { background: #ff980022; color: #ff9800; }
  .score-s4 { background: #ff572222; color: #ff5722; }
  .score-s5 { background: #e0505022; color: #e05050; }

  /* バー */
  .score-bar-wrap { background: var(--border); border-radius: 99px; height: 6px; flex: 1; overflow: hidden; }
  .score-bar-fill { height: 100%; border-radius: 99px; }

  /* フラグ */
  .flag { display: inline-block; font-size: .7rem; padding: .1rem .4rem; border-radius: 3px; margin: .1rem; font-weight: 600; }
  .flag-CONFIRMED    { background: #4caf8222; color: #4caf82; border: 1px solid #4caf8244; }
  .flag-PRIMARY_SOURCE { background: #2196f322; color: #42a5f5; border: 1px solid #42a5f544; }
  .flag-DISPUTED     { background: #ff980022; color: #ff9800; border: 1px solid #ff980044; }
  .flag-OVERSTATED   { background: #e0505022; color: #e05050; border: 1px solid #e0505044; }
  .flag-UNDERSTATED  { background: #9c27b022; color: #ce93d8; border: 1px solid #ce93d844; }
  .flag-SPECULATIVE  { background: #60606022; color: #aaa; border: 1px solid #aaa4; }
  .flag-SECONDARY_SOURCE { background: #78909c22; color: #90a4ae; border: 1px solid #90a4ae44; }

  /* 資料カード */
  .source-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: .8rem; }
  .source-card .source-title { font-weight: 700; color: var(--text); font-size: .92rem; margin-bottom: .5rem; }
  .source-card .source-meta { display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; margin-bottom: .5rem; }
  .source-card .category-tag { font-size: .72rem; color: var(--muted); background: var(--bg); padding: .15rem .5rem; border-radius: 3px; }
  .score-row { display: flex; align-items: center; gap: .6rem; margin: .4rem 0; }
  .score-num { font-weight: 700; font-size: .95rem; min-width: 2.5rem; }
  .score-diff-plus  { color: #4caf82; font-size: .75rem; }
  .score-diff-minus { color: #e05050; font-size: .75rem; }
  .source-detail { font-size: .82rem; color: var(--muted); line-height: 1.6; margin-top: .4rem; }
  .source-detail strong { color: var(--text); }

  /* 総合スコア */
  .summary-box { background: var(--card); border: 2px solid var(--gold); border-radius: 10px; padding: 1.2rem 1.5rem; margin: 1.2rem 0; }
  .summary-box h3 { color: var(--gold); margin-bottom: .8rem; font-size: 1rem; }
  .big-score { font-size: 2.2rem; font-weight: 800; color: var(--gold); }
  .big-score-label { font-size: .9rem; color: var(--muted); margin-left: .5rem; }
  .flag-summary { display: flex; flex-wrap: wrap; gap: .4rem; margin: .6rem 0; }
  .adjusted-list { font-size: .82rem; color: var(--muted); }
  .adjusted-list li { padding: .2rem 0; }
  .overall-comment { font-size: .85rem; line-height: 1.7; color: var(--text); border-top: 1px solid var(--border); margin-top: .8rem; padding-top: .8rem; }

  .sections-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .sections-grid { grid-template-columns: 1fr; } }

  .sources-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; }
  @media (max-width: 1100px) { .sources-grid { grid-template-columns: 1fr; } }

  .streaming-dot { display: inline-block; animation: blink 1s infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  .error-box { background: #e0505022; border: 1px solid #e05050; border-radius: 8px; padding: 1rem 1.2rem; color: #e05050; }
</style>
</head>
<body>

<header>
  <h1>✦ 聖書釈義ツール</h1>
  <span>Bible Exegesis Tool — 歴史・文化・考古学・信頼性チェック</span>
</header>

<div class="layout">

  <!-- サイドバー -->
  <aside class="sidebar">
    <h2>聖書箇所を選択</h2>

    <div class="input-group">
      <input id="passageInput" class="passage-input" type="text"
        placeholder="例：ヨハネ3:16 / 詩篇23篇"
        autocomplete="off" list="bookSuggestions">
      <datalist id="bookSuggestions"></datalist>
      <button id="analyzeBtn" class="btn" onclick="startAnalysis()">釈義・分析する</button>
    </div>

    <p class="hint" style="margin-bottom:1rem;">
      書物名をクリック → 章節を入力<br>
      例：ルカ2章14節 / Genesis 1:1 / 詩篇119篇105節
    </p>

    <h2>書物一覧</h2>
    <div class="book-list" id="bookList"></div>
  </aside>

  <!-- メインエリア -->
  <main class="main" id="main">
    <div class="welcome">
      <div class="big">✦</div>
      <h2>聖書箇所を選択して分析を開始</h2>
      <p>左のリストから書物を選ぶか、箇所を直接入力してください</p>
    </div>
  </main>

</div>

<script>
const BOOKS = {{ books_json }};

// 書物リストを描画
function renderBookList() {
  const el = document.getElementById('bookList');
  const dl = document.getElementById('bookSuggestions');
  let html = '';
  let section = '';
  BOOKS.forEach((b, i) => {
    const newSection = i < 39 ? '旧約聖書' : '新約聖書';
    if (newSection !== section) {
      html += `<div class="book-section-title">${newSection}</div>`;
      section = newSection;
    }
    html += `<div class="book-item" onclick="selectBook('${b.jp}', ${b.chapters})">
      <span>${b.jp}</span>
      <span class="chaps">${b.chapters}章</span>
    </div>`;
    const opt1 = document.createElement('option'); opt1.value = b.jp; dl.appendChild(opt1);
    const opt2 = document.createElement('option'); opt2.value = b.en; dl.appendChild(opt2);
  });
  el.innerHTML = html;
}

function selectBook(name, chapters) {
  const chap = chapters === 1
    ? prompt(`${name}（1章のみ）\n節を入力してください（例：1）`, '1')
    : prompt(`${name}（全${chapters}章）\n章:節 を入力してください\n例：1:1 / ${chapters}:1 / 1（章全体）`, '');
  if (chap === null) return;
  document.getElementById('passageInput').value = name + chap.trim();
  startAnalysis();
}

function startAnalysis() {
  const raw = document.getElementById('passageInput').value.trim();
  if (!raw) { alert('聖書箇所を入力してください'); return; }

  const main = document.getElementById('main');
  const btn = document.getElementById('analyzeBtn');
  btn.disabled = true;
  btn.textContent = '分析中…';

  main.innerHTML = `
    <div id="progress">
      <div class="progress-label" id="progressLabel">接続中<span class="streaming-dot">…</span></div>
      <div class="progress-bar-wrap"><div class="progress-bar" id="progressBar" style="width:5%"></div></div>
    </div>
    <div id="streamOutput"></div>`;
  document.getElementById('progress').style.display = 'block';

  const evtSource = new EventSource('/analyze?passage=' + encodeURIComponent(raw));
  let resultData = null;

  evtSource.addEventListener('progress', e => {
    const d = JSON.parse(e.data);
    document.getElementById('progressLabel').textContent = d.message;
    document.getElementById('progressBar').style.width = d.pct + '%';
  });

  evtSource.addEventListener('result', e => {
    resultData = JSON.parse(e.data);
  });

  evtSource.addEventListener('done', () => {
    evtSource.close();
    btn.disabled = false;
    btn.textContent = '釈義・分析する';
    document.getElementById('progress').style.display = 'none';
    if (resultData) renderResult(resultData);
  });

  evtSource.addEventListener('error_msg', e => {
    evtSource.close();
    btn.disabled = false;
    btn.textContent = '釈義・分析する';
    document.getElementById('progress').style.display = 'none';
    main.innerHTML = `<div class="error-box">⚠ エラー：${JSON.parse(e.data).message}</div>`;
  });

  evtSource.onerror = () => {
    if (evtSource.readyState === EventSource.CLOSED) return;
    evtSource.close();
    btn.disabled = false;
    btn.textContent = '釈義・分析する';
    main.innerHTML = `<div class="error-box">⚠ 接続エラーが発生しました。もう一度お試しください。</div>`;
  };
}

// Enter キーで分析実行
document.addEventListener('DOMContentLoaded', () => {
  renderBookList();
  document.getElementById('passageInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') startAnalysis();
  });
});

// スコアのCSSクラス
function scoreClass(s) {
  if (s >= 90) return 'score-s1';
  if (s >= 70) return 'score-s2';
  if (s >= 50) return 'score-s3';
  if (s >= 30) return 'score-s4';
  return 'score-s5';
}
function scoreStars(s) {
  const f = Math.round(s / 20);
  return '★'.repeat(f) + '☆'.repeat(5 - f);
}
function scoreBarColor(s) {
  if (s >= 90) return '#4caf82';
  if (s >= 70) return '#8bc34a';
  if (s >= 50) return '#ff9800';
  if (s >= 30) return '#ff5722';
  return '#e05050';
}
function scoreLabel(s) {
  if (s >= 90) return '非常に高い';
  if (s >= 70) return '高い';
  if (s >= 50) return '中程度';
  if (s >= 30) return '低い';
  return '非常に低い';
}

function renderSource(src) {
  const diff = src.verified_score - src.credibility_score;
  const diffHtml = diff !== 0
    ? `<span class="${diff > 0 ? 'score-diff-plus' : 'score-diff-minus'}">${diff > 0 ? '+' : ''}${diff}</span>`
    : '';
  const flagsHtml = (src.flags || []).map(f =>
    `<span class="flag flag-${f}">${f}</span>`).join('');

  const bar = `<div class="score-bar-wrap" style="min-width:100px">
    <div class="score-bar-fill" style="width:${src.verified_score}%;background:${scoreBarColor(src.verified_score)}"></div>
  </div>`;

  let detailHtml = '';
  if (src.credibility_reason) detailHtml += `<div><strong>根拠：</strong>${src.credibility_reason}</div>`;
  if (src.verification_notes && diff !== 0) detailHtml += `<div><strong>検証：</strong>${src.verification_notes}</div>`;
  if (src.description) detailHtml += `<div><strong>説明：</strong>${src.description}</div>`;

  return `<div class="source-card">
    <div class="source-title">${src.title}</div>
    <div class="source-meta">
      <span class="category-tag">${src.category}</span>
      <span class="score-badge ${scoreClass(src.verified_score)}">${scoreStars(src.verified_score)}</span>
    </div>
    <div class="score-row">
      <span class="score-num">${src.verified_score}点</span>
      ${diffHtml}
      ${diff !== 0 ? `<span style="color:var(--muted);font-size:.75rem">元:${src.credibility_score}点</span>` : ''}
      ${bar}
    </div>
    ${flagsHtml ? `<div style="margin:.3rem 0">${flagsHtml}</div>` : ''}
    <div class="source-detail">${detailHtml}</div>
  </div>`;
}

function renderResult(d) {
  const main = document.getElementById('main');

  // フラグ集計
  const flagCount = {};
  [...(d.archaeological_evidence || []), ...(d.sources || [])].forEach(s => {
    (s.flags || []).forEach(f => { flagCount[f] = (flagCount[f] || 0) + 1; });
  });
  const flagSummaryHtml = Object.entries(flagCount)
    .sort((a,b) => b[1]-a[1])
    .map(([f,n]) => `<span class="flag flag-${f}">${f} ×${n}</span>`)
    .join('');

  // 大幅修正
  const adjusted = [...(d.archaeological_evidence||[]), ...(d.sources||[])]
    .filter(s => Math.abs((s.verified_score||0) - s.credibility_score) >= 10);
  const adjustedHtml = adjusted.length
    ? `<div style="margin-top:.6rem"><strong style="color:var(--text)">⚠ スコア大幅修正（±10点以上）</strong>
        <ul class="adjusted-list">${adjusted.map(s => {
          const diff = (s.verified_score||0) - s.credibility_score;
          return `<li>${s.title.slice(0,42)}… ${s.credibility_score}点 → ${s.verified_score}点
            <span class="${diff>0?'score-diff-plus':'score-diff-minus'}">(${diff>0?'+':''}${diff})</span></li>`;
        }).join('')}</ul></div>`
    : '';

  const overall = Math.round(d.overall_credibility || 0);

  main.innerHTML = `
    <div class="result-header">
      <div class="passage-title">✦ ${d.passage}</div>
      <div class="meta">分析日時：${d.created_at} ／ 総合信頼性：${overall}点（${scoreLabel(overall)}）</div>
    </div>

    <div class="section" style="grid-column:1/-1">
      <h3>本文概要</h3>
      <p>${d.text_summary}</p>
    </div>

    <div class="sections-grid">
      <div class="section"><h3>イスラエル史における文脈</h3><p>${d.israel_history_context}</p></div>
      <div class="section"><h3>世界史との接点</h3><p>${d.world_history_connections}</p></div>
      <div class="section"><h3>歴史的背景</h3><p>${d.historical_background}</p></div>
      <div class="section"><h3>文化的・社会的文脈</h3><p>${d.cultural_context}</p></div>
      <div class="section"><h3>地理的文脈</h3><p>${d.geographical_context}</p></div>
      <div class="section"><h3>経済的文脈</h3><p>${d.economic_context}</p></div>
      <div class="section" style="grid-column:1/-1"><h3>神学的注釈</h3><p>${d.theological_notes}</p></div>
    </div>

    <h2 style="color:var(--gold);margin:1.2rem 0 .6rem;font-size:1rem;letter-spacing:.06em">◆ 考古学的証拠・資料</h2>
    <div class="sources-grid">${(d.archaeological_evidence||[]).map(renderSource).join('')}</div>

    <h2 style="color:var(--gold);margin:1.2rem 0 .6rem;font-size:1rem;letter-spacing:.06em">◆ 参考資料・文献</h2>
    <div class="sources-grid">${(d.sources||[]).map(renderSource).join('')}</div>

    <div class="summary-box">
      <h3>◆ 信頼性チェック サマリー</h3>
      <div>
        <span class="big-score">${overall}点</span>
        <span class="big-score-label">${scoreStars(overall)} ${scoreLabel(overall)}</span>
      </div>
      <div class="score-row" style="margin:.6rem 0">
        <div class="score-bar-wrap" style="min-width:200px;height:10px">
          <div class="score-bar-fill" style="width:${overall}%;background:${scoreBarColor(overall)};height:100%"></div>
        </div>
      </div>
      <div class="flag-summary">${flagSummaryHtml}</div>
      ${adjustedHtml}
      ${d.overall_comment ? `<div class="overall-comment"><strong>総評：</strong>${d.overall_comment}</div>` : ''}
    </div>`;
}
</script>
</body>
</html>
"""


# ── 書物データ（JSONシリアライズ用）────────────────────────────────────────

BOOKS_JSON = json.dumps(
    [{"jp": jp, "en": en, "chapters": chaps} for jp, en, _, chaps in BIBLE_BOOKS],
    ensure_ascii=False,
)


# ── ルーティング ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML, books_json=BOOKS_JSON)


@app.route("/analyze")
def analyze():
    raw = request.args.get("passage", "").strip()
    if not raw:
        return Response("data: {}\n\n", mimetype="text/event-stream")

    passage = _normalize_passage(raw)
    valid, msg = _validate_passage(passage)
    if not valid:
        return _sse_error(msg)

    def generate():
        try:
            client = _get_client()

            yield _sse("progress", {"message": "釈義分析中（1/2）…", "pct": 10})

            # ステップ1: 釈義分析
            from bible_exegesis import EXEGESIS_SYSTEM_PROMPT, _extract_json
            import anthropic as _anthropic

            prompt = (
                f"聖書箇所「{passage}」について釈義分析を行い、"
                "指定のJSON形式のみで回答してください。"
                "考古学的証拠は具体的な発掘地・碑文名・遺物名を含め最低4件、"
                "参考資料も最低4件挙げてください。"
                "全テキストフィールド内のダブルクォートは必ずバックスラッシュでエスケープしてください。"
            )

            full = ""
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=8096,
                system=EXEGESIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for i, text in enumerate(stream.text_stream):
                    full += text
                    if i % 30 == 0:
                        pct = min(10 + int(len(full) / 80), 55)
                        yield _sse("progress", {"message": "釈義分析中（1/2）…", "pct": pct})

            data = _extract_json(full)
            yield _sse("progress", {"message": "信頼性チェック中（2/2）…", "pct": 60})

            arch = _make_sources(data.get("archaeological_evidence", []))
            srcs = _make_sources(data.get("sources", []))
            all_sources = arch + srcs

            # ステップ2: 信頼性チェック
            try:
                verification = _run_credibility_check(client, all_sources, passage)
                all_sources = _apply_verification(all_sources, verification)
                overall_comment = verification.get("overall_assessment", "")
            except Exception:
                overall_comment = ""
                for s in all_sources:
                    s.verified_score = s.credibility_score

            arch = all_sources[: len(arch)]
            srcs = all_sources[len(arch):]

            avg = (
                sum(s.verified_score for s in all_sources) / len(all_sources)
                if all_sources else 0.0
            )

            def src_dict(s: Source) -> dict:
                return {
                    "title": s.title, "category": s.category,
                    "description": s.description,
                    "credibility_score": s.credibility_score,
                    "credibility_reason": s.credibility_reason,
                    "verified_score": s.verified_score,
                    "verification_notes": s.verification_notes,
                    "flags": s.flags,
                }

            result = {
                "passage": passage,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "overall_credibility": avg,
                "overall_comment": overall_comment,
                "text_summary": data.get("text_summary", ""),
                "israel_history_context": data.get("israel_history_context", ""),
                "world_history_connections": data.get("world_history_connections", ""),
                "historical_background": data.get("historical_background", ""),
                "cultural_context": data.get("cultural_context", ""),
                "geographical_context": data.get("geographical_context", ""),
                "economic_context": data.get("economic_context", ""),
                "theological_notes": data.get("theological_notes", ""),
                "archaeological_evidence": [src_dict(s) for s in arch],
                "sources": [src_dict(s) for s in srcs],
            }

            yield _sse("progress", {"message": "完了", "pct": 100})
            yield _sse("result", result)
            yield _sse("done", {})

        except Exception as e:
            traceback.print_exc()
            yield _sse("error_msg", {"message": str(e)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_error(msg: str) -> Response:
    def gen():
        yield _sse("error_msg", {"message": msg})
    return Response(stream_with_context(gen()), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"聖書釈義ツール起動中 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
