"""Session-authenticated HTTP dashboard for TeamBrain."""

import base64
from contextlib import closing
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from server import messages
from server.database import create_tables
from server.members import dashboard_members, set_dashboard_member, set_profile
from server.roles import create_role, list_roles, set_role_active, validate_role


SESSION_COOKIE = "teambrain_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
_LOGIN_FAILURES: dict[str, list[float]] = {}
_LOGIN_FAILURES_LOCK = threading.Lock()


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
    h2{font-size:15px;letter-spacing:-.01em;margin:28px 0 11px}.section-note{color:var(--muted);font-weight:400;font-size:12px;margin-left:7px}.list{display:grid;gap:10px}.proposal{overflow:hidden;transition:border-color .18s,background .18s}.proposal:hover{border-color:#3a4a59;background:#141b23}.proposal.escalation{border-color:#765a31;background:linear-gradient(110deg,#211b12,var(--panel) 44%)}.proposal-head{width:100%;text-align:left;background:none;border:0;padding:15px 17px;display:block}.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.titleline{font-weight:620;min-width:0;flex:1;overflow-wrap:anywhere}.status-pill,.role,.type,.warning{display:inline-flex;align-items:center;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.045em;padding:3px 8px;text-transform:uppercase;white-space:nowrap}.status-open{background:#17283b;color:#8bbcff}.status-accepted{background:#132b24;color:#82e1bd}.status-escalated{background:#382915;color:#f0bd69}.status-rejected{background:#351d24;color:#f19aa5}.role-uiux{background:#302039;color:#d8adf2}.role-frontend{background:#16323a;color:#87d7e8}.role-backend{background:#33271a;color:#e8bd85}.role-other{background:#252d36;color:#bdc8d3}.type{background:#252d36;color:#bec9d5}.warning{background:#3b2b13;color:#f1c36f}.waiting-on{display:inline-flex;align-items:center;gap:5px;border:1px solid #385347;background:#14251e;color:#a9dfc5;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:650;white-space:nowrap}.waiting-on .role{font-size:9px;padding:2px 6px}.subline{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:11px}.subline .sep{opacity:.45}.thread{display:grid;grid-template-rows:0fr;transition:grid-template-rows .24s ease}.proposal.expanded .thread{grid-template-rows:1fr}.thread-inner{overflow:hidden;min-height:0}.timeline{margin:0 17px 16px 23px;padding:2px 0 0 17px;border-left:1px solid #35434f}.message{position:relative;padding:0 0 15px 0}.message:last-child{padding-bottom:2px}.message:before{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:#718091;left:-21px;top:6px;box-shadow:0 0 0 3px var(--panel)}.message-meta{display:flex;align-items:center;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:11px}.message-body{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0 0;color:#dce3ea;font-size:13px}.empty{border:1px dashed #34404b;border-radius:11px;padding:22px;text-align:center;color:var(--muted);background:#10151b}.empty strong{display:block;color:#c4ced8;margin-bottom:4px}.section{margin-top:4px}.hidden{display:none!important}
    .team-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:11px}.team-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px}.team-head{display:flex;align-items:center;gap:10px}.avatar{width:36px;height:36px;display:grid;place-items:center;border-radius:50%;font-size:16px;font-weight:750;flex:none}.avatar-uiux{background:#302039;color:#d8adf2}.avatar-frontend{background:#16323a;color:#87d7e8}.avatar-backend{background:#33271a;color:#e8bd85}.team-identity{min-width:0;flex:1}.team-name{font-size:14px;font-weight:700;overflow-wrap:anywhere}.team-roleline{display:flex;align-items:center;gap:7px;margin-top:4px}.presence{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:10px}.presence-dot{width:7px;height:7px;border-radius:50%;background:#697481}.presence-online{background:#63d7aa;box-shadow:0 0 8px #63d7aa77}.presence-idle{background:#e8bd63}.presence-offline{background:#697481}.team-details{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin:14px 0 0}.team-detail{min-width:0}.team-detail span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.05em}.team-detail strong{display:block;color:#d5dee6;font-size:12px;font-weight:550;margin-top:3px;overflow-wrap:anywhere}.team-actions{display:flex;justify-content:flex-end;margin-top:12px}.team-edit,.team-save{border:1px solid var(--line);background:#1b252e;border-radius:7px;padding:6px 10px;color:#d4dde5;font-size:11px}.team-form{display:grid;gap:8px;margin-top:12px}.team-form label{display:grid;gap:4px;color:var(--muted);font-size:10px}.team-form input{width:100%;background:#0c1117;border:1px solid var(--line);border-radius:6px;color:var(--text);padding:7px}.team-form-error{color:#f19aa5;font-size:11px;min-height:14px}.login{max-width:390px;margin:10vh auto 0;padding:26px;background:var(--panel);border:1px solid var(--line);border-radius:15px;box-shadow:0 24px 70px #0005}.login h2{font-size:20px;margin:0 0 5px}.login p{color:var(--muted);font-size:13px;margin:0 0 20px}.login label{display:block;color:#bdc8d3;font-size:12px;margin-bottom:7px}.login input{width:100%;background:#0c1117;border:1px solid var(--line);border-radius:8px;color:var(--text);padding:11px}.login button{width:100%;margin-top:12px;border:0;border-radius:8px;background:var(--accent);color:#092019;padding:11px;font-weight:750}.login-error{min-height:20px;margin:10px 0 0!important;color:#f19aa5!important;font-size:12px!important}
    .team-controls{display:grid;gap:9px;margin-top:12px}.team-control{display:grid;gap:5px}.team-control label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.team-input,.team-select{width:100%;min-height:36px;background:#0c1117;border:1px solid var(--line);border-radius:7px;color:var(--text);padding:8px;font:inherit;font-size:11px}.team-input{resize:vertical;min-height:52px}.team-control-row{display:flex;gap:7px;align-items:center}.team-control-row .team-input{min-width:0;flex:1}.team-button{border:1px solid var(--line);background:#1b252e;border-radius:7px;padding:7px 9px;color:#d4dde5;font-size:11px;white-space:nowrap}.team-button.primary{background:#183129;border-color:#346958;color:#a5f0d9}.team-card-note{min-height:14px;color:var(--muted);font-size:10px;overflow-wrap:anywhere}.team-section-label{font-size:10px;color:#aeb9c4;text-transform:uppercase;letter-spacing:.06em;margin-top:4px}.team-settings{border-top:1px solid var(--line);padding-top:10px}.team-coming{color:#e7ad59;font-size:10px}.team-form select{width:100%;background:#0c1117;border:1px solid var(--line);border-radius:6px;color:var(--text);padding:7px;font:inherit;font-size:11px}.handoff{border:1px solid #385347;background:#101b18;border-radius:9px;padding:10px;margin-top:12px}.handoff-head{display:flex;align-items:center;justify-content:space-between;gap:7px}.handoff-title{font-size:11px;font-weight:700}.handoff-meta{display:flex;gap:6px;flex-wrap:wrap;color:var(--muted);font-size:10px;margin-top:7px}.handoff-prompt{white-space:pre-wrap;overflow-wrap:anywhere;color:#d9e3e8;font-size:11px;margin:8px 0}.handoff-link{color:var(--accent);background:none;border:0;padding:0;text-decoration:underline;font:inherit;font-size:10px;cursor:pointer}
    @media(max-width:620px){.shell{padding:18px 14px 40px}.topbar{gap:10px}.brand{font-size:21px}.live{order:3;width:100%;margin-left:0}.logout{margin-left:auto}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.stat{padding:12px}.stat strong{font-size:22px}.proposal-head{padding:13px}.titleline{flex-basis:100%;order:2}.status-pill{order:1}.timeline{margin-left:17px}}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important}}
  </style>
