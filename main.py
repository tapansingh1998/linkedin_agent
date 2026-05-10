"""
FastAPI app — the spine of the pipeline.

Routes:
  GET  /                    → Dashboard (status, logs, manual trigger)
  GET  /health              → Render health check
  POST /run                 → Manually trigger the full pipeline
  GET  /approve/{token}     → Approval link from email → posts to LinkedIn
  GET  /auth/linkedin       → Start LinkedIn OAuth flow
  GET  /auth/callback       → LinkedIn OAuth callback
  GET  /status              → JSON pipeline status
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    SCHEDULE_DAYS, SCHEDULE_HOUR_UTC, SCHEDULE_MINUTE_UTC,
    APP_BASE_URL, LINKEDIN_CLIENT_ID
)
from agents import topic_agent, post_agent, email_agent, linkedin_agent

# ── In-memory run log (last 20 runs) ────────────────────────────────────────
run_log: list[dict] = []
pipeline_status = {"state": "idle", "last_run": None, "next_run": None}


# ── Core pipeline ─────────────────────────────────────────────────────────────

async def run_pipeline(triggered_by: str = "scheduler") -> dict:
    """
    Full agentic pipeline:
    1. Topic discovery
    2. Send five topic options for selection
    """
    entry = {
        "run_id":       datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "triggered_by": triggered_by,
        "started_at":   datetime.now(timezone.utc).isoformat(),
        "status":       "running",
        "topic":        None,
        "topics":       None,
        "post_preview": None,
        "error":        None,
    }
    run_log.insert(0, entry)
    if len(run_log) > 20:
        run_log.pop()

    pipeline_status["state"] = "running"

    try:
        # Agent 1 — topic
        topics = await asyncio.to_thread(topic_agent.run)
        entry["topics"] = [topic["topic"] for topic in topics]
        entry["topic"] = f"{len(topics)} topic options sent"

        # Agent 2 — post generation
        tokenized_topics = await asyncio.to_thread(email_agent.send_topic_selection_email, topics)

        # Agent 3 — email for approval
        entry["status"]   = "awaiting_topic_selection"
        entry["topic_tokens"] = [item["token"] for item in tokenized_topics]
        pipeline_status["state"]    = "awaiting_topic_selection"
        pipeline_status["last_run"] = entry["started_at"]

        print(f"[pipeline] Run {entry['run_id']} complete - awaiting topic selection")
        return entry

    except Exception as exc:
        entry["status"] = "error"
        entry["error"]  = str(exc)
        pipeline_status["state"] = "error"
        print(f"[pipeline] ERROR: {exc}")
        raise


# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="UTC")

def _build_cron_days() -> str:
    day_map = {"mon":"0","tue":"1","wed":"2","thu":"3","fri":"4","sat":"5","sun":"6"}
    return ",".join(day_map[d] for d in SCHEDULE_DAYS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler
    day_of_week = _build_cron_days()
    scheduler.add_job(
        run_pipeline,
        CronTrigger(
            day_of_week=day_of_week,
            hour=SCHEDULE_HOUR_UTC,
            minute=SCHEDULE_MINUTE_UTC,
            timezone="UTC",
        ),
        id="weekly_pipeline",
        kwargs={"triggered_by": "scheduler"},
        replace_existing=True,
    )
    scheduler.start()
    job = scheduler.get_job("weekly_pipeline")
    pipeline_status["next_run"] = str(job.next_run_time) if job else None
    print(f"[scheduler] Started — next run: {pipeline_status['next_run']}")
    yield
    scheduler.shutdown()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="LinkedIn AI Agent", lifespan=lifespan)


# ── Dashboard HTML ────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn AI Agent</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0c0c10;
  --surface: #13131a;
  --surface2: #1a1a24;
  --border: rgba(255,255,255,0.07);
  --accent: #4f8ef7;
  --accent2: #a78bfa;
  --green: #34d399;
  --amber: #fbbf24;
  --red: #f87171;
  --text: #e8e8f0;
  --muted: #6b6b80;
  --mono: 'DM Mono', monospace;
  --sans: 'Syne', sans-serif;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
  padding: 0;
}

/* Noise texture overlay */
body::before {
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
  opacity: 0.4;
}

.layout { position:relative; z-index:1; max-width:900px; margin:0 auto; padding:40px 24px 80px; }

/* Header */
.header { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:48px; flex-wrap:wrap; gap:16px; }
.logo { display:flex; align-items:center; gap:12px; }
.logo-dot { width:10px; height:10px; border-radius:50%; background:var(--accent); box-shadow:0 0 12px var(--accent); animation:pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.logo h1 { font-size:22px; font-weight:800; letter-spacing:-.02em; }
.logo span { color:var(--accent); }
.badge { font-family:var(--mono); font-size:11px; padding:4px 10px; border-radius:4px; background:var(--surface2); border:1px solid var(--border); color:var(--muted); }

/* Status bar */
.statusbar { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px 24px; margin-bottom:24px; display:flex; align-items:center; gap:20px; flex-wrap:wrap; }
.status-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.status-idle    { background:var(--muted); }
.status-running { background:var(--amber); box-shadow:0 0 8px var(--amber); animation:pulse 1s linear infinite; }
.status-awaiting_approval { background:var(--accent); box-shadow:0 0 8px var(--accent); }
.status-error   { background:var(--red); box-shadow:0 0 8px var(--red); }
.status-label { font-family:var(--mono); font-size:13px; text-transform:uppercase; letter-spacing:.06em; }
.status-meta { font-size:13px; color:var(--muted); margin-left:auto; }

/* Grid */
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }
@media(max-width:560px){ .grid2{grid-template-columns:1fr;} }

.card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px 24px; }
.card-label { font-family:var(--mono); font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; margin-bottom:8px; }
.card-value { font-size:22px; font-weight:700; }
.card-sub { font-size:12px; color:var(--muted); margin-top:4px; font-family:var(--mono); }

/* Trigger panel */
.trigger-panel { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; margin-bottom:24px; }
.trigger-panel h2 { font-size:16px; font-weight:700; margin-bottom:16px; }
.btn-row { display:flex; gap:12px; flex-wrap:wrap; }

.btn { font-family:var(--sans); font-size:13px; font-weight:600; padding:10px 22px; border-radius:8px; border:none; cursor:pointer; transition:all .15s; letter-spacing:.01em; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { filter:brightness(1.15); transform:translateY(-1px); }
.btn-primary:active { transform:translateY(0); }
.btn-secondary { background:transparent; color:var(--text); border:1px solid var(--border); }
.btn-secondary:hover { background:var(--surface2); }
.btn:disabled { opacity:.4; cursor:not-allowed; transform:none!important; }

/* Schedule info */
.schedule-chip { display:inline-flex; align-items:center; gap:8px; background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:8px 14px; font-family:var(--mono); font-size:12px; color:var(--accent2); }

/* Log */
.log-panel { background:var(--surface); border:1px solid var(--border); border-radius:12px; overflow:hidden; }
.log-header { padding:16px 24px; border-bottom:1px solid var(--border); font-size:15px; font-weight:700; display:flex; align-items:center; gap:10px; }
.log-empty { padding:32px 24px; font-family:var(--mono); font-size:13px; color:var(--muted); text-align:center; }
.log-entry { padding:16px 24px; border-bottom:1px solid var(--border); display:grid; grid-template-columns:auto 1fr auto; gap:12px; align-items:start; font-size:13px; }
.log-entry:last-child { border-bottom:none; }
.run-id { font-family:var(--mono); font-size:11px; color:var(--muted); }
.run-topic { color:var(--text); margin-top:3px; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:400px; }
.run-preview { color:var(--muted); font-size:12px; margin-top:4px; font-family:var(--mono); }
.pill { font-size:10px; font-family:var(--mono); padding:3px 8px; border-radius:4px; font-weight:500; white-space:nowrap; }
.pill-awaiting { background:rgba(79,142,247,.15); color:var(--accent); }
.pill-error     { background:rgba(248,113,113,.15); color:var(--red); }
.pill-running   { background:rgba(251,191,36,.15); color:var(--amber); }
.pill-done      { background:rgba(52,211,153,.15); color:var(--green); }

/* Toast */
#toast { position:fixed; bottom:24px; right:24px; background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:14px 20px; font-size:14px; font-weight:600; transform:translateY(80px); opacity:0; transition:all .3s; z-index:99; }
#toast.show { transform:translateY(0); opacity:1; }

/* Auth link */
.auth-link { font-size:12px; font-family:var(--mono); color:var(--muted); }
.auth-link a { color:var(--accent2); }
</style>
</head>
<body>
<div class="layout">

  <div class="header">
    <div class="logo">
      <div class="logo-dot"></div>
      <h1>LinkedIn <span>AI</span> Agent</h1>
    </div>
    <div class="badge">Tapan Singh · AI Engineer</div>
  </div>

  <div class="statusbar" id="statusbar">
    <div class="status-dot status-idle" id="status-dot"></div>
    <span class="status-label" id="status-label">Idle</span>
    <span class="status-meta" id="status-meta">–</span>
  </div>

  <div class="grid2">
    <div class="card">
      <div class="card-label">Schedule</div>
      <div class="card-value">Wed + Thu</div>
      <div class="card-sub">09:00 AM IST · every week</div>
    </div>
    <div class="card">
      <div class="card-label">Next run</div>
      <div class="card-value" id="next-run-val">–</div>
      <div class="card-sub" id="next-run-sub">UTC</div>
    </div>
  </div>

  <div class="trigger-panel">
    <h2>Controls</h2>
    <div class="btn-row">
      <button class="btn btn-primary" id="run-btn" onclick="triggerRun()">Run pipeline now</button>
      <button class="btn btn-secondary" onclick="refreshStatus()">Refresh status</button>
    </div>
    <div style="margin-top:16px;">
      <span class="auth-link">LinkedIn auth: <a href="/auth/linkedin">Connect LinkedIn account</a></span>
    </div>
  </div>

  <div class="log-panel">
    <div class="log-header">
      <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
      Run Log
    </div>
    <div id="log-container"><div class="log-empty">No runs yet. Hit "Run pipeline now" to start.</div></div>
  </div>

</div>

<div id="toast"></div>

<script>
function toast(msg, color='#4f8ef7'){
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.borderColor = color;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 3000);
}

async function refreshStatus(){
  const data = await fetch('/status').then(r=>r.json());

  const dot = document.getElementById('status-dot');
  dot.className = 'status-dot status-' + data.state;
  document.getElementById('status-label').textContent = data.state.replace(/_/g,' ');
  document.getElementById('status-meta').textContent =
    data.last_run ? 'Last: ' + new Date(data.last_run).toLocaleString() : '–';

  if(data.next_run){
    const d = new Date(data.next_run);
    document.getElementById('next-run-val').textContent = d.toLocaleDateString('en-IN',{weekday:'short',month:'short',day:'numeric'});
    document.getElementById('next-run-sub').textContent = d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}) + ' IST';
  }

  // Render log
  const log = data.run_log || [];
  const container = document.getElementById('log-container');
  if(!log.length){ container.innerHTML='<div class="log-empty">No runs yet.</div>'; return; }

  container.innerHTML = log.map(r=>`
    <div class="log-entry">
      <div>
        <div class="run-id">${r.run_id}</div>
        <div style="font-size:11px;color:var(--muted);margin-top:2px;">${r.triggered_by}</div>
      </div>
      <div>
        <div class="run-topic">${r.topic||'–'}</div>
        <div class="run-preview">${r.post_preview||''}</div>
        ${r.error?`<div style="color:var(--red);font-size:11px;margin-top:4px;">${r.error}</div>`:''}
      </div>
      <div>
        <span class="pill pill-${r.status.startsWith('awaiting_')?'awaiting':r.status}">${r.status}</span>
      </div>
    </div>
  `).join('');
}

async function triggerRun(){
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Running…';
  try{
    const res = await fetch('/run', {method:'POST'});
    const data = await res.json();
    if(res.ok){ toast('Pipeline started! Check your email soon.'); }
    else{ toast('Error: '+data.detail, '#f87171'); }
  }catch(e){ toast('Network error','#f87171'); }
  btn.disabled = false; btn.textContent = 'Run pipeline now';
  setTimeout(refreshStatus, 1000);
}

refreshStatus();
setInterval(refreshStatus, 15000);
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


@app.get("/health")
async def health():
    return {"status": "ok", "service": "linkedin-ai-agent"}


@app.get("/status")
async def status():
    job = scheduler.get_job("weekly_pipeline")
    pipeline_status["next_run"] = str(job.next_run_time) if job else None
    return {**pipeline_status, "run_log": run_log}


@app.post("/run")
async def manual_run(background_tasks: BackgroundTasks):
    if pipeline_status["state"] == "running":
        raise HTTPException(status_code=409, detail="Pipeline already running")
    background_tasks.add_task(run_pipeline, "manual")
    return {"message": "Pipeline started", "triggered_by": "manual"}


@app.get("/select-topic/{token}")
async def select_topic(token: str):
    data = email_agent.get_pending_topic(token)
    if not data:
        raise HTTPException(status_code=404, detail="Topic token not found or already used")

    topic = data["topic"]
    pipeline_status["state"] = "running"

    try:
        post_text = await asyncio.to_thread(post_agent.run, topic)
        approval_token = await asyncio.to_thread(email_agent.send_approval_email, post_text, topic)

        for entry in run_log:
            if token in entry.get("topic_tokens", []):
                entry["status"] = "awaiting_approval"
                entry["topic"] = topic.get("topic")
                entry["post_preview"] = post_text[:120] + "..."
                entry["token"] = approval_token
                break

        pipeline_status["state"] = "awaiting_approval"

        return HTMLResponse("""
        <html><head><title>Draft Created</title>
        <link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;800&display=swap" rel="stylesheet">
        <style>body{background:#0c0c10;color:#e8e8f0;font-family:'Syne',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
        .box{text-align:center;max-width:520px;padding:40px;}.icon{font-size:42px;margin-bottom:16px;}
        h1{font-size:28px;font-weight:800;color:#4f8ef7;margin-bottom:8px;}
        p{color:#b8b8c8;font-size:15px;line-height:1.6;}
        a{color:#4f8ef7;font-size:13px;}</style></head><body>
        <div class="box">
          <div class="icon">&#9997;</div>
          <h1>Draft generated</h1>
          <p>Your LinkedIn post draft has been generated and sent to your email for final approval.</p>
          <br><a href="/">Back to dashboard</a>
        </div></body></html>
        """)
    except Exception as e:
        pipeline_status["state"] = "error"
        for entry in run_log:
            if token in entry.get("topic_tokens", []):
                entry["status"] = "error"
                entry["error"] = str(e)
                break
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/approve/{token}")
async def approve_post(token: str):
    data = email_agent.get_pending_post(token)
    if not data:
        raise HTTPException(status_code=404, detail="Token not found or already used")

    post_text = data["post"]
    topic     = data["topic"]

    try:
        result = await asyncio.to_thread(linkedin_agent.run_post, post_text)
        # Update last run log entry
        for entry in run_log:
            if entry.get("token") == token:
                entry["status"] = "published"
                break
        pipeline_status["state"] = "idle"

        return HTMLResponse(f"""
        <html><head><title>Posted!</title>
        <link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;800&display=swap" rel="stylesheet">
        <style>body{{background:#0c0c10;color:#e8e8f0;font-family:'Syne',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}}
        .box{{text-align:center;max-width:480px;padding:40px;}}.icon{{font-size:48px;margin-bottom:16px;}}
        h1{{font-size:28px;font-weight:800;color:#34d399;margin-bottom:8px;}}
        p{{color:#6b6b80;font-size:15px;line-height:1.6;}}
        a{{color:#4f8ef7;font-size:13px;}}
        </style></head><body>
        <div class="box">
          <div class="icon">&#10003;</div>
          <h1>Published to LinkedIn!</h1>
          <p>Your post about "<em>{topic.get('topic','')[:60]}</em>" is now live on your profile.</p>
          <br><a href="/">Back to dashboard</a>
        </div></body></html>
        """)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── LinkedIn OAuth ─────────────────────────────────────────────────────────────

@app.get("/auth/linkedin")
async def linkedin_auth():
    url = linkedin_agent.get_auth_url()
    if LINKEDIN_CLIENT_ID == "DUMMY_CLIENT_ID":
        return JSONResponse({"message": "Dummy mode — replace LINKEDIN_CLIENT_ID in config.py", "would_redirect_to": url})
    return RedirectResponse(url)


@app.get("/auth/callback")
async def linkedin_callback(code: str, state: str = ""):
    token = await asyncio.to_thread(linkedin_agent.exchange_code_for_token, code)
    return HTMLResponse("""
    <html><head><title>Auth complete</title>
    <style>body{background:#0c0c10;color:#e8e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}
    .box{text-align:center;} h1{color:#34d399;} a{color:#4f8ef7;}</style></head>
    <body><div class="box"><h1>LinkedIn connected!</h1><p>Token saved. <a href="/">Go to dashboard</a></p></div></body></html>
    """)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
