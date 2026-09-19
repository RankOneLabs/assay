"""Render a blind label packet as one self-contained HTML file.

The hosted packet page in ``scout/comms/label-packets-spec.md`` is the eventual
home for this. That page is unbuilt, and standing it up is disproportionate for
one 30-case packet, so this renders a single file the reviewer opens locally
from the private receipts directory.

By default the page holds no network code. It keeps a draft in ``localStorage``
against the packet digest and writes labels out as a download, so a dropped tab
costs nothing and nothing leaves the machine.

``post_back`` relaxes that for the served variant in ``serve_packet.py``, where
the reviewer labels on a phone and the download would land on the wrong device.
It is a separate delivery fragment rather than a branch on a null constant, so
"this file cannot phone home" stays a property you can grep for rather than one
you have to reason about.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Endpoints:
    """Where a served page submits labels and syncs its draft.

    One type rather than two arguments: a page with a submit URL but no draft
    URL is not a state worth being able to express.
    """

    labels: str
    draft: str

_STYLE = """
:root { color-scheme: light dark; }
body {
  font: 15px/1.6 system-ui, sans-serif; max-width: 52rem;
  margin: 0 auto; padding: 2rem 1.25rem 6rem;
}
h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 1.5rem; }
.rubric {
  background: rgba(127,127,127,.09); border-radius: 8px;
  padding: 1rem 1.25rem; margin-bottom: 2rem;
}
.rubric ol, .rubric ul { padding-left: 1.2rem; }
.rubric .lvl { margin: .45rem 0; }
.rubric .lvl b { font-variant: small-caps; letter-spacing: .03em; }
details summary { cursor: pointer; font-weight: 600; margin: .5rem 0; }
.case {
  border: 1px solid rgba(127,127,127,.35); border-radius: 8px;
  padding: 1rem 1.25rem; margin: 1.25rem 0;
}
.case.done { border-color: rgba(60,160,90,.75); }
.case h3 { margin: 0 0 .6rem; font-size: .95rem; opacity: .7; }
.text {
  white-space: pre-wrap; word-wrap: break-word;
  background: rgba(127,127,127,.07); padding: .75rem; border-radius: 6px;
}
.parent {
  border-left: 3px solid rgba(127,127,127,.4); padding-left: .75rem;
  margin-bottom: .75rem; opacity: .8; font-size: .92rem; white-space: pre-wrap;
}
.parent em { opacity: .65; font-size: .85rem; }
fieldset { border: 0; padding: .5rem 0 0; margin: .75rem 0 0; }
fieldset legend { font-weight: 600; font-size: .9rem; padding: 0; }
fieldset.disp {
  border-top: 1px dashed rgba(127,127,127,.4); margin-top: 1rem; padding-top: .75rem;
}
label.opt { display: block; padding: .2rem 0; cursor: pointer; }
label.opt span.n { font-weight: 600; }
label.opt span.d { opacity: .72; }
textarea {
  width: 100%; margin-top: .5rem; font: inherit; padding: .4rem;
  border-radius: 6px; border: 1px solid rgba(127,127,127,.4);
  background: transparent; color: inherit;
}
#bar {
  position: fixed; left: 0; right: 0; bottom: 0; padding: .7rem 1.25rem;
  background: Canvas; border-top: 1px solid rgba(127,127,127,.35);
  display: flex; gap: 1rem; align-items: center;
}
button {
  font: inherit; padding: .45rem 1rem; border-radius: 6px;
  border: 1px solid rgba(127,127,127,.5); background: transparent;
  color: inherit; cursor: pointer;
}
button:disabled { opacity: .45; cursor: default; }
code { background: rgba(127,127,127,.15); padding: .1em .35em; border-radius: 3px; }
"""

_SCRIPT = """
const KEY = 'label-packet:' + PACKET.digest;
const STAMP = KEY + ':saved_at';
const answers = JSON.parse(localStorage.getItem(KEY) || '{}');

function caseState(id) { return answers[id] || (answers[id] = {}); }

/* Only a real edit advances the clock. Merely opening the page must not make
   this device look newer than one that has genuinely moved further on. */
function touch() { localStorage.setItem(STAMP, new Date().toISOString()); }

function answered(a) {
  return a && a.band !== undefined && a.exclusion !== undefined && a.disposition !== undefined;
}

function refresh() {
  let done = 0;
  for (const c of PACKET.cases) {
    const complete = answered(answers[c.case_id]);
    if (complete) done++;
    document.getElementById('case-' + c.case_id).classList.toggle('done', complete);
  }
  document.getElementById('count').textContent = done + ' / ' + PACKET.cases.length + ' answered';
  document.getElementById('save').disabled = done !== PACKET.cases.length;
  localStorage.setItem(KEY, JSON.stringify(answers));
  syncDraft(done);
}

document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.name) return;
  const [kind, id] = el.name.split(':');
  if (kind === 'band') caseState(id).band = parseInt(el.value, 10);
  else if (kind === 'exclusion') caseState(id).exclusion = el.value;
  else if (kind === 'disposition') caseState(id).disposition = el.value;
  touch();
  refresh();
});