</head>
<body><main class="shell">
  <header class="topbar"><h1 class="brand">TeamBrain</h1><span id="version" class="version">Contract v—</span><div class="live"><i class="dot"></i><span id="updated">Waiting for data</span></div><button id="logout" class="logout hidden" type="button">Log out</button></header>
  <section id="login" class="login"><h2>Welcome back</h2><p>Sign in to view the TeamBrain dashboard.</p><form id="login-form"><label for="password">Dashboard password</label><input id="password" type="password" autocomplete="current-password" required><button type="submit">Sign in</button><p id="login-error" class="login-error" role="status"></p></form></section>
  <section id="workspace" class="hidden"><div id="status" role="status"></div>
  <section id="stats" class="stats" aria-label="Proposal counts"></section>
  <section class="section"><h2>Team</h2><div id="team-cards" class="team-grid"></div><form id="add-role-form" class="team-form team-settings"><div class="team-section-label">Add role</div><label class="team-control"><span>Role name (lowercase letters and digits, up to 20)</span><input class="team-input" name="name" pattern="[a-z0-9]{1,20}" maxlength="20" required></label><label class="team-control"><span>Description</span><input class="team-input" name="description" maxlength="200"></label><label class="team-control"><span>Role color</span><input class="team-input" name="color" type="color" value="#8bbcff" required></label><button class="team-button primary" type="submit">Add role</button><p id="add-role-result" class="team-card-note" role="status"></p></form></section>
  <nav id="filters" class="filters" aria-label="Filter proposals"></nav>
  <section class="section"><h2>Recent messages <span id="recent-message-count" class="section-note"></span></h2><div id="recent-messages" class="list"></div></section>
  <section class="section"><h2>Needs human attention <span id="escalated-count" class="section-note"></span></h2><div id="escalated" class="list"></div></section>
  <section class="section"><h2>Proposals <span id="proposal-count" class="section-note"></span></h2><div id="proposals" class="list"></div></section></section>
