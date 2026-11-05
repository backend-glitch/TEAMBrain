"""Read-only HTTP dashboard for TeamBrain."""

import sqlite3
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from server import messages


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TeamBrain</title>
  <style>
    :root{color-scheme:dark;font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--bg:#0b0e12;--panel:#12171e;--panel2:#171e27;--line:#26313d;--muted:#8996a5;--text:#e8edf3;--accent:#67d4b5;--amber:#e7ad59}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 50% -20%,#17252b 0,transparent 48%),var(--bg);color:var(--text)}button,input{font:inherit}button{cursor:pointer;color:inherit}
    .shell{max-width:1120px;margin:auto;padding:28px 24px 60px}.topbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding-bottom:22px;border-bottom:1px solid var(--line)}
    .brand{font-size:23px;font-weight:750;letter-spacing:-.04em;margin:0}.version{font-size:12px;border:1px solid #34554e;background:#12251f;color:var(--accent);padding:4px 9px;border-radius:999px}
    .live{margin-left:auto;color:var(--muted);font-size:12px;display:flex;align-items:center;gap:8px}.dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px #67d4b588}
    .unlock{position:relative}.unlock summary{list-style:none;border:1px solid var(--line);background:var(--panel);border-radius:9px;padding:8px 11px;color:#bdc8d3;font-size:12px;cursor:pointer}.unlock summary::-webkit-details-marker{display:none}.tokenbox{position:absolute;z-index:3;right:0;top:42px;width:min(320px,88vw);padding:14px;background:var(--panel2);border:1px solid var(--line);border-radius:12px;box-shadow:0 14px 42px #0009}.tokenbox label{display:block;color:var(--muted);font-size:12px;margin-bottom:7px}.tokenrow{display:flex;gap:7px}.tokenrow input{min-width:0;flex:1;background:#0c1117;border:1px solid var(--line);border-radius:7px;color:var(--text);padding:9px}.tokenrow button{border:0;border-radius:7px;background:var(--accent);color:#092019;padding:0 12px;font-weight:700}.hint{font-size:11px;color:var(--muted);margin:8px 0 0}
    #status{min-height:20px;color:var(--muted);font-size:12px;margin:14px 0 8px}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0 24px}.stat,.proposal{background:var(--panel);border:1px solid var(--line);border-radius:12px}.stat{padding:14px 16px}.stat span{display:block;color:var(--muted);font-size:12px}.stat strong{display:block;font-size:25px;line-height:1.2;margin-top:6px;letter-spacing:-.04em}.stat.open strong{color:#86b9ff}.stat.accepted strong{color:var(--accent)}.stat.escalated strong{color:var(--amber)}.stat.rejected strong{color:#ee8d98}
    .filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:4px 0 22px}.filter-label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.09em;margin-right:2px}.chip{border:1px solid var(--line);background:transparent;color:#aab5c1;border-radius:999px;padding:6px 11px;font-size:12px}.chip.active{background:#183129;border-color:#346958;color:#a5f0d9}.filter-gap{width:8px}
    h2{font-size:15px;letter-spacing:-.01em;margin:28px 0 11px}.section-note{color:var(--muted);font-weight:400;font-size:12px;margin-left:7px}.list{display:grid;gap:10px}.proposal{overflow:hidden;transition:border-color .18s,background .18s}.proposal:hover{border-color:#3a4a59;background:#141b23}.proposal.escalation{border-color:#765a31;background:linear-gradient(110deg,#211b12,var(--panel) 44%)}.proposal-head{width:100%;text-align:left;background:none;border:0;padding:15px 17px;display:block}.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.titleline{font-weight:620;min-width:0;flex:1;overflow-wrap:anywhere}.status-pill,.role,.type,.warning{display:inline-flex;align-items:center;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.045em;padding:3px 8px;text-transform:uppercase;white-space:nowrap}.status-open{background:#17283b;color:#8bbcff}.status-accepted{background:#132b24;color:#82e1bd}.status-escalated{background:#382915;color:#f0bd69}.status-rejected{background:#351d24;color:#f19aa5}.role-uiux{background:#302039;color:#d8adf2}.role-frontend{background:#16323a;color:#87d7e8}.role-backend{background:#33271a;color:#e8bd85}.role-other{background:#252d36;color:#bdc8d3}.type{background:#252d36;color:#bec9d5}.warning{background:#3b2b13;color:#f1c36f}.subline{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:11px}.subline .sep{opacity:.45}.thread{display:grid;grid-template-rows:0fr;transition:grid-template-rows .24s ease}.proposal.expanded .thread{grid-template-rows:1fr}.thread-inner{overflow:hidden;min-height:0}.timeline{margin:0 17px 16px 23px;padding:2px 0 0 17px;border-left:1px solid #35434f}.message{position:relative;padding:0 0 15px 0}.message:last-child{padding-bottom:2px}.message:before{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:#718091;left:-21px;top:6px;box-shadow:0 0 0 3px var(--panel)}.message-meta{display:flex;align-items:center;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:11px}.message-body{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0 0;color:#dce3ea;font-size:13px}.empty{border:1px dashed #34404b;border-radius:11px;padding:22px;text-align:center;color:var(--muted);background:#10151b}.empty strong{display:block;color:#c4ced8;margin-bottom:4px}.section{margin-top:4px}.hidden{display:none!important}
    @media(max-width:620px){.shell{padding:18px 14px 40px}.topbar{gap:10px}.brand{font-size:21px}.live{order:3;width:100%;margin-left:0}.unlock{margin-left:auto}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.stat{padding:12px}.stat strong{font-size:22px}.proposal-head{padding:13px}.titleline{flex-basis:100%;order:2}.status-pill{order:1}.timeline{margin-left:17px}}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important}}
  </style>
