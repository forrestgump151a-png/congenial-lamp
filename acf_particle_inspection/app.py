#!/usr/bin/env python3
"""
ACF粒子検査 規格値検索ツール Webアプリ

品名を入力すると、一次粒子径・平均粒子径・粒子面積率の
検査OK範囲(規格値)を表示する。
"""

import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, redirect, render_template_string, request, send_file, url_for

from criteria_store import (
    ALL_COLUMNS,
    CRITERIA_PATH,
    CriteriaFileError,
    load_criteria,
    load_csv_text,
    load_xlsx_bytes,
    search,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB

BACKUP_DIR = CRITERIA_PATH.parent / "backups"

HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACF粒子検査 規格値検索</title>
<style>
  :root {
    --bg: #0f1720; --card: #16212c; --accent: #133a4a;
    --teal: #4fd1c5; --text: #e6edf3; --muted: #8b98a5;
    --green: #4caf82; --red: #e05c5c; --amber: #e2b96f; --border: #223140;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', 'Noto Sans JP', sans-serif; min-height: 100vh; }
  header { background: var(--accent); padding: 1.2rem 2rem; border-bottom: 2px solid var(--teal); display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
  header h1 { font-size: 1.3rem; color: var(--teal); letter-spacing: .04em; }
  header span { color: var(--muted); font-size: .82rem; }
  header nav { margin-left: auto; display: flex; gap: 1rem; }
  header nav a { color: var(--muted); font-size: .82rem; text-decoration: none; }
  header nav a:hover { color: var(--teal); }

  main { max-width: 980px; margin: 0 auto; padding: 1.6rem 1.4rem 3rem; }

  .search-box { display: flex; gap: .6rem; margin-bottom: .6rem; }
  .search-box input[type=text] {
    flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); font-size: 1rem; padding: .7rem 1rem;
  }
  .search-box input[type=text]:focus { outline: none; border-color: var(--teal); }
  .btn {
    background: var(--teal); color: #0f1720; border: none; border-radius: 6px;
    font-size: .92rem; font-weight: 700; padding: .7rem 1.2rem; cursor: pointer;
  }
  .btn:hover { opacity: .85; }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--muted); }
  .btn-outline:hover { border-color: var(--teal); color: var(--teal); }

  .opts { display: flex; gap: 1.2rem; align-items: center; margin-bottom: 1.4rem; color: var(--muted); font-size: .82rem; }
  .opts label { display: flex; align-items: center; gap: .35rem; cursor: pointer; }

  .count { color: var(--muted); font-size: .82rem; margin-bottom: .8rem; }

  .card {
    background: var(--card); border: 1px solid var(--border); border-left: 3px solid var(--teal);
    border-radius: 8px; padding: 1rem 1.3rem; margin-bottom: .9rem;
  }
  .card h2 { color: var(--teal); font-size: 1.05rem; margin-bottom: .7rem; }
  .card table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  .card table td { padding: .35rem .4rem; border-bottom: 1px solid var(--border); }
  .card table td.k { color: var(--muted); width: 9.5rem; white-space: nowrap; }
  .card .note { margin-top: .6rem; color: var(--amber); font-size: .8rem; }
  .card .updated { margin-top: .4rem; color: var(--muted); font-size: .76rem; }

  .empty { text-align: center; padding: 3.5rem 1rem; color: var(--muted); }
  .empty .big { font-size: 2.4rem; margin-bottom: .8rem; }

  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem 1.4rem; margin-top: 2rem; }
  .panel h2 { color: var(--teal); font-size: .95rem; margin-bottom: .7rem; }
  .panel p { color: var(--muted); font-size: .82rem; line-height: 1.6; margin-bottom: .8rem; }
  .panel .row { display: flex; gap: .8rem; align-items: center; flex-wrap: wrap; }
  .flash { padding: .7rem 1rem; border-radius: 6px; margin-bottom: 1.2rem; font-size: .85rem; }
  .flash.ok { background: #4caf8222; color: var(--green); border: 1px solid #4caf8255; }
  .flash.err { background: #e05c5c22; color: var(--red); border: 1px solid #e05c5c55; }

  table.all { width: 100%; border-collapse: collapse; font-size: .84rem; }
  table.all th { text-align: left; color: var(--teal); border-bottom: 2px solid var(--border); padding: .5rem .5rem; }
  table.all td { padding: .5rem .5rem; border-bottom: 1px solid var(--border); }
  table.all tr:hover td { background: #ffffff08; }
</style>
</head>
<body>
<header>
  <h1>ACF粒子検査 規格値検索</h1>
  <span>品名から 一次粒子径 / 平均粒子径 / 粒子面積率 のOK範囲を検索</span>
  <nav>
    <a href="{{ url_for('index') }}">検索</a>
    <a href="{{ url_for('list_all') }}">全件一覧</a>
    <a href="{{ url_for('manage') }}">データ更新</a>
  </nav>
</header>
<main>
  <form class="search-box" method="get" action="{{ url_for('index') }}" id="searchForm">
    <input type="text" name="q" value="{{ query or '' }}" placeholder="品名を入力(部分一致) 例: ACF-1000" autofocus>
    <button class="btn" type="submit">検索</button>
  </form>
  <div class="opts">
    <label><input type="checkbox" name="exact" value="1" form="searchForm" {% if exact %}checked{% endif %}> 完全一致で検索</label>
  </div>

  {% if query is not none %}
    {% if results %}
      <div class="count">{{ results|length }} 件ヒット</div>
      {% for it in results %}
      <div class="card">
        <h2>{{ it.name }}</h2>
        <table>
          <tr><td class="k">一次粒子径</td><td>{{ it.primary_diameter.as_text() }}</td></tr>
          <tr><td class="k">平均粒子径</td><td>{{ it.average_diameter.as_text() }}</td></tr>
          <tr><td class="k">粒子面積率</td><td>{{ it.area_ratio.as_text() }}</td></tr>
        </table>
        {% if it.note %}<div class="note">備考: {{ it.note }}</div>{% endif %}
        {% if it.updated_at %}<div class="updated">更新日: {{ it.updated_at }}</div>{% endif %}
      </div>
      {% endfor %}
    {% else %}
      <div class="empty">
        <div class="big">🔍</div>
        <p>「{{ query }}」に一致する品名が見つかりませんでした。</p>
      </div>
    {% endif %}
  {% endif %}

  <div class="panel">
    <h2>このツールについて</h2>
    <p>
      品名ごとの粒子検査規格(一次粒子径・平均粒子径・粒子面積率の許容範囲)を CSV/Excel で管理し、
      品名検索で参照できるツールです。現在のデータは <b>{{ data_count }} 件</b>(ファイル: {{ data_path }}) 登録されています。<br>
      実際の規格値リストが揃ったら「データ更新」からCSV/Excelを差し替えてください。
    </p>
    <div class="row">
      <a class="btn btn-outline" href="{{ url_for('list_all') }}">全件一覧を見る</a>
      <a class="btn btn-outline" href="{{ url_for('manage') }}">データを更新する</a>
      <a class="btn btn-outline" href="{{ url_for('download_template') }}">CSVテンプレートをダウンロード</a>
    </div>
  </div>
</main>
</body>
</html>
"""

MANAGE_HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>データ更新 - ACF粒子検査 規格値検索</title>
<style>
  :root {
    --bg: #0f1720; --card: #16212c; --accent: #133a4a;
    --teal: #4fd1c5; --text: #e6edf3; --muted: #8b98a5;
    --green: #4caf82; --red: #e05c5c; --amber: #e2b96f; --border: #223140;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', 'Noto Sans JP', sans-serif; min-height: 100vh; }
  header { background: var(--accent); padding: 1.2rem 2rem; border-bottom: 2px solid var(--teal); display: flex; align-items: baseline; gap: 1rem; }
  header h1 { font-size: 1.3rem; color: var(--teal); }
  header nav { margin-left: auto; display: flex; gap: 1rem; }
  header nav a { color: var(--muted); font-size: .82rem; text-decoration: none; }
  header nav a:hover { color: var(--teal); }
  main { max-width: 760px; margin: 0 auto; padding: 1.6rem 1.4rem 3rem; }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.3rem 1.5rem; margin-bottom: 1.4rem; }
  .panel h2 { color: var(--teal); font-size: 1rem; margin-bottom: .8rem; }
  .panel p, .panel li { color: var(--muted); font-size: .84rem; line-height: 1.7; }
  .panel ul { margin: .4rem 0 .8rem 1.3rem; }
  code { background: #ffffff10; padding: .1rem .35rem; border-radius: 4px; }
  input[type=file] { color: var(--text); margin-bottom: 1rem; }
  .btn { background: var(--teal); color: #0f1720; border: none; border-radius: 6px; font-size: .92rem; font-weight: 700; padding: .7rem 1.2rem; cursor: pointer; }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--muted); text-decoration: none; padding: .6rem 1.1rem; border-radius: 6px; font-size: .85rem; }
  .btn-outline:hover { border-color: var(--teal); color: var(--teal); }
  .flash { padding: .7rem 1rem; border-radius: 6px; margin-bottom: 1.2rem; font-size: .85rem; white-space: pre-wrap; }
  .flash.ok { background: #4caf8222; color: var(--green); border: 1px solid #4caf8255; }
  .flash.err { background: #e05c5c22; color: var(--red); border: 1px solid #e05c5c55; }
</style>
</head>
<body>
<header>
  <h1>データ更新</h1>
  <nav><a href="{{ url_for('index') }}">検索へ戻る</a></nav>
</header>
<main>
  {% if message %}<div class="flash {{ 'ok' if ok else 'err' }}">{{ message }}</div>{% endif %}
  <div class="panel">
    <h2>規格値リストの差し替え(CSV / Excel)</h2>
    <p>提出された品名ごとの規格値リストを CSV(.csv) または Excel(.xlsx) でアップロードすると、検索に反映されます。</p>
    <p>必須列(1行目のヘッダー):</p>
    <ul>
      <li><code>品名</code></li>
      <li><code>一次粒子径_下限</code> / <code>一次粒子径_上限</code> / <code>一次粒子径_単位</code></li>
      <li><code>平均粒子径_下限</code> / <code>平均粒子径_上限</code> / <code>平均粒子径_単位</code></li>
      <li><code>粒子面積率_下限</code> / <code>粒子面積率_上限</code> / <code>粒子面積率_単位</code></li>
      <li>任意: <code>備考</code> / <code>更新日</code></li>
    </ul>
    <p>上限・下限のどちらかが未入力でも構いません(片側規格として扱われます)。アップロード前の内容は自動的にバックアップされます。</p>
    <form method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.xlsx,.xlsm" required>
      <br>
      <button class="btn" type="submit">アップロードして反映</button>
    </form>
  </div>
  <div class="panel">
    <h2>テンプレート</h2>
    <p>列構成の見本です。この形式でリストを整えてからアップロードしてください。</p>
    <a class="btn-outline" href="{{ url_for('download_template') }}">CSVテンプレートをダウンロード</a>
  </div>
</main>
</body>
</html>
"""


def _ensure_dirs():
    CRITERIA_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/")
def index():
    query = request.args.get("q")
    exact = request.args.get("exact") == "1"
    items = load_criteria()
    results = search(items, query, exact=exact) if query is not None else None
    return render_template_string(
        HTML,
        query=query,
        exact=exact,
        results=results,
        data_count=len(items),
        data_path=CRITERIA_PATH.name,
    )


@app.route("/all")
def list_all():
    items = load_criteria()
    rows = "".join(
        f"<tr><td>{it.name}</td><td>{it.primary_diameter.as_text()}</td>"
        f"<td>{it.average_diameter.as_text()}</td><td>{it.area_ratio.as_text()}</td>"
        f"<td>{it.note}</td></tr>"
        for it in items
    )
    body = f"""
    <main style="max-width:1100px;margin:0 auto;padding:1.6rem 1.4rem 3rem;">
      <p style="margin-bottom:1rem;"><a href="{url_for('index')}" style="color:#4fd1c5;">← 検索へ戻る</a></p>
      <table class="all">
        <tr><th>品名</th><th>一次粒子径</th><th>平均粒子径</th><th>粒子面積率</th><th>備考</th></tr>
        {rows}
      </table>
    </main>
    """
    return render_template_string(
        HTML.split("<main>")[0] + body + "</body></html>",
        query=None, exact=False, results=None, data_count=len(items), data_path=CRITERIA_PATH.name,
    )


@app.route("/manage")
def manage():
    return render_template_string(MANAGE_HTML, message=None, ok=True)


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return render_template_string(MANAGE_HTML, message="ファイルが選択されていません。", ok=False)

    filename = f.filename.lower()
    raw = f.read()
    try:
        if filename.endswith((".xlsx", ".xlsm")):
            items = load_xlsx_bytes(raw)
        elif filename.endswith(".csv"):
            items = load_csv_text(raw.decode("utf-8-sig"))
        else:
            raise CriteriaFileError("対応形式は .csv / .xlsx / .xlsm です。")
    except CriteriaFileError as e:
        return render_template_string(MANAGE_HTML, message=f"読み込みエラー:\n{e}", ok=False)
    except UnicodeDecodeError:
        return render_template_string(MANAGE_HTML, message="文字コードを認識できませんでした(UTF-8で保存してください)。", ok=False)

    if not items:
        return render_template_string(MANAGE_HTML, message="有効な行が見つかりませんでした。", ok=False)

    _ensure_dirs()
    if CRITERIA_PATH.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (BACKUP_DIR / f"criteria_{stamp}.csv").write_bytes(CRITERIA_PATH.read_bytes())

    # 常に正規CSVとして保存する(内部形式を統一)
    import csv as _csv
    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=ALL_COLUMNS)
    writer.writeheader()
    for it in items:
        writer.writerow({
            "品名": it.name,
            "一次粒子径_下限": "" if it.primary_diameter.lower is None else it.primary_diameter.lower,
            "一次粒子径_上限": "" if it.primary_diameter.upper is None else it.primary_diameter.upper,
            "一次粒子径_単位": it.primary_diameter.unit,
            "平均粒子径_下限": "" if it.average_diameter.lower is None else it.average_diameter.lower,
            "平均粒子径_上限": "" if it.average_diameter.upper is None else it.average_diameter.upper,
            "平均粒子径_単位": it.average_diameter.unit,
            "粒子面積率_下限": "" if it.area_ratio.lower is None else it.area_ratio.lower,
            "粒子面積率_上限": "" if it.area_ratio.upper is None else it.area_ratio.upper,
            "粒子面積率_単位": it.area_ratio.unit,
            "備考": it.note,
            "更新日": it.updated_at,
        })
    CRITERIA_PATH.write_text(buf.getvalue(), encoding="utf-8-sig")

    return render_template_string(
        MANAGE_HTML, message=f"{len(items)} 件を反映しました。", ok=True
    )


@app.route("/template.csv")
def download_template():
    buf = io.StringIO()
    buf.write(",".join(ALL_COLUMNS) + "\n")
    buf.write(
        "ACF-XXXX,2.80,3.20,um,2.90,3.10,um,8.0,15.0,%,例: 記入例です,2026-08-11\n"
    )
    data = buf.getvalue().encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=criteria_template.csv"},
    )


if __name__ == "__main__":
    _ensure_dirs()
    app.run(host="0.0.0.0", port=5050, debug=True)