</main>
<script>
  "use strict";
  const statusNode=document.getElementById("status"),loginNode=document.getElementById("login"),workspaceNode=document.getElementById("workspace");
  const countsNode=document.getElementById("stats"),teamNode=document.getElementById("team-cards"),filtersNode=document.getElementById("filters"),recentMessagesNode=document.getElementById("recent-messages"),proposalNode=document.getElementById("proposals"),escalatedNode=document.getElementById("escalated");
  let dataset=null,lastSuccess=null,authenticated=false,selectedStatus="all",selectedRole="all",teamDrafts={};
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text==null?"":String(text);return n}
  function roleInfo(role){return (dataset?.roles||[]).find(item=>item.name===role)}
  function roleTag(role){const r=String(role||"unknown").toLowerCase(),info=roleInfo(r),node=el("span",`role role-${info?r:"other"}`,role||"unknown");if(info?.color){node.style.color=info.color;node.style.border=`1px solid ${info.color}`}return node}
  function relative(value){const t=Date.parse(value||"");if(!Number.isFinite(t))return "time unknown";const sec=Math.max(0,Math.floor((Date.now()-t)/1000));if(sec<60)return "just now";if(sec<3600)return `${Math.floor(sec/60)} min ago`;if(sec<86400)return `${Math.floor(sec/3600)} hr ago`;if(sec<604800)return `${Math.floor(sec/86400)} days ago`;return new Date(t).toLocaleDateString()}
  function makeMessage(m){const item=el("article","message"),meta=el("div","message-meta");meta.append(roleTag(m.from_role),el("span","type",m.type||"message"),el("span","",relative(m.created_at)));if(m.warning)meta.append(el("span","warning","Stale context"));item.append(meta,el("p","message-body",m.body||""));return item}
  function memberPresence(lastSeen){if(!lastSeen)return "never connected";const age=Math.max(0,Date.now()-Date.parse(lastSeen));return age<120000?"online":age<600000?"idle":"offline"}
  function draftFor(role){return teamDrafts[role]||(teamDrafts[role]={})}
  function renderWaitingForYou(member,role,draft){const box=el("section","handoff"),head=el("div","handoff-head");head.append(el("span","handoff-title","Waiting for you"));const messages=member.unread_messages||[];if(!messages.length){box.append(head,el("p","team-card-note","Nothing waiting for you right now. Your inbox is clear."));return box}let index=(draft.waiting_index||0)%messages.length;const message=messages[index],count=el("span","team-card-note",`${index+1} of ${messages.length} unread`);head.append(count);box.append(head);const meta=el("div","handoff-meta");meta.append(roleTag(message.from_role),el("span","type",message.type||"message"),el("span","",relative(message.created_at)),el("span","",`Contract v${message.contract_version??0}`));if(message.proposal_id){const link=el("button","handoff-link",`Proposal ${message.proposal_id}`);link.type="button";link.addEventListener("click",()=>{const proposal=document.getElementById(`proposal-${message.proposal_id}`);if(proposal){proposal.scrollIntoView({behavior:"smooth",block:"center"});proposal.classList.add("expanded");const trigger=proposal.querySelector(".proposal-head");if(trigger)trigger.setAttribute("aria-expanded","true")}});meta.append(link)}box.append(meta);const prompt=message.handoff_prompt||`You are the ${role}. Use only the TeamBrain MCP tools. ${message.from_role} says: ${message.body}. Read thread ${message.proposal_id||"(no proposal_id)"}, do what it asks, reply with objection or accept using proposal_id, then mark_read.`;box.append(el("p","handoff-prompt",prompt));const actions=el("div","team-control-row"),copy=el("button","team-button","Copy"),note=el("span","team-card-note","");copy.type="button";copy.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(prompt);note.textContent="Prompt copied"}catch(_){note.textContent="Clipboard unavailable"}});actions.append(copy,note);if(messages.length>1){const next=el("button","team-button","Next");next.type="button";next.addEventListener("click",()=>{draft.waiting_index=(index+1)%messages.length;renderTeam()});actions.append(next)}box.append(actions);return box}
  function appendField(parent,labelText,field,value,{select=false}={}){const wrap=el("label","team-control"),label=el("span","",labelText),input=el(select?"select":"textarea",select?"team-select":"team-input");input.name=field;if(select){for(const [optionValue,optionText] of [["manual","Manual"],["headless","Headless — coming soon"]]){const option=el("option","",optionText);option.value=optionValue;input.append(option)}}else if(field!=="tool_label")input.maxLength=field==="send_task"?10000:4000;input.value=value||"";wrap.append(label,input);parent.append(wrap);return input}
  function renderTeam(){teamNode.replaceChildren();for(const member of (dataset.members||[])){const role=String(member.role||"unknown").toLowerCase(),draft=draftFor(role),card=el("article","team-card"),head=el("div","team-head"),avatar=el("div",`avatar avatar-${role}`,String(member.ai_name||role).trim().charAt(0).toUpperCase()||role.charAt(0).toUpperCase()),identity=el("div","team-identity"),presence=memberPresence(member.last_seen),presenceNode=el("span","presence"),presenceDot=el("i",`presence-dot presence-${presence.replaceAll(" ","-")}`);if(member.color){avatar.style.color=member.color;avatar.style.border=`1px solid ${member.color}`}presenceNode.append(presenceDot,el("span","",presence));identity.append(el("div","team-name",member.ai_name||`${role} AI`));const roleline=el("div","team-roleline");roleline.append(roleTag(role),presenceNode);if(!member.active)roleline.append(el("span","team-coming","Inactive"));if(member.waiting_on_open_proposal)roleline.append(el("span","waiting-on","Waiting on"));if(member.run_mode==="headless")roleline.append(el("span","team-coming","Headless · coming soon"));identity.append(roleline);head.append(avatar,identity);card.append(head);const details=el("div","team-details"),client=[member.client_name,member.client_version].filter(Boolean).join(" ")||"Not detected";for(const [label,value] of [["Description",member.description||""],["Person",member.person_name||"Not set"],["Tool label",member.tool_label||"Not set"],["Run mode",member.run_mode==="headless"?"Headless · coming soon":"Manual"],["Client app",client],["Machine",member.machine_label||"Not set"],["Last IP",member.last_ip||"Not seen"],["Last seen",member.last_seen?relative(member.last_seen):"Never"],["Last tool",member.last_tool||"Not yet used"],["Requests",member.request_count??0],["Messages sent",member.messages_sent??0],["Unread",member.unread_count??0],["Contract writing",member.can_write_contract?"Allowed":"Not allowed"],["HTTP token",member.token_configured?"Configured":"Not configured"],["Token variable",member.token_env_var]]){const detail=el("div","team-detail");detail.append(el("span","",label),el("strong","",value));details.append(detail)}card.append(details,renderWaitingForYou(member,role,draft));const controls=el("div","team-controls"),copyTask=appendField(controls,"Task to append to copied prompt","copy_task",draft.copy_task),copyRow=el("div","team-control-row"),copyButton=el("button","team-button","Copy prompt"),copyNote=el("span","team-card-note","");copyButton.type="button";copyRow.append(copyButton,copyNote);controls.append(copyRow);copyTask.addEventListener("input",()=>{draft.copy_task=copyTask.value});copyButton.addEventListener("click",async()=>{const prompt=`You are the ${role}. Use only the TeamBrain MCP tools. Call check_inbox, read each thread with get_thread, reply with objection or accept using proposal_id, do the work an accepted proposal requires, then mark_read what you handled.${copyTask.value.trim()?`\n\nTask:\n${copyTask.value.trim()}`:""}`;try{await navigator.clipboard.writeText(prompt);copyNote.textContent="Prompt copied"}catch(_){copyNote.textContent="Clipboard unavailable"}});const sendForm=el("form","team-controls"),sendTask=appendField(sendForm,"Send task","send_task",draft.send_task),sendRow=el("div","team-control-row"),sendButton=el("button","team-button primary","Send task"),sendNote=el("span","team-card-note","");sendButton.type="submit";sendRow.append(sendButton,sendNote);sendForm.append(sendRow);sendTask.addEventListener("input",()=>{draft.send_task=sendTask.value});sendForm.addEventListener("submit",async event=>{event.preventDefault();const task=sendTask.value.trim();sendNote.textContent="";if(!task){sendNote.textContent="Enter a task first.";return}try{const response=await fetch(`/api/tasks/${encodeURIComponent(role)}`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({task})});const data=await response.json();if(!response.ok)throw new Error(data.error||"Could not send task.");draft.send_task="";statusNode.textContent=`Proposal sent to ${role}.`;await refresh()}catch(problem){sendNote.textContent=problem.message||"Could not send task."}});controls.append(sendForm);const settingsToggle=el("button","team-button","Settings");settingsToggle.type="button";settingsToggle.addEventListener("click",()=>{draft.settings_open=!draft.settings_open;renderTeam()});if(draft.settings_open){const settings=el("form","team-form team-settings"),label=el("div","team-section-label","Role settings"),settingsError=el("div","team-form-error");settings.append(label);const profileValues={ai_name:draft.ai_name??member.ai_name,person_name:draft.person_name??member.person_name,machine_label:draft.machine_label??member.machine_label};for(const [field,title] of [["ai_name","AI name"],["person_name","Person name"],["machine_label","Machine label"]]){const input=appendField(settings,title,field,profileValues[field]);input.maxLength=40;input.addEventListener("input",()=>{draft[field]=input.value})}const mode=appendField(settings,"Run mode","run_mode",draft.run_mode??member.run_mode,{select:true}),tool=appendField(settings,"Tool label","tool_label",draft.tool_label??member.tool_label);mode.addEventListener("change",()=>{draft.run_mode=mode.value});tool.addEventListener("input",()=>{draft.tool_label=tool.value});settings.append(el("span","team-coming","Headless mode is coming soon; no headless runner is enabled."));const save=el("button","team-button primary","Save settings");save.type="submit";settings.append(save,settingsError);settings.addEventListener("submit",async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(settings).entries());try{const response=await fetch(`/api/members/${encodeURIComponent(role)}`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)});const data=await response.json();if(!response.ok)throw new Error(data.error||"Could not save settings.");delete teamDrafts[role];await refresh()}catch(problem){settingsError.textContent=problem.message||"Could not save settings."}});controls.append(settings)}const settingsRow=el("div","team-control-row"),activate=el("button","team-button",member.active?"Deactivate role":"Activate role"),roleNote=el("span","team-card-note",member.token_configured?"HTTP token configured.":`Set ${member.token_env_var} in the server environment to enable HTTP access.`);activate.type="button";activate.addEventListener("click",async()=>{try{const response=await fetch(`/api/roles/${encodeURIComponent(role)}/active`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({active:!member.active})});const result=await response.json();if(!response.ok)throw new Error(result.error||"Could not update role.");await refresh()}catch(problem){roleNote.textContent=problem.message||"Could not update role."}});settingsRow.append(settingsToggle,activate);controls.append(settingsRow,roleNote);card.append(controls);teamNode.append(card)}}
  function renderRecentMessages(){const recent=dataset.recent_messages||[];document.getElementById("recent-message-count").textContent=`${recent.length} total`;recentMessagesNode.replaceChildren();if(!recent.length){empty(recentMessagesNode,"No messages yet","Messages sent by the team will appear here.");return}for(const message of recent){const card=el("article","proposal recent-message"),meta=el("div","message-meta");meta.append(roleTag(message.from_role),el("span","sep","→"),roleTag(message.to_role),el("span","type",message.type||"message"),el("span","",relative(message.created_at)),el("span","",`Contract v${message.contract_version}`));card.append(meta,el("p","message-body",message.body||""));recentMessagesNode.append(card)}}
  function makeProposal(p,highlight){const card=el("article",`proposal${highlight?" escalation":""}`),head=el("button","proposal-head");card.id=`proposal-${p.id}`;head.type="button";head.setAttribute("aria-expanded","false");const row=el("div","row");row.append(el("span",`status-pill status-${p.status||"open"}`,p.status||"unknown"),el("span","titleline",p.body||p.id));const sub=el("div","subline");sub.append(roleTag(p.from_role),el("span","sep","→"),roleTag(p.to_role),el("span","sep","·"),el("span","",relative(p.created_at)));if(p.thread&&p.thread.some(m=>m.warning))sub.append(el("span","warning","Stale context"));if(p.status==="open"){const waitingRoles=[...new Set((p.thread||[]).filter(m=>m.read===0||m.read===false||m.read==="0").map(m=>m.to_role).filter(Boolean))];if(waitingRoles.length){const badge=el("span","waiting-on");badge.append(el("span","","Waiting on"));for(const role of waitingRoles)badge.append(roleTag(role));sub.append(badge)}}head.append(row,sub);const panel=el("div","thread"),inner=el("div","thread-inner"),timeline=el("div","timeline");for(const m of (p.thread||[]))timeline.append(makeMessage(m));if(!(p.thread||[]).length)timeline.append(el("p","empty","No messages in this thread yet."));inner.append(timeline);panel.append(inner);head.addEventListener("click",()=>{const open=card.classList.toggle("expanded");head.setAttribute("aria-expanded",String(open))});card.append(head,panel);return card}
  function empty(parent,title,detail){const box=el("div","empty");box.append(el("strong","",title),el("span","",detail));parent.append(box)}
  function filtered(){return (dataset?.proposals||[]).filter(p=>(selectedStatus==="all"||p.status===selectedStatus)&&(selectedRole==="all"||p.from_role===selectedRole||p.to_role===selectedRole))}
  function renderFilters(){filtersNode.replaceChildren();const roleValues=["all",...(dataset?.roles||[]).map(role=>role.name)],groups=[["Status",["all","open","accepted","escalated","rejected"]],["Role",roleValues]];for(let gi=0;gi<groups.length;gi++){const [label,values]=groups[gi];if(gi)filtersNode.append(el("span","filter-gap"));filtersNode.append(el("span","filter-label",label));for(const value of values){const active=(gi===0?selectedStatus:selectedRole)===value,b=el("button",`chip${active?" active":""}`,value==="all"?"All":value),info=roleInfo(value);if(info?.color){b.style.borderColor=info.color;b.style.color=info.color}b.type="button";b.addEventListener("click",()=>{if(gi===0)selectedStatus=value;else selectedRole=value;render()});filtersNode.append(b)}}}
  function render(){if(!dataset)return;const all=dataset.proposals||[],visible=filtered(),counts={open:0,accepted:0,escalated:0,rejected:0};for(const p of all)if(Object.hasOwn(counts,p.status))counts[p.status]++;document.getElementById("version").textContent=`Contract v${dataset.contract_version??0}`;countsNode.replaceChildren();for(const [key,label] of [["open","Open"],["accepted","Accepted"],["escalated","Escalated"],["rejected","Rejected"]]){const box=el("div",`stat ${key}`);box.append(el("span","",label),el("strong","",counts[key]));countsNode.append(box)}renderTeam();renderFilters();renderRecentMessages();const escalated=visible.filter(p=>p.status==="escalated");document.getElementById("escalated-count").textContent=`${escalated.length} ${escalated.length===1?"proposal":"proposals"}`;escalatedNode.replaceChildren();if(escalated.length)for(const p of escalated)escalatedNode.append(makeProposal(p,true));else empty(escalatedNode,"Nothing needs escalation","Escalated proposals will appear here for human review.");document.getElementById("proposal-count").textContent=`${visible.length} shown`;proposalNode.replaceChildren();if(visible.length)for(const p of visible)proposalNode.append(makeProposal(p,false));else empty(proposalNode,"No proposals match","Try another status or role filter.")}
  function showLogin(message=""){authenticated=false;workspaceNode.classList.add("hidden");document.getElementById("logout").classList.add("hidden");loginNode.classList.remove("hidden");document.getElementById("login-error").textContent=message}
  function showWorkspace(){authenticated=true;loginNode.classList.add("hidden");workspaceNode.classList.remove("hidden");document.getElementById("logout").classList.remove("hidden")}
  async function refresh(){try{const response=await fetch("/api/dashboard",{credentials:"same-origin"});if(response.status===401){showLogin();return}if(!response.ok)throw new Error("Could not refresh the dashboard.");dataset=await response.json();showWorkspace();render();lastSuccess=Date.now();document.getElementById("updated").textContent="Updated just now";statusNode.textContent="Connected · refreshes every 3 seconds."}catch(_){statusNode.textContent="Could not refresh the dashboard."}}
  document.getElementById("login-form").addEventListener("submit",async event=>{event.preventDefault();const password=document.getElementById("password"),error=document.getElementById("login-error");error.textContent="";try{const response=await fetch("/api/login",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:password.value})});if(response.ok){password.value="";await refresh()}else if(response.status===429)error.textContent="Too many attempts. Please wait a minute and try again.";else error.textContent="Wrong password. Please try again."}catch(_){error.textContent="Wrong password. Please try again."}});
  document.getElementById("add-role-form").addEventListener("submit",async event=>{event.preventDefault();const form=event.currentTarget,result=document.getElementById("add-role-result"),values=Object.fromEntries(new FormData(form).entries());result.textContent="";try{const response=await fetch("/api/roles",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}),data=await response.json();if(!response.ok)throw new Error(data.error||"Could not add role.");result.textContent=`Role ${data.name} added. Set ${data.token_env_var} in the server environment after generating a token manually, then restart TeamBrain HTTP. The server never generates or stores tokens.`;form.reset();form.querySelector('[name="color"]').value="#8bbcff";await refresh()}catch(problem){result.textContent=problem.message||"Could not add role."}});
  document.getElementById("add-role-form").addEventListener("submit",async event=>{event.preventDefault();const form=event.currentTarget,result=document.getElementById("add-role-result"),values=Object.fromEntries(new FormData(form).entries());result.textContent="";try{const response=await fetch("/api/roles",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}),data=await response.json();if(!response.ok)throw new Error(data.error||"Could not add role.");result.textContent=`Role ${data.name} added. Set ${data.token_env_var} in the server environment after generating a token manually. The server never generates or stores tokens.`;form.reset();form.querySelector('[name="color"]').value="#8bbcff";await refresh()}catch(problem){result.textContent=problem.message||"Could not add role."}});
  document.getElementById("logout").addEventListener("click",async()=>{try{await fetch("/api/logout",{method:"POST",credentials:"same-origin"})}finally{dataset=null;showLogin();document.getElementById("password").value=""}});
  setInterval(()=>{if(authenticated)refresh();if(lastSuccess)document.getElementById("updated").textContent=`Updated ${relative(new Date(lastSuccess).toISOString())}`},3000);refresh();
