"""A minimal, self-contained demo front-end for ragbox, served at GET /.

It's a real UI: the page calls the live /ask endpoint and renders the answer with its
citations. No build step, no framework - a single HTML string so `uvicorn ragbox.api:app`
gives you a working demo out of the box.
"""

DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ragbox - ask your documents</title>
<style>
  :root { --bg:#f6f8fa; --card:#fff; --line:#e3e8ee; --ink:#1b2430; --muted:#5b6876;
          --accent:#2563eb; --accentbg:#eef4ff; --ok:#0f7b3f; }
  * { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.55; }
  .wrap { max-width:760px; margin:0 auto; padding:40px 20px 80px; }
  .brand { font-weight:800; font-size:30px; letter-spacing:-.02em; }
  .brand span { color:var(--accent); }
  .sub { color:var(--muted); margin:6px 0 26px; }
  .askbar { display:flex; gap:10px; }
  input { flex:1; padding:14px 16px; font-size:16px; border:1px solid var(--line);
    border-radius:10px; background:var(--card); outline:none; }
  input:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accentbg); }
  button { padding:0 22px; font-size:16px; font-weight:600; color:#fff; background:var(--accent);
    border:0; border-radius:10px; cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
  .chips { margin:14px 0 4px; display:flex; gap:8px; flex-wrap:wrap; }
  .chip { font-size:13px; color:var(--accent); background:var(--accentbg); border:1px solid #dbe6ff;
    padding:6px 12px; border-radius:999px; cursor:pointer; }
  .answer { margin-top:26px; background:var(--card); border:1px solid var(--line);
    border-radius:14px; padding:22px 24px; white-space:pre-wrap; display:none; }
  .answer.show { display:block; }
  .cites { margin-top:16px; border-top:1px solid var(--line); padding-top:14px; }
  .cites h4 { margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:.06em;
    color:var(--muted); }
  .cite { font-size:14px; color:var(--muted); display:flex; gap:8px; align-items:baseline; margin:4px 0; }
  .cite b { color:var(--ok); }
  .foot { margin-top:40px; color:var(--muted); font-size:13px; }
  .foot a { color:var(--accent); text-decoration:none; }
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">rag<span>box</span></div>
  <div class="sub">Ask a question and get an answer straight from your documents, with the source cited.</div>

  <div class="askbar">
    <input id="q" placeholder="e.g. What is the refund policy?" autocomplete="off">
    <button id="go" onclick="ask()">Ask</button>
  </div>
  <div class="chips" id="chips"></div>

  <div class="answer" id="answer"></div>

  <div class="foot">Indexed: <span id="status">...</span> &nbsp;·&nbsp;
    Open source: <a href="https://github.com/junaidshahid-dev/ragbox">github.com/junaidshahid-dev/ragbox</a></div>
</div>

<script>
const examples = ["What is the refund policy?", "What are the support hours?",
                  "What battery does the ToolMaster use?", "Is there a warranty?"];
const chips = document.getElementById('chips');
examples.forEach(t => { const c=document.createElement('span'); c.className='chip'; c.textContent=t;
  c.onclick=()=>{document.getElementById('q').value=t; ask();}; chips.appendChild(c); });

fetch('/status').then(r=>r.json()).then(s=>{
  document.getElementById('status').textContent =
    s.indexed_chunks + ' passages from ' + s.sources.length + ' document(s) ['+s.retrieval_backend+']';
});

async function ask() {
  const q = document.getElementById('q').value.trim(); if(!q) return;
  const box = document.getElementById('answer'), go = document.getElementById('go');
  go.disabled = true; box.className='answer show'; box.textContent='Searching your documents...';
  try {
    const r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({query:q, k:2})});
    const d = await r.json();
    let html = d.text.replace(/</g,'&lt;');
    if (d.citations && d.citations.length) {
      html += '<div class="cites"><h4>Sources</h4>' + d.citations.map((c,i)=>
        '<div class="cite">'+(i+1)+'. <b>'+c.source+(c.page?(' p.'+c.page):'')+'</b> '+
        '<span>(match '+c.score+')</span></div>').join('') + '</div>';
    }
    box.innerHTML = html;
  } catch(e) { box.textContent = 'Error: ' + e; }
  go.disabled = false;
}
document.getElementById('q').addEventListener('keydown', e=>{ if(e.key==='Enter') ask(); });
</script>
</body>
</html>"""
