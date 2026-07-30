"""The marketing landing page, served at GET /welcome.

Every claim on this page is one the engine can actually back up, and several are things
competitors genuinely cannot say:

  - citations on every answer (verifiable, not "trust me")
  - honest refusal when the answer isn't in your documents (the anti-hallucination guarantee)
  - tested multi-tenant isolation (60 tests, including cross-tenant leak attempts)
  - the engine is open source, so a buyer can read exactly how their documents are handled
  - works with no AI key at all on the free tier

Pricing is rendered from PLANS at request time, so the page can never drift out of sync with
what the product actually enforces.
"""
from __future__ import annotations

from .saas import PLANS, TRIAL_DAYS


def _plan_card(plan, highlight: bool) -> str:
    q = f"{plan.max_questions_per_month:,}"
    rows = [
        f"<li><b>{plan.max_documents:,}</b> documents</li>",
        f"<li><b>{q}</b> questions / month</li>",
        f"<li>Up to <b>{plan.max_upload_mb} MB</b> per file</li>",
        (f"<li class='yes'>AI-written answers</li>" if plan.llm_answers
         else "<li class='no'>Cited passages only</li>"),
        (f"<li class='yes'>Priority support</li>" if plan.priority_support
         else "<li class='no'>Community support</li>"),
    ]
    price = "Free" if plan.price_usd == 0 else f"${plan.price_usd}"
    per = "" if plan.price_usd == 0 else "<span>/month</span>"
    cta = "Start free" if plan.price_usd == 0 else f"Start {TRIAL_DAYS}-day trial"
    return f"""
    <div class="plan{' featured' if highlight else ''}">
      {'<div class="badge">Most popular</div>' if highlight else ''}
      <h3>{plan.label}</h3>
      <div class="price">{price}{per}</div>
      <ul>{''.join(rows)}</ul>
      <a class="btn{' primary' if highlight else ''}" href="/#signup">{cta}</a>
    </div>"""


def landing_html() -> str:
    order = ["free", "starter", "business"]
    cards = "".join(_plan_card(PLANS[k], highlight=(k == "starter")) for k in order)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ragbox - ask your documents, get answers with sources</title>