</script></body></html>"""


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)


def dashboard_payload() -> dict[str, Any]:
    """Return current contract version, proposal threads, and escalated proposals."""
    database_path = Path(messages.DB_PATH)
    if not database_path.exists():
        with sqlite3.connect(":memory:") as connection:
            create_tables(connection)
            return {
                "contract_version": 0,
                "roles": list_roles(connection),
                "proposals": [],
                "escalated_proposals": [],
                "recent_messages": [],
                "members": dashboard_members(connection),
            }

    # Apply additive schema migrations before opening the dashboard's read-only view.
    with sqlite3.connect(database_path) as connection:
        create_tables(connection)

    with closing(_readonly_connection(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        contract_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM contracts"
        ).fetchone()[0]
        proposal_rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, handoff_prompt, created_at
            FROM messages
            WHERE type = 'proposal'
            ORDER BY created_at, id
            """
        ).fetchall()
        message_rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   proposal_id, status, decision_note, handoff_prompt, "read", created_at
            FROM messages
            WHERE proposal_id IS NOT NULL
            ORDER BY created_at, id
            """
        ).fetchall()
        recent_message_rows = connection.execute(
            """
            SELECT id, from_role, to_role, type, body, contract_version,
                   handoff_prompt, created_at
            FROM messages
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        member_rows = dashboard_members(connection)
        role_rows = list_roles(connection)

    for role in role_rows:
        role["token_configured"] = bool(os.environ.get(role["token_env_var"]))
    for member in member_rows:
        member["token_configured"] = bool(os.environ.get(member["token_env_var"]))

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
        "roles": role_rows,
        "proposals": proposals,
        "escalated_proposals": [
            proposal for proposal in proposals if proposal["status"] == "escalated"
        ],
        "recent_messages": [dict(row) for row in recent_message_rows],
        "members": member_rows,
    }


