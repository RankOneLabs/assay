"""Render a blind label packet as one self-contained HTML file.

The hosted packet page in ``scout/comms/label-packets-spec.md`` is the eventual
home for this. That page is unbuilt, and standing it up is disproportionate for
one 30-case packet, so this renders a single file the reviewer opens locally
from the private receipts directory.

The page holds no network code. It keeps a draft in ``localStorage`` against the
packet digest and writes labels out as a download, so a dropped tab costs
nothing and nothing leaves the machine.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

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
const answers = JSON.parse(localStorage.getItem(KEY) || '{}');

function caseState(id) { return answers[id] || (answers[id] = {}); }

function refresh() {
  let done = 0;
  for (const c of PACKET.cases) {
    const a = answers[c.case_id] || {};
    const complete = a.band !== undefined && a.exclusion !== undefined;
    if (complete) done++;
    document.getElementById('case-' + c.case_id).classList.toggle('done', complete);
  }
  document.getElementById('count').textContent = done + ' / ' + PACKET.cases.length + ' answered';
  document.getElementById('save').disabled = done !== PACKET.cases.length;
  localStorage.setItem(KEY, JSON.stringify(answers));
}

document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.name) return;
  const [kind, id] = el.name.split(':');
  if (kind === 'band') caseState(id).band = parseInt(el.value, 10);
  else if (kind === 'exclusion') caseState(id).exclusion = el.value;
  refresh();
});

document.addEventListener('input', (e) => {
  if (e.target.tagName !== 'TEXTAREA') return;
  const id = e.target.name.split(':')[1];
  const note = e.target.value.trim();
  if (note) caseState(id).note = note; else delete caseState(id).note;
  localStorage.setItem(KEY, JSON.stringify(answers));
});

document.getElementById('save').addEventListener('click', () => {
  const payload = {
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
      note: answers[c.case_id].note || null,
    })),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2) + '\\n'], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels.json';
  a.click();
});

for (const [id, a] of Object.entries(answers)) {
  if (a.band !== undefined) {
    const el = document.querySelector(`input[name="band:${id}"][value="${a.band}"]`);
    if (el) el.checked = true;
  }
  if (a.exclusion !== undefined) {
    const el = document.querySelector(`input[name="exclusion:${id}"][value="${a.exclusion}"]`);
    if (el) el.checked = true;
  }
  if (a.note) {
    const el = document.querySelector(`textarea[name="note:${id}"]`);
    if (el) el.value = a.note;
  }
}
refresh();
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
    return f"""
<div class="case" id="case-{case_id}">
  <h3>Case {case_id}</h3>
  {parent_block}
  <div class="text">{html.escape(case["text"])}</div>
  <fieldset><legend>Hard exclusion?</legend>{exclusions}</fieldset>
  <fieldset><legend>Which situation best describes this post?</legend>{bands}</fieldset>
  <textarea name="note:{case_id}" rows="2" placeholder="Note (optional)"></textarea>
</div>"""


def render_packet_html(
    name: str,
    digest: str,
    plan_digest: str,
    cases: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
) -> str:
    """One self-contained blind packet page."""
    payload = {
        "name": name,
        "digest": digest,
        "plan_digest": plan_digest,
        "cases": [{"case_id": case["case_id"]} for case in cases],
    }
    body = "".join(_case_html(case, rubric) for case in cases)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(name)}</title><style>{_STYLE}</style></head>
<body>
<h1>{html.escape(name)}</h1>
<p>Blind packet. You are seeing each post's own text and its parent, and nothing else
— no author, no prior label, no model decision. Answer both questions from the wording
below; it is the catalogue's own text, unedited. Progress saves as you go.</p>
{_rubric_html(rubric)}
{body}
<div id="bar">
  <label>Reviewer <input id="reviewer" value="steve"></label>
  <span id="count"></span>
  <button id="save" disabled>Download labels.json</button>
</div>
<script>const PACKET = {json.dumps(payload)};{_SCRIPT}</script>
</body></html>
"""