document.addEventListener('input', (e) => {
  if (e.target.tagName !== 'TEXTAREA') return;
  const id = e.target.name.split(':')[1];
  const note = e.target.value.trim();
  if (note) caseState(id).note = note; else delete caseState(id).note;
  touch();
  refresh();
});

function collect() {
  return {
    format: 'assay.label-packet-labels/v1',
    packet: PACKET.name,
    packet_digest: PACKET.digest,
    plan_digest: PACKET.plan_digest,
    reviewer: document.getElementById('reviewer').value || 'unknown',
    saved_at: new Date().toISOString(),
    cases: PACKET.cases.map(c => ({
      case_id: c.case_id,
      band: answers[c.case_id].band,
      exclusion: answers[c.case_id].exclusion,
      disposition: answers[c.case_id].disposition,
      note: answers[c.case_id].note || null,
    })),
  };
}

function download(payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2) + '\\n'], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels.json';
  a.click();
}

function status(message) { document.getElementById('status').textContent = message; }

document.getElementById('save').addEventListener('click', () => deliver(collect()));

function restore() {
  for (const [id, a] of Object.entries(answers)) {
    if (a.band !== undefined) {
      const el = document.querySelector(`input[name="band:${id}"][value="${a.band}"]`);
      if (el) el.checked = true;
    }
    if (a.exclusion !== undefined) {
      const el = document.querySelector(`input[name="exclusion:${id}"][value="${a.exclusion}"]`);
      if (el) el.checked = true;
    }
    if (a.disposition !== undefined) {
      const el = document.querySelector(
        `input[name="disposition:${id}"][value="${a.disposition}"]`);
      if (el) el.checked = true;
    }
    if (a.note) {
      const el = document.querySelector(`textarea[name="note:${id}"]`);
      if (el) el.value = a.note;
    }
  }
}

hydrate();
"""

#: The default delivery: a download, and no network call anywhere on the page.
#: ``syncDraft`` and ``hydrate`` are the same seams the served variant fills, so
#: the shared script can call them unconditionally.
_DELIVER_DOWNLOAD = """
function deliver(payload) { download(payload); }
function syncDraft(done) {}
function hydrate() { restore(); refresh(); }
"""

#: The served delivery. The payload carries case ids and three choices per case —
#: never post text — so this crosses the tailnet with nothing sensitive in it.
#: A refusal or an unreachable server falls back to the download rather than
#: losing the sitting; the localStorage draft survives either way.
_DELIVER_POST = """
async function deliver(payload) {
  status('sending…');
  try {
    const response = await fetch(POST_BACK, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const body = (await response.text()).trim();
    if (response.ok) { status(body); return; }
    status('refused: ' + body + ' — downloading instead');
  } catch (error) {
    status('server unreachable (' + error.message + ') — downloading instead');
  }
  download(payload);
}

/* Draft sync. The draft is scratch and may be partial; `/labels` stays the
   complete, validated artifact. Uploads are debounced so a burst of clicks is
   one request, and a failed upload is survivable — the localStorage copy is
   still authoritative for this device. */
let pending = null;

function syncDraft(done) {
  if (pending) clearTimeout(pending);
  pending = setTimeout(async () => {
    pending = null;
    try {
      const response = await fetch(DRAFT_BACK, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({
          format: 'assay.label-packet-draft/v1',
          packet: PACKET.name,
          packet_digest: PACKET.digest,
          plan_digest: PACKET.plan_digest,
          reviewer: document.getElementById('reviewer').value || 'unknown',
          saved_at: localStorage.getItem(STAMP) || new Date().toISOString(),
          answers: answers,
        }),
      });
      status(response.ok ? 'synced ' + done + ' / ' + PACKET.cases.length
                         : 'sync refused: ' + (await response.text()).trim());
    } catch (error) {
      status('offline — saved on this device only');
    }
  }, 1200);
}

/* Union on load, newest-wins on a genuine conflict. A case answered on one
   device and untouched on another is never lost; a case answered differently on
   both takes the later edit. */
function hydrate() {
  fetch(DRAFT_BACK, {cache: 'no-store'})
    .then(response => response.ok ? response.json() : null)
    .then(remote => {
      if (!remote || remote.packet_digest !== PACKET.digest) return;
      const theirs = remote.saved_at || '';
      const mine = localStorage.getItem(STAMP) || '';
      for (const [id, entry] of Object.entries(remote.answers || {})) {
        if (!answers[id] || Object.keys(answers[id]).length === 0 || theirs > mine) {
          answers[id] = entry;
        }
      }
      if (theirs > mine) localStorage.setItem(STAMP, theirs);
    })
    .catch(() => {})
    .finally(() => { restore(); refresh(); });
}
"""


def _rubric_html(rubric: Mapping[str, Any]) -> str:
    band, exclusion = rubric["band"], rubric["exclusion"]
    order = "".join(f"<li>{html.escape(step)}</li>" for step in band["apply_in_order"])
    levels = "".join(
        f'<div class="lvl"><b>{html.escape(level["name"])}</b> — '
        f'{html.escape(level["summary"])}</div>'
        for level in band["levels"]
    )
    options = "".join(
        f"<li><b>{html.escape(option['name'])}</b> — {html.escape(option['what'])}"
        + (
            f"<br><em>Not for:</em> {html.escape(option['not_for'])}"
            if option.get("not_for")
            else ""
        )
        + "</li>"
        for option in exclusion["options"]
    )
    disposition = rubric["disposition"]
    dispositions = "".join(
        f"<li><b>{html.escape(option['name'])}</b> — {html.escape(option['what'])}</li>"
        for option in disposition["options"]
    )
    return f"""