async def dashboard_page(request: Request):
    """Serve the dashboard shell; client data access is session authenticated."""
    return HTMLResponse(DASHBOARD_HTML)


def _session_signature(expires: str) -> str | None:
    secret = os.environ.get("TEAMBRAIN_SESSION_SECRET")
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), expires.encode("ascii"), hashlib.sha256).hexdigest()


def _valid_session(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    expires, dot, signature = cookie.partition(".")
    if not dot or not expires.isascii() or not expires.isdigit():
        return False
    expected = _session_signature(expires)
    if expected is None or not hmac.compare_digest(signature, expected):
        return False
    return int(expires) > int(time.time())


def _valid_origin(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    expected = f"{request.url.scheme}://{request.url.netloc}"
    return bool(parsed.scheme and parsed.netloc and not parsed.path and origin == expected)


def _login_limited(ip: str, *, failed: bool = False) -> bool:
    now = time.monotonic()
    with _LOGIN_FAILURES_LOCK:
        attempts = [stamp for stamp in _LOGIN_FAILURES.get(ip, []) if now - stamp < 60]
        if failed:
            attempts.append(now)
        _LOGIN_FAILURES[ip] = attempts
        return len(attempts) >= 5 and not failed


async def dashboard_login(request: Request):
    """Validate the dashboard password and issue a signed session cookie."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    ip = request.client.host if request.client else "unknown"
    if _login_limited(ip):
        return JSONResponse({"error": "Too many attempts."}, status_code=429)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = {}
    supplied = payload.get("password", "") if isinstance(payload, dict) else ""
    if not isinstance(supplied, str):
        supplied = ""
    expected_password = os.environ.get("TEAMBRAIN_DASHBOARD_TOKEN", "")
    password_matches = hmac.compare_digest(
        supplied.encode("utf-8"), expected_password.encode("utf-8")
    )
    if not expected_password or not password_matches:
        _login_limited(ip, failed=True)
        return JSONResponse({"error": "Wrong password."}, status_code=401)
    expires = str(int(time.time()) + SESSION_SECONDS)
    signature = _session_signature(expires)
    if signature is None:
        return JSONResponse({"error": "Sign-in unavailable."}, status_code=503)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        f"{expires}.{signature}",
        max_age=SESSION_SECONDS,
        expires=datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    with _LOGIN_FAILURES_LOCK:
        _LOGIN_FAILURES.pop(ip, None)
    return response


async def dashboard_logout(request: Request):
    """Clear the dashboard session cookie after a same-origin POST."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


async def dashboard_api(request: Request):
    """Serve read-only dashboard data as JSON."""
    if not _valid_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(dashboard_payload())


async def dashboard_update_member(request: Request):
    """Update a team profile from the dashboard owner's same-origin session."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    if not _valid_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid profile."}, status_code=400)
    role = request.path_params.get("role", "")
    try:
        profile_values = (
            role,
            payload.get("ai_name"),
            payload.get("person_name"),
            payload.get("machine_label"),
        )
        profile = None
        settings = None
        if "run_mode" in payload or "tool_label" in payload:
            if "run_mode" not in payload or "tool_label" not in payload:
                return JSONResponse({"error": "run_mode and tool_label must be submitted together."}, status_code=400)
            profile = set_dashboard_member(*profile_values, payload["run_mode"], payload["tool_label"])
        else:
            profile = set_profile(*profile_values)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse(profile)


async def dashboard_send_task(request: Request):
    """Create an owner-authored proposal in the selected role's inbox."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    if not _valid_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    task = payload.get("task") if isinstance(payload, dict) else None
    if not isinstance(task, str) or not task.strip():
        return JSONResponse({"error": "Task must be non-empty text."}, status_code=400)
    if len(task) > 10000:
        return JSONResponse({"error": "Task must be at most 10000 characters."}, status_code=400)
    role = request.path_params.get("role", "")
    try:
        with sqlite3.connect(messages.DB_PATH) as connection:
            create_tables(connection)
            validate_role(connection, role)
    except ValueError:
        return JSONResponse({"error": "Unknown or inactive role."}, status_code=404)
    contract = messages.read_contract()
    result = messages.post_message(
        from_role="owner",
        to_role=role,
        type="proposal",
        body=task.strip(),
        contract_version=contract["version"] if contract else 0,
        allow_owner=True,
    )
    return JSONResponse(result, status_code=201)


async def dashboard_create_role(request: Request):
    """Add a role from the owner-only dashboard session."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    if not _valid_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid role."}, status_code=400)
    try:
        created = create_role(
            payload.get("name"),
            payload.get("description", ""),
            payload.get("color"),
            active=payload.get("active", True),
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse(created, status_code=201)


async def dashboard_set_role_active(request: Request):
    """Enable or disable a role from the owner-only dashboard session."""
    if not _valid_origin(request):
        return JSONResponse({"error": "Request rejected."}, status_code=403)
    if not _valid_session(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("active"), bool):
        return JSONResponse({"error": "active must be a boolean."}, status_code=400)
    try:
        updated = set_role_active(request.path_params.get("role", ""), payload["active"])
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=404)
    return JSONResponse(updated)