</head>
<body><main class="shell">
  <header class="topbar"><h1 class="brand">TeamBrain</h1><span id="version" class="version">Contract v—</span><div class="live"><i class="dot"></i><span id="updated">Waiting for data</span></div>
    <details class="unlock"><summary>Unlock dashboard</summary><div class="tokenbox"><label for="token">Dashboard token</label><div class="tokenrow"><input id="token" type="password" autocomplete="off" spellcheck="false"><button id="connect" type="button">Connect</button></div><p class="hint">Stored in this tab only. Sent in the authorization header.</p></div></details>
  </header>
  <div id="status" role="status">Enter your dashboard token to load the shared workspace.</div>
  <section id="stats" class="stats" aria-label="Proposal counts"></section>
  <nav id="filters" class="filters" aria-label="Filter proposals"></nav>
  <section class="section"><h2>Needs human attention <span id="escalated-count" class="section-note"></span></h2><div id="escalated" class="list"></div></section>
  <section class="section"><h2>Proposals <span id="proposal-count" class="section-note"></span></h2><div id="proposals" class="list"></div></section>
</main>
<script>
  "use strict";
  const tokenInput=document.getElementById("token"),statusNode=document.getElementById("status"),storageKey="teambrain-dashboard-token";
  const countsNode=document.getElementById("stats"),filtersNode=document.getElementById("filters"),proposalNode=document.getElementById("proposals"),escalatedNode=document.getElementById("escalated");
  let dataset=null,lastSuccess=null,selectedStatus="all",selectedRole="all";
  try{tokenInput.value=sessionStorage.getItem(storageKey)||""}catch(_){}
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text==null?"":String(text);return n}
  function roleTag(role){const r=String(role||"unknown").toLowerCase(),known=["uiux","frontend","backend"].includes(r);return el("span",`role role-${known?r:"other"}`,role||"unknown")}
  function relative(value){const t=Date.parse(value||"");if(!Number.isFinite(t))return "time unknown";const sec=Math.max(0,Math.floor((Date.now()-t)/1000));if(sec<60)return "just now";if(sec<3600)return `${Math.floor(sec/60)} min ago`;if(sec<86400)return `${Math.floor(sec/3600)} hr ago`;if(sec<604800)return `${Math.floor(sec/86400)} days ago`;return new Date(t).toLocaleDateString()}
  function makeMessage(m){const item=el("article","message"),meta=el("div","message-meta");meta.append(roleTag(m.from_role),el("span","type",m.type||"message"),el("span","",relative(m.created_at)));if(m.warning)meta.append(el("span","warning","Stale context"));item.append(meta,el("p","message-body",m.body||""));return item}
  function makeProposal(p,highlight){const card=el("article",`proposal${highlight?" escalation":""}`),head=el("button","proposal-head");head.type="button";head.setAttribute("aria-expanded","false");const row=el("div","row");row.append(el("span",`status-pill status-${p.status||"open"}`,p.status||"unknown"),el("span","titleline",p.body||p.id));const sub=el("div","subline");sub.append(roleTag(p.from_role),el("span","sep","→"),roleTag(p.to_role),el("span","sep","·"),el("span","",relative(p.created_at)));if(p.thread&&p.thread.some(m=>m.warning))sub.append(el("span","warning","Stale context"));head.append(row,sub);const panel=el("div","thread"),inner=el("div","thread-inner"),timeline=el("div","timeline");for(const m of (p.thread||[]))timeline.append(makeMessage(m));if(!(p.thread||[]).length)timeline.append(el("p","empty","No messages in this thread yet."));inner.append(timeline);panel.append(inner);head.addEventListener("click",()=>{const open=card.classList.toggle("expanded");head.setAttribute("aria-expanded",String(open))});card.append(head,panel);return card}
  function empty(parent,title,detail){const box=el("div","empty");box.append(el("strong","",title),el("span","",detail));parent.append(box)}
  function filtered(){return (dataset?.proposals||[]).filter(p=>(selectedStatus==="all"||p.status===selectedStatus)&&(selectedRole==="all"||p.from_role===selectedRole||p.to_role===selectedRole))}
  function renderFilters(){filtersNode.replaceChildren();const groups=[["Status",["all","open","accepted","escalated","rejected"]],["Role",["all","uiux","frontend","backend"]]];for(let gi=0;gi<groups.length;gi++){const [label,values]=groups[gi];if(gi)filtersNode.append(el("span","filter-gap"));filtersNode.append(el("span","filter-label",label));for(const value of values){const active=(gi===0?selectedStatus:selectedRole)===value,b=el("button",`chip${active?" active":""}`,value==="all"?"All":value);b.type="button";b.addEventListener("click",()=>{if(gi===0)selectedStatus=value;else selectedRole=value;render()});filtersNode.append(b)}}}
  function render(){if(!dataset)return;const all=dataset.proposals||[],visible=filtered(),counts={open:0,accepted:0,escalated:0,rejected:0};for(const p of all)if(Object.hasOwn(counts,p.status))counts[p.status]++;document.getElementById("version").textContent=`Contract v${dataset.contract_version??0}`;countsNode.replaceChildren();for(const [key,label] of [["open","Open"],["accepted","Accepted"],["escalated","Escalated"],["rejected","Rejected"]]){const box=el("div",`stat ${key}`);box.append(el("span","",label),el("strong","",counts[key]));countsNode.append(box)}renderFilters();const escalated=visible.filter(p=>p.status==="escalated");document.getElementById("escalated-count").textContent=`${escalated.length} ${escalated.length===1?"proposal":"proposals"}`;escalatedNode.replaceChildren();if(escalated.length)for(const p of escalated)escalatedNode.append(makeProposal(p,true));else empty(escalatedNode,"Nothing needs escalation","Escalated proposals will appear here for human review.");document.getElementById("proposal-count").textContent=`${visible.length} shown`;proposalNode.replaceChildren();if(visible.length)for(const p of visible)proposalNode.append(makeProposal(p,false));else empty(proposalNode,"No proposals match","Try another status or role filter.")}
  async function refresh(){const token=tokenInput.value.trim();if(!token){statusNode.textContent="Enter your dashboard token to load the shared workspace.";return}try{sessionStorage.setItem(storageKey,token)}catch(_){}try{const response=await fetch("/api/dashboard",{headers:{"Authorization":`Bearer ${token}`}});if(!response.ok)throw new Error(response.status===401?"Access denied. Check the dashboard token.":`Could not refresh (${response.status}).`);dataset=await response.json();render();lastSuccess=Date.now();document.getElementById("updated").textContent="Updated just now";statusNode.textContent="Connected · refreshes every 5 seconds."}catch(error){statusNode.textContent=error.message}}
  document.getElementById("connect").addEventListener("click",refresh);tokenInput.addEventListener("keydown",event=>{if(event.key==="Enter")refresh()});setInterval(()=>{if(tokenInput.value.trim())refresh();if(lastSuccess)document.getElementById("updated").textContent=`Updated ${relative(new Date(lastSuccess).toISOString())}`},5000);if(tokenInput.value)refresh();