<div class="rubric">
  <h2>{html.escape(band["question"])}</h2>
  <ol>{order}</ol>
  <p><strong>Note.</strong> {html.escape(band["note"])}</p>
  {levels}
  <details>
    <summary>Hard exclusions — {html.escape(exclusion["question"])}</summary>
    <p>{html.escape(exclusion["judge"])}</p>
    <ul>{options}</ul>
  </details>
  <details open>
    <summary>{html.escape(disposition["question"])}</summary>
    <p>{html.escape(disposition["judge"])}</p>
    <ul>{dispositions}</ul>
  </details>
</div>"""


def _case_html(case: Mapping[str, Any], rubric: Mapping[str, Any]) -> str:
    case_id = case["case_id"]
    parent = case.get("parent_text")
    parent_block = (
        f'<div class="parent"><em>in reply to</em><br>{html.escape(str(parent))}</div>'
        if parent
        else ""
    )
    bands = "".join(
        f'<label class="opt"><input type="radio" name="band:{case_id}" value="{level["index"]}"> '
        f'<span class="n">{html.escape(level["name"])}</span> '
        f'<span class="d">— {html.escape(level["summary"])}</span></label>'
        for level in rubric["band"]["levels"]
    )
    exclusions = "".join(
        f'<label class="opt"><input type="radio" name="exclusion:{case_id}" '
        f'value="{html.escape(option["name"])}"> '
        f'<span class="n">{html.escape(option["name"])}</span> '
        f'<span class="d">— {html.escape(option["what"])}</span></label>'
        for option in rubric["exclusion"]["options"]
    )
    dispositions = "".join(
        f'<label class="opt"><input type="radio" name="disposition:{case_id}" '
        f'value="{html.escape(option["name"])}"> '
        f'<span class="n">{html.escape(option["name"])}</span> '
        f'<span class="d">— {html.escape(option["what"])}</span></label>'
        for option in rubric["disposition"]["options"]
    )
    return f"""
<div class="case" id="case-{case_id}">
  <h3>Case {case_id}</h3>
  {parent_block}
  <div class="text">{html.escape(case["text"])}</div>
  <fieldset><legend>Hard exclusion?</legend>{exclusions}</fieldset>
  <fieldset><legend>Which situation best describes this post?</legend>{bands}</fieldset>
  <fieldset class="disp">
    <legend>{html.escape(rubric["disposition"]["question"])}</legend>
    {dispositions}
  </fieldset>
  <textarea name="note:{case_id}" rows="2" placeholder="Note (optional)"></textarea>
</div>"""


def render_packet_html(
    name: str,
    digest: str,
    plan_digest: str,
    cases: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
    *,
    endpoints: Endpoints | None = None,
) -> str:
    """One self-contained blind packet page.

    ``endpoints`` makes the page submit to a server and sync its draft. Left
    unset, the page downloads and makes no network call of any kind.
    """
    payload = {
        "name": name,
        "digest": digest,
        "plan_digest": plan_digest,
        "cases": [{"case_id": case["case_id"]} for case in cases],
    }
    body = "".join(_case_html(case, rubric) for case in cases)
    constants = f"const PACKET = {json.dumps(payload)};"
    if endpoints is None:
        deliver, action = _DELIVER_DOWNLOAD, "Download labels.json"
    else:
        constants += (
            f"const POST_BACK = {json.dumps(endpoints.labels)};"
            f"const DRAFT_BACK = {json.dumps(endpoints.draft)};"
        )
        deliver, action = _DELIVER_POST, "Submit labels"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(name)}</title><style>{_STYLE}</style></head>
<body>
<h1>{html.escape(name)}</h1>
<p>Blind packet. You are seeing each post's own text and its parent, and nothing else
— no author, no prior label, no model decision. Answer the three questions from the
wording below; it is the catalogue's own text, unedited. Progress saves as you go.</p>
{_rubric_html(rubric)}
{body}
<div id="bar">
  <label>Reviewer <input id="reviewer" value="steve"></label>
  <span id="count"></span>
  <button id="save" disabled>{html.escape(action)}</button>
  <span id="status"></span>
</div>
<script>{constants}{_SCRIPT}{deliver}</script>
</body></html>
"""