<meta name="description" content="Upload your PDFs and manuals. Ask questions in plain language.
Every answer cites the exact source, and it tells you when the answer isn't there.">
<style>
  :root {{
    --ink:#14181f; --muted:#5c6875; --line:#e4e9ef; --bg:#ffffff; --soft:#f6f8fb;
    --accent:#1f6feb; --accent-soft:#eaf2ff; --ok:#0f7b3f; --warn:#9a6a00;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); line-height:1.6;
    font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1060px; margin:0 auto; padding:0 24px; }}
  header {{ border-bottom:1px solid var(--line); }}
  nav {{ display:flex; align-items:center; justify-content:space-between; padding:18px 0; }}
  .logo {{ font-weight:800; font-size:22px; letter-spacing:-.02em; }}
  .logo span {{ color:var(--accent); }}
  .nav-links a {{ color:var(--muted); text-decoration:none; margin-left:22px; font-size:15px; }}
  .nav-links a:hover {{ color:var(--ink); }}
  /* ---- buttons: soft, tactile, never jumpy ---- */
  .btn {{ display:inline-block; padding:11px 20px; border-radius:10px; text-decoration:none;
    border:1px solid var(--line); color:var(--ink); font-weight:600; font-size:15px;
    background:#fff; cursor:pointer; position:relative; overflow:hidden;
    transition:transform .18s cubic-bezier(.2,.8,.2,1), box-shadow .22s ease,
               background-color .18s ease, border-color .18s ease; }}
  .btn:hover {{ transform:translateY(-2px); box-shadow:0 8px 20px -10px rgba(20,24,31,.28);
    border-color:#cfd8e3; }}
  .btn:active {{ transform:translateY(0); box-shadow:0 2px 6px -4px rgba(20,24,31,.3); }}
  .btn:focus-visible {{ outline:3px solid var(--accent-soft); outline-offset:2px; }}
  .btn.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  .btn.primary:hover {{ background:#1a62d4; box-shadow:0 10px 26px -10px rgba(31,111,235,.6); }}
  /* a slow sheen that travels across the primary CTA - draws the eye without shouting */
  .btn.primary::after {{ content:""; position:absolute; inset:0;
    background:linear-gradient(110deg,transparent 25%,rgba(255,255,255,.34) 50%,transparent 75%);
    transform:translateX(-120%); }}
  .btn.primary:hover::after {{ transform:translateX(120%); transition:transform .8s ease; }}

  /* ---- modal ---- */
  .overlay {{ position:fixed; inset:0; background:rgba(14,20,28,.55);
    backdrop-filter:blur(3px); display:flex; align-items:center; justify-content:center;
    padding:20px; opacity:0; pointer-events:none; transition:opacity .22s ease; z-index:50; }}
  .overlay.open {{ opacity:1; pointer-events:auto; }}
  .modal {{ background:#fff; border-radius:16px; width:100%; max-width:420px; padding:30px;
    box-shadow:0 30px 70px -20px rgba(14,20,28,.45);
    transform:translateY(14px) scale(.97); opacity:0;
    transition:transform .26s cubic-bezier(.2,.8,.2,1), opacity .26s ease; }}
  .overlay.open .modal {{ transform:translateY(0) scale(1); opacity:1; }}
  .modal h3 {{ margin:0 0 6px; font-size:23px; letter-spacing:-.02em; }}
  .modal .sub {{ color:var(--muted); font-size:15px; margin:0 0 20px; }}
  .modal label {{ display:block; font-size:13px; font-weight:600; color:var(--muted);
    margin:14px 0 6px; }}
  .modal input {{ width:100%; padding:12px 14px; font-size:15px; border:1px solid var(--line);
    border-radius:10px; transition:border-color .18s ease, box-shadow .18s ease; }}
  .modal input:focus {{ outline:none; border-color:var(--accent);
    box-shadow:0 0 0 4px var(--accent-soft); }}
  .modal .btn {{ width:100%; margin-top:20px; }}
  .modal .alt {{ text-align:center; font-size:14px; color:var(--muted); margin-top:16px; }}
  .modal .alt a {{ color:var(--accent); text-decoration:none; font-weight:600; cursor:pointer; }}
  .modal .close {{ position:absolute; top:14px; right:16px; border:0; background:none;
    font-size:24px; color:var(--muted); cursor:pointer; line-height:1; }}
  .modal-wrap {{ position:relative; }}
  .msg {{ font-size:14px; margin-top:14px; padding:10px 12px; border-radius:9px; display:none; }}
  .msg.err {{ display:block; background:#fdecec; color:#9b1c1c; border:1px solid #f6cccc; }}
  .msg.ok {{ display:block; background:#e9f7ef; color:var(--ok); border:1px solid #cdeddb; }}
  .trust {{ font-size:13px; color:var(--muted); text-align:center; margin-top:14px; }}

  /* ---- gentle scroll reveal ---- */
  .reveal {{ opacity:0; transform:translateY(16px);
    transition:opacity .6s ease, transform .6s cubic-bezier(.2,.8,.2,1); }}
  .reveal.in {{ opacity:1; transform:none; }}

  /* respect people who don't want motion */
  @media (prefers-reduced-motion:reduce) {{
    * {{ transition:none !important; animation:none !important; }}
    .reveal {{ opacity:1; transform:none; }}
  }}

  /* hero */
  .hero {{ padding:78px 0 56px; text-align:center; }}
  .hero h1 {{ font-size:52px; line-height:1.1; letter-spacing:-.03em; margin:0 0 18px;
    text-wrap:balance; }}
  .hero p.sub {{ font-size:20px; color:var(--muted); max-width:620px; margin:0 auto 30px; }}
  .hero .cta-row {{ display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }}
  .note {{ font-size:14px; color:var(--muted); margin-top:14px; }}

  /* proof panel */
  .proof {{ background:var(--soft); border:1px solid var(--line); border-radius:14px;
    padding:22px 24px; margin:48px 0 8px; text-align:left; }}
  .proof .q {{ font-weight:600; }}
  .proof .a {{ margin-top:10px; padding-top:12px; border-top:1px solid var(--line); }}
  .cite {{ display:inline-block; margin-top:10px; font-size:14px; color:var(--ok);
    background:#e9f7ef; border:1px solid #cdeddb; border-radius:999px; padding:4px 12px; }}
  .refuse {{ color:var(--warn); background:#fdf6e3; border-color:#f0e2b6; }}

  /* sections */
  section {{ padding:62px 0; border-top:1px solid var(--line); }}
  h2 {{ font-size:32px; letter-spacing:-.02em; margin:0 0 10px; text-wrap:balance; }}
  .lead {{ color:var(--muted); font-size:18px; margin:0 0 34px; max-width:640px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:20px; }}
  .card {{ border:1px solid var(--line); border-radius:14px; padding:24px; }}
  .card h3 {{ margin:0 0 8px; font-size:18px; }}
  .card p {{ margin:0; color:var(--muted); font-size:15.5px; }}
  .card .tag {{ font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
    color:var(--accent); background:var(--accent-soft); border-radius:6px; padding:3px 8px;
    display:inline-block; margin-bottom:10px; }}

  /* pricing */
  .plans {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:20px;
    align-items:start; }}
  .plan {{ border:1px solid var(--line); border-radius:14px; padding:26px; position:relative; }}
  .plan.featured {{ border-color:var(--accent); box-shadow:0 10px 30px -18px rgba(31,111,235,.5); }}
  .badge {{ position:absolute; top:-12px; left:26px; background:var(--accent); color:#fff;
    font-size:12px; font-weight:700; padding:4px 10px; border-radius:999px; }}
  .plan h3 {{ margin:0 0 4px; font-size:19px; }}
  .price {{ font-size:38px; font-weight:800; letter-spacing:-.02em; margin:6px 0 16px; }}
  .price span {{ font-size:15px; font-weight:500; color:var(--muted); }}
  .plan ul {{ list-style:none; padding:0; margin:0 0 22px; }}
  .plan li {{ padding:7px 0 7px 26px; position:relative; font-size:15.5px;
    border-top:1px solid var(--line); }}
  .plan li:first-child {{ border-top:0; }}
  .plan li::before {{ content:"✓"; position:absolute; left:0; color:var(--ok); font-weight:700; }}
  .plan li.no::before {{ content:"–"; color:var(--muted); }}
  .plan li.yes::before {{ content:"★"; color:var(--accent); }}
  .plan .btn {{ display:block; text-align:center; }}

  footer {{ border-top:1px solid var(--line); padding:34px 0; color:var(--muted); font-size:14px;
    display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px; }}
  footer a {{ color:var(--accent); text-decoration:none; }}
  @media (max-width:640px) {{ .hero h1 {{ font-size:36px; }} .hero p.sub {{ font-size:17px; }} }}
</style></head>
<body>

<header><div class="wrap"><nav>
  <div class="logo">rag<span>box</span></div>
  <div class="nav-links">
    <a href="#how">How it works</a><a href="#why">Why ragbox</a><a href="#pricing">Pricing</a>
    <a class="btn primary" href="/#signup" style="margin-left:22px">Start free</a>
  </div>
</nav></div></header>

<div class="wrap">
  <div class="hero">
    <h1>Ask your documents.<br>Get answers you can check.</h1>
    <p class="sub">Upload your PDFs, manuals and policies. Ask a question in plain language and
      get the answer <b>with the exact source and page</b> it came from.</p>
    <div class="cta-row">
      <a class="btn primary" href="/#signup">Start free - no card</a>
      <a class="btn" href="#how">See how it works</a>
    </div>
    <div class="note">Free plan forever. {TRIAL_DAYS}-day trial of AI answers, no card required.</div>

    <div class="proof">
      <div class="q">Q: "Can I get a refund after 30 days?"</div>
      <div class="a">Customers may request a full refund within 30 days of purchase. After 30
        days, refunds are issued as store credit only.
        <div><span class="cite">Source: company_handbook.pdf, p.2</span></div>
      </div>
      <div class="a">Q: "Do you sell helicopters?"<br>
        <span style="color:var(--muted)">I couldn't find that in your documents.</span>
        <div><span class="cite refuse">Says "I don't know" instead of inventing an answer</span></div>
      </div>
    </div>
  </div>
</div>

<div class="wrap">
<section id="why">
  <h2>What makes it different</h2>
  <p class="lead">Most document AI tools give you a confident paragraph and hope you don't check it.
    ragbox is built the other way round.</p>
  <div class="grid">
    <div class="card"><span class="tag">Verifiable</span>
      <h3>Every answer cites its source</h3>
      <p>File name, page number, and the passage it came from. You never have to take the
        answer on faith, and neither do your customers.</p></div>
    <div class="card"><span class="tag">Honest</span>
      <h3>It admits when it doesn't know</h3>
      <p>If the answer isn't in your documents it says so, instead of inventing something
        plausible. That's what makes it safe to put in front of real customers.</p></div>
    <div class="card"><span class="tag">Private</span>
      <h3>Your documents stay yours</h3>
      <p>Each account has its own isolated storage and its own search index. Nothing is shared,
        pooled, or used to train anything.</p></div>
    <div class="card"><span class="tag">Proven</span>
      <h3>Isolation is tested, not promised</h3>
      <p>60 automated tests, including ones that deliberately try to read another account's
        documents and must fail. We test for the leak we'd be fired for.</p></div>
    <div class="card"><span class="tag">Open</span>
      <h3>The engine is open source</h3>
      <p>Read exactly how your documents are handled, or run it on your own server. No black
        box, no lock-in.</p></div>
    <div class="card"><span class="tag">Fast</span>
      <h3>Answers in milliseconds</h3>
      <p>Around 1 ms to search thousands of passages, so asking feels instant even on a large
        document library.</p></div>
  </div>
</section>

<section id="how">
  <h2>Three steps</h2>
  <p class="lead">No setup, no training, no configuration files.</p>
  <div class="grid">
    <div class="card"><span class="tag">Step 1</span><h3>Upload</h3>
      <p>Drop in your PDFs, Word files or text. Handbooks, product manuals, policies,
        contracts - whatever people keep asking about.</p></div>
    <div class="card"><span class="tag">Step 2</span><h3>Ask</h3>
      <p>Type a question the way a person would. No keywords, no syntax.</p></div>
    <div class="card"><span class="tag">Step 3</span><h3>Check</h3>
      <p>Read the answer and click straight through to the source. Trust it because you can
        verify it.</p></div>
  </div>
</section>

<section id="pricing">
  <h2>Simple monthly pricing</h2>
  <p class="lead">Start free and stay free if it suits you. Upgrade when you want AI-written
    answers and room to grow. Cancel any time - you keep access until the month you paid for ends.</p>
  <div class="plans">{cards}</div>
  <p class="note" style="margin-top:22px">Prices in USD, billed monthly. The free plan gives you
    cited passages from your documents; paid plans add AI-written answers on top of the same
    citations.</p>
</section>
</div>

<footer><div class="wrap" style="display:flex;justify-content:space-between;width:100%;flex-wrap:wrap;gap:12px">
  <div>ragbox - ask your documents, get answers with sources.</div>
  <div><a href="https://github.com/junaidshahid-dev/ragbox">Source on GitHub</a> ·
       <a href="/docs">API</a> · <a href="/">Demo</a></div>
</div></footer>

<!-- signup / login modal: opens instantly so a visitor never leaves the page to convert -->
<div class="overlay" id="overlay" role="dialog" aria-modal="true" aria-labelledby="mtitle">
  <div class="modal-wrap">
    <div class="modal">
      <button class="close" id="mclose" aria-label="Close">&times;</button>
      <h3 id="mtitle">Create your account</h3>
      <p class="sub" id="msub">Free forever. No card, no sales call.</p>
      <form id="mform" novalidate>
        <label for="memail">Work email</label>
        <input id="memail" type="email" autocomplete="email" placeholder="you@company.com" required>
        <label for="mpass">Password</label>
        <input id="mpass" type="password" autocomplete="new-password"
               placeholder="At least 8 characters" required minlength="8">
        <button class="btn primary" type="submit" id="msubmit">Create account</button>
      </form>
      <div class="msg" id="mmsg" role="status" aria-live="polite"></div>
      <div class="alt" id="malt">Already have an account? <a id="mtoggle">Sign in</a></div>
      <div class="trust">Your documents stay private to your account.</div>
    </div>
  </div>
</div>

<script>
(function () {{
  var overlay = document.getElementById('overlay');
  var form    = document.getElementById('mform');
  var msg     = document.getElementById('mmsg');
  var submit  = document.getElementById('msubmit');
  var title   = document.getElementById('mtitle');
  var sub     = document.getElementById('msub');
  var alt     = document.getElementById('malt');
  var toggle  = document.getElementById('mtoggle');
  var email   = document.getElementById('memail');
  var mode    = 'signup';
  var lastFocus = null;

  function render() {{
    var signup = mode === 'signup';
    title.textContent  = signup ? 'Create your account' : 'Welcome back';
    sub.textContent    = signup ? 'Free forever. No card, no sales call.'
                                : 'Sign in to your documents.';
    submit.textContent = signup ? 'Create account' : 'Sign in';
    document.getElementById('mpass').setAttribute(
      'autocomplete', signup ? 'new-password' : 'current-password');
    alt.innerHTML = signup
      ? 'Already have an account? <a id="mtoggle">Sign in</a>'
      : 'New here? <a id="mtoggle">Create an account</a>';
    document.getElementById('mtoggle').onclick = function () {{
      mode = signup ? 'login' : 'signup'; msg.className = 'msg'; render();
    }};
  }}

  function open(next) {{
    mode = next || 'signup'; render();
    msg.className = 'msg';
    lastFocus = document.activeElement;
    overlay.classList.add('open');
    setTimeout(function () {{ email.focus(); }}, 120);   // after the transition, not during
  }}
  function close() {{
    overlay.classList.remove('open');
    if (lastFocus) lastFocus.focus();
  }}

  // any link pointing at #signup opens the modal instead of navigating
  document.querySelectorAll('a[href="/#signup"], a[href="#signup"]').forEach(function (a) {{
    a.addEventListener('click', function (e) {{ e.preventDefault(); open('signup'); }});
  }});
  document.getElementById('mclose').onclick = close;
  overlay.addEventListener('click', function (e) {{ if (e.target === overlay) close(); }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape' && overlay.classList.contains('open')) close();
  }});

  form.addEventListener('submit', async function (e) {{
    e.preventDefault();
    var pass = document.getElementById('mpass').value;
    if (!email.value.includes('@')) {{
      msg.className = 'msg err'; msg.textContent = 'Please enter a valid email address.'; return;
    }}
    if (pass.length < 8) {{
      msg.className = 'msg err'; msg.textContent = 'Password must be at least 8 characters.'; return;
    }}
    submit.disabled = true;
    submit.textContent = mode === 'signup' ? 'Creating your account...' : 'Signing in...';
    try {{
      var r = await fetch('/' + mode, {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ email: email.value.trim(), password: pass }})
      }});
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Something went wrong. Please try again.');
      msg.className = 'msg ok';
      msg.textContent = "You're in. Taking you to your documents...";
      setTimeout(function () {{ window.location.href = '/'; }}, 700);
    }} catch (err) {{
      msg.className = 'msg err'; msg.textContent = err.message;
      submit.disabled = false;
      submit.textContent = mode === 'signup' ? 'Create account' : 'Sign in';
    }}
  }});

  // gentle scroll reveal for cards and plans
  var targets = document.querySelectorAll('.card, .plan, .proof');
  targets.forEach(function (el) {{ el.classList.add('reveal'); }});
  if ('IntersectionObserver' in window) {{
    var io = new IntersectionObserver(function (entries) {{
      entries.forEach(function (en, i) {{
        if (en.isIntersecting) {{
          setTimeout(function () {{ en.target.classList.add('in'); }}, i * 70);  // slight stagger
          io.unobserve(en.target);
        }}
      }});
    }}, {{ threshold: 0.12 }});
    targets.forEach(function (el) {{ io.observe(el); }});
  }} else {{
    targets.forEach(function (el) {{ el.classList.add('in'); }});
  }}
}})();
</script>

</body></html>"""