</script></body></html>"""


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)


def dashboard_payload() -> dict[str, Any]:
    """Return current contract version, proposal threads, and escalated proposals."""
    database_path = Path(messages.DB_PATH)
    if not database_path.exists():
        return {"contract_version": 0, "proposals": [], "escalated_proposals": []}

    with _readonly_connection(database_path) as connection:
        connection.row_factory = sqlite3.Row
        contract_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        proposal_rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, created_at
            FROM messages
            WHERE type = 'proposal'
            ORDER BY created_at, id
            """
        ).fetchall()
        message_rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, "read", created_at
            FROM messages
            WHERE proposal_id IS NOT NULL
            ORDER BY created_at, id
            """
        ).fetchall()

    thread_rows: dict[str, list[sqlite3.Row]] = {}
    for row in message_rows:
        thread_rows.setdefault(row["proposal_id"], []).append(row)

    proposals = []
    for proposal in proposal_rows:
        data = dict(proposal)
        data["thread"] = messages._messages_with_contract_warnings(
            thread_rows.get(proposal["id"], []), contract_version
        )
        proposals.append(data)

    return {
        "contract_version": contract_version,
        "proposals": proposals,
        "escalated_proposals": [
            proposal for proposal in proposals if proposal["status"] == "escalated"
        ],
    }


async def dashboard_page(request: Request):
    """Serve the static dashboard page."""
    return HTMLResponse(DASHBOARD_HTML)


async def dashboard_api(request: Request):
    """Serve read-only dashboard data as JSON."""
    return JSONResponse(dashboard_payload())
