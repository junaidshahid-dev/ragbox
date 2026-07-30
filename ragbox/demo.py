"""The product UI, served at GET /.

This is what a paying customer opens every day, so it is built as a real application rather than
a demo box: signed-in state, drag-and-drop upload, a document list you can delete from, live
usage meters that warn before a limit bites, and answers rendered as citation cards.

Design decisions that exist for business reasons, not decoration:
  - USAGE IS ALWAYS VISIBLE. A customer who cannot see they're near a limit experiences the
    limit as a bug. Shown as meters that turn amber at 75% and red at 100%, with the upgrade
    path attached at the moment of friction.
  - EMPTY STATES TEACH. A new account with no documents gets instructions, not a blank panel;
    the first minute decides whether they ever come back.
  - CITATIONS ARE THE HERO. Each source is a card with filename, page and match score, because
    "you can check this" is the entire product promise.
  - The whole page degrades to a sign-in prompt when the session is missing or expired.
"""

DEMO_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ragbox - your documents</title>
<style>
  :root {
    --ink:#14181f; --muted:#5c6875; --line:#e4e9ef; --bg:#f7f9fc; --panel:#ffffff;
    --accent:#1f6feb; --accent-soft:#eaf2ff; --ok:#0f7b3f; --ok-soft:#e9f7ef;
    --warn:#9a6a00; --warn-soft:#fdf6e3; --danger:#9b1c1c; --danger-soft:#fdecec;
    --radius:14px;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); line-height:1.55;
    font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  button, input { font-family:inherit; }

  /* ---------- top bar ---------- */
  header { background:var(--panel); border-bottom:1px solid var(--line); position:sticky; top:0;
    z-index:20; }
  .bar { max-width:1180px; margin:0 auto; padding:12px 22px; display:flex; align-items:center;
    gap:14px; }
  .logo { font-weight:800; font-size:21px; letter-spacing:-.02em; }
  .logo span { color:var(--accent); }
  .spacer { flex:1; }
  .pill { font-size:13px; font-weight:600; padding:5px 12px; border-radius:999px;
    border:1px solid var(--line); background:#fff; color:var(--muted); white-space:nowrap; }
  .pill.plan { color:var(--accent); background:var(--accent-soft); border-color:#d3e3ff; }
  .linkish { background:none; border:0; color:var(--muted); font-size:14px; cursor:pointer;
    padding:6px 8px; border-radius:8px; transition:background-color .15s ease, color .15s ease; }
  .linkish:hover { background:var(--bg); color:var(--ink); }

  /* ---------- layout ---------- */
  main { max-width:1180px; margin:0 auto; padding:26px 22px 70px;
    display:grid; grid-template-columns:320px 1fr; gap:22px; align-items:start; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
    padding:20px; }
  .panel h2 { margin:0 0 4px; font-size:15px; text-transform:uppercase; letter-spacing:.07em;
    color:var(--muted); }
  .panel .hint { color:var(--muted); font-size:13.5px; margin:0 0 16px; }

  /* ---------- usage meters ---------- */
  .meter + .meter { margin-top:14px; }
  .meter .row { display:flex; justify-content:space-between; font-size:13.5px; margin-bottom:6px; }
  .meter .row b { font-variant-numeric:tabular-nums; }
  .track { height:7px; background:#eef2f7; border-radius:999px; overflow:hidden; }
  .fill { height:100%; width:0; background:var(--accent); border-radius:999px;
    transition:width .5s cubic-bezier(.2,.8,.2,1), background-color .3s ease; }
  .fill.warn { background:#d9a406; } .fill.full { background:#c23b3b; }
  .upsell { margin-top:14px; font-size:13.5px; padding:11px 13px; border-radius:10px;
    background:var(--warn-soft); border:1px solid #f0e2b6; color:var(--warn); display:none; }
  .upsell.show { display:block; }
  .upsell a { color:var(--accent); font-weight:700; text-decoration:none; }

  /* ---------- dropzone ---------- */
  .drop { border:2px dashed #cfd8e3; border-radius:12px; padding:22px 16px; text-align:center;
    cursor:pointer; transition:border-color .18s ease, background-color .18s ease; }
  .drop:hover, .drop.over { border-color:var(--accent); background:var(--accent-soft); }
  .drop .big { font-weight:600; font-size:14.5px; }
  .drop .small { color:var(--muted); font-size:12.5px; margin-top:4px; }

  /* ---------- document list ---------- */
  .docs { list-style:none; margin:16px 0 0; padding:0; }
  .docs li { display:flex; align-items:center; gap:10px; padding:9px 0;
    border-top:1px solid var(--line); font-size:14px; }
  .docs li:first-child { border-top:0; }
  .docs .name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .docs .del { border:0; background:none; color:var(--muted); cursor:pointer; font-size:17px;
    line-height:1; padding:2px 6px; border-radius:7px; opacity:0; transition:.15s; }
  .docs li:hover .del { opacity:1; }
  .docs .del:hover { background:var(--danger-soft); color:var(--danger); }

  /* ---------- ask ---------- */
  .askbar { display:flex; gap:10px; }
  .askbar input { flex:1; padding:14px 16px; font-size:16px; border:1px solid var(--line);
    border-radius:11px; background:#fff; transition:border-color .18s, box-shadow .18s; }
  .askbar input:focus { outline:none; border-color:var(--accent);
    box-shadow:0 0 0 4px var(--accent-soft); }
  .btn { padding:0 22px; font-size:15px; font-weight:600; color:#fff; background:var(--accent);
    border:0; border-radius:11px; cursor:pointer;
    transition:transform .16s cubic-bezier(.2,.8,.2,1), box-shadow .2s, background-color .18s; }
  .btn:hover:not(:disabled) { transform:translateY(-1px); background:#1a62d4;
    box-shadow:0 8px 20px -10px rgba(31,111,235,.65); }
  .btn:active:not(:disabled) { transform:translateY(0); }
  .btn:disabled { opacity:.55; cursor:default; }
  .btn.ghost { background:#fff; color:var(--ink); border:1px solid var(--line); }
  .btn.ghost:hover:not(:disabled) { background:var(--bg); }
  .modes { display:flex; gap:8px; align-items:center; margin-top:12px; font-size:13.5px;
    color:var(--muted); flex-wrap:wrap; }
  .chip { border:1px solid var(--line); background:#fff; border-radius:999px; padding:5px 13px;
    font-size:13px; cursor:pointer; transition:.15s; }
  .chip:hover { border-color:var(--accent); color:var(--accent); }
  .chip.locked { opacity:.6; }
  .chip.on { background:var(--accent); border-color:var(--accent); color:#fff; }

  /* ---------- answer ---------- */
  .answer { margin-top:20px; display:none; }
  .answer.show { display:block; animation:rise .35s cubic-bezier(.2,.8,.2,1); }
  @keyframes rise { from { opacity:0; transform:translateY(10px); } to { opacity:1; } }
  .atext { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
    padding:20px 22px; white-space:pre-wrap; font-size:15.5px; }
  .cites { margin-top:14px; display:grid; gap:10px;
    grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); }
  .cite { background:var(--ok-soft); border:1px solid #cdeddb; border-radius:12px; padding:13px 15px; }
  .cite .src { font-weight:700; font-size:13.5px; color:var(--ok); }
  .cite .ex { font-size:12.5px; color:#3d5f4c; margin-top:6px; max-height:66px; overflow:hidden; }
  .empty { text-align:center; padding:44px 20px; color:var(--muted); }
  .empty h3 { color:var(--ink); margin:0 0 8px; font-size:18px; }
  .empty ol { text-align:left; max-width:330px; margin:16px auto 0; padding-left:20px;
    font-size:14.5px; }
  .toast { position:fixed; bottom:22px; left:50%; transform:translate(-50%,80px);
    background:var(--ink); color:#fff; padding:12px 20px; border-radius:11px; font-size:14.5px;
    box-shadow:0 14px 40px -14px rgba(0,0,0,.5); opacity:0; transition:.3s
    cubic-bezier(.2,.8,.2,1); z-index:60; }
  .toast.show { transform:translate(-50%,0); opacity:1; }
  .toast.bad { background:var(--danger); }
  .gate { max-width:430px; margin:80px auto; text-align:center; }
  @media (prefers-reduced-motion:reduce) { *{transition:none!important;animation:none!important;} }
  @media (max-width:860px) { main { grid-template-columns:1fr; } }
</style></head>
<body>

<header><div class="bar">
  <div class="logo">rag<span>box</span></div>
  <div class="spacer"></div>
  <span class="pill plan" id="planPill">...</span>
  <span class="pill" id="emailPill"></span>
  <button class="linkish" id="signout">Sign out</button>
</div></header>

<main id="app" hidden>
  <!-- ---------------- left: documents + usage ---------------- -->
  <section>
    <div class="panel">
      <h2>Your documents</h2>
      <p class="hint" id="docHint">PDF, Markdown or text.</p>
      <div class="drop" id="drop">
        <div class="big">Drop a file here</div>
        <div class="small">or click to choose</div>
      </div>
      <input type="file" id="file" accept=".pdf,.md,.txt" hidden>
      <ul class="docs" id="docs"></ul>
    </div>

    <div class="panel" style="margin-top:18px">
      <h2>This month</h2>
      <div class="meter">
        <div class="row"><span>Documents</span><b id="dTxt">-</b></div>
        <div class="track"><div class="fill" id="dFill"></div></div>
      </div>
      <div class="meter">
        <div class="row"><span>Questions</span><b id="qTxt">-</b></div>
        <div class="track"><div class="fill" id="qFill"></div></div>
      </div>
      <div class="upsell" id="upsell"></div>
    </div>
  </section>

  <!-- ---------------- right: ask ---------------- -->
  <section>
    <div class="panel">
      <h2>Ask a question</h2>
      <p class="hint">Answers come only from your documents, with the source shown.</p>
      <div class="askbar">
        <input id="q" placeholder="e.g. What is our refund policy?" autocomplete="off">
        <button class="btn" id="go">Ask</button>
      </div>
      <div class="modes">
        <span>Answer style:</span>
        <button class="chip on" id="mExt" data-mode="extractive">Exact passages</button>
        <button class="chip" id="mLlm" data-mode="llm">AI-written</button>
      </div>
    </div>

    <div class="answer" id="answer">
      <div class="atext" id="atext"></div>
      <div class="cites" id="cites"></div>
    </div>

    <div class="panel empty" id="emptyState" style="margin-top:18px">
      <h3>Add a document to get started</h3>
      <p>Once you upload something, you can ask questions about it and every answer will show
         you exactly where it came from.</p>
      <ol><li>Upload a PDF, manual or policy document</li>
          <li>Ask a question the way you'd ask a colleague</li>
          <li>Check the answer against its cited source</li></ol>
    </div>
  </section>
</main>

<!-- signed-out gate -->
<div class="gate" id="gate" hidden>
  <div class="panel">
    <h3 style="margin-top:0">You're signed out</h3>
    <p style="color:var(--muted)">Sign in to reach your documents.</p>
    <a class="btn" style="display:inline-block;line-height:42px;text-decoration:none"
       href="/welcome">Go to sign in</a>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
(function () {
  var mode = 'extractive', me = null;
  var $ = function (id) { return document.getElementById(id); };

  function toast(text, bad) {
    var t = $('toast'); t.textContent = text;
    t.className = 'toast show' + (bad ? ' bad' : '');
    setTimeout(function () { t.className = 'toast' + (bad ? ' bad' : ''); }, 3200);
  }

  function meter(fillEl, txtEl, used, limit) {
    var pct = limit > 0 ? Math.min(100, used / limit * 100) : 0;
    fillEl.style.width = pct + '%';
    fillEl.className = 'fill' + (pct >= 100 ? ' full' : pct >= 75 ? ' warn' : '');
    txtEl.textContent = used.toLocaleString() + ' / ' + limit.toLocaleString();
  }

  async function loadMe() {
    var r = await fetch('/me');
    if (r.status === 401) { $('gate').hidden = false; $('app').hidden = true; return null; }
    me = await r.json();
    $('app').hidden = false; $('gate').hidden = true;
    $('planPill').textContent = me.plan_label + (me.subscription.days_left !== null
      ? ' - ' + me.subscription.days_left + 'd left' : '');
    $('emailPill').textContent = me.email;
    meter($('dFill'), $('dTxt'), me.documents.used, me.documents.limit);
    meter($('qFill'), $('qTxt'), me.questions.used, me.questions.limit);
    $('docHint').textContent = 'PDF, Markdown or text. Up to ' + me.features.max_upload_mb
      + ' MB per file.';

    // upgrade prompt appears exactly when a limit starts to bite
    var nearDocs = me.documents.used / me.documents.limit >= 0.75;
    var nearQ    = me.questions.used / me.questions.limit >= 0.75;
    var up = $('upsell');
    if (!me.subscription.is_paying && (nearDocs || nearQ)) {
      up.className = 'upsell show';
      up.innerHTML = 'You\\'re close to the Free plan limit. '
        + '<a href="/welcome#pricing">See plans</a> for more room and AI-written answers.';
    } else { up.className = 'upsell'; }

    $('mLlm').className = 'chip' + (me.features.llm_answers ? '' : ' locked')
      + (mode === 'llm' ? ' on' : '');
    return me;
  }

  async function loadDocs() {
    var r = await fetch('/status');
    if (r.status === 401) return loadMe();
    var s = await r.json();
    var ul = $('docs'); ul.innerHTML = '';
    (s.sources || []).forEach(function (name) {
      var li = document.createElement('li');
      li.innerHTML = '<span class="name"></span>'
        + '<button class="del" title="Remove">&times;</button>';
      li.querySelector('.name').textContent = name;
      li.querySelector('.del').onclick = function () { del(name); };
      ul.appendChild(li);
    });
    $('emptyState').style.display = (s.sources || []).length ? 'none' : 'block';
  }

  async function del(name) {
    var r = await fetch('/documents/' + encodeURIComponent(name), { method: 'DELETE' });
    if (r.ok) { toast('Removed ' + name); loadDocs(); loadMe(); }
    else { toast('Could not remove that file', true); }
  }

  async function upload(f) {
    if (!f) return;
    var fd = new FormData(); fd.append('file', f);
    toast('Uploading ' + f.name + '...');
    var r = await fetch('/upload', { method: 'POST', body: fd });
    var d = await r.json().catch(function () { return {}; });
    if (r.ok) { toast('Added ' + f.name); loadDocs(); loadMe(); }
    else { toast(d.detail || 'Upload failed', true); loadMe(); }
  }

  // dropzone
  var drop = $('drop'), file = $('file');
  drop.onclick = function () { file.click(); };
  file.onchange = function () { upload(file.files[0]); file.value = ''; };
  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); });
  });
  drop.addEventListener('drop', function (e) {
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
  });

  // answer-style chips
  [$('mExt'), $('mLlm')].forEach(function (c) {
    c.onclick = function () {
      if (c.dataset.mode === 'llm' && me && !me.features.llm_answers) {
        toast('AI-written answers are on the paid plans', true);
        window.location.href = '/welcome#pricing'; return;
      }
      mode = c.dataset.mode;
      $('mExt').className = 'chip' + (mode === 'extractive' ? ' on' : '');
      $('mLlm').className = 'chip' + (me && me.features.llm_answers ? '' : ' locked')
        + (mode === 'llm' ? ' on' : '');
    };
  });

  async function ask() {
    var q = $('q').value.trim(); if (!q) return;
    var btn = $('go'); btn.disabled = true; btn.textContent = 'Searching...';
    try {
      var r = await fetch('/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, k: 3, mode: mode })
      });
      var d = await r.json();
      if (!r.ok) { toast(d.detail || 'Something went wrong', true); loadMe(); return; }
      $('atext').textContent = d.text;
      var box = $('cites'); box.innerHTML = '';
      (d.citations || []).forEach(function (c) {
        var el = document.createElement('div'); el.className = 'cite';
        var src = document.createElement('div'); src.className = 'src';
        src.textContent = c.source + (c.page ? ' - page ' + c.page : '')
          + '  (match ' + c.score + ')';
        var ex = document.createElement('div'); ex.className = 'ex'; ex.textContent = c.excerpt;
        el.appendChild(src); el.appendChild(ex); box.appendChild(el);
      });
      $('answer').className = 'answer show';
      loadMe();
    } catch (e) { toast('Network error', true); }
    finally { btn.disabled = false; btn.textContent = 'Ask'; }
  }
  $('go').onclick = ask;
  $('q').addEventListener('keydown', function (e) { if (e.key === 'Enter') ask(); });

  $('signout').onclick = async function () {
    await fetch('/logout', { method: 'POST' }); window.location.href = '/welcome';
  };

  loadMe().then(function (m) { if (m) loadDocs(); });
})();
</script>
</body></html>"""
