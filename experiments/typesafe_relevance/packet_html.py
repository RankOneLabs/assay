"""Render a blind label packet as one self-contained HTML file.

The hosted packet page in the Scout label-packets specification is the eventual
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


@dataclass(frozen=True, slots=True)
class Formats:
    """What the page stamps on what it sends back.

    The version tracks the question set, not the page. ``/v1`` carries `band`;
    ``/v2`` carries `substance` instead. A reader must be able to tell which
    questions a label file answers without inspecting its rows.
    """

    labels: str
    draft: str


#: The band-era question set: `exclusion`, `band`, `disposition`.
FORMATS_V1 = Formats(labels="assay.label-packet-labels/v1", draft="assay.label-packet-draft/v1")

#: The substance rule: `exclusion`, then `substance` when nothing was excluded.
FORMATS_V2 = Formats(labels="assay.label-packet-labels/v2", draft="assay.label-packet-draft/v2")

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
/* A question whose `asked_when` is unmet. Rendered so the page stays static
   HTML, hidden so it is not answered; its stored answer is pruned separately. */
fieldset.hidden { display: none; }
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

/* Whether a question applies given the answers so far. Mirrors `is_asked` in
   packet.py and `_is_asked` in serve_packet.py — all three read the same
   `asked_when` off the packet rather than knowing which question gates which. */
function isAsked(q, a) {
  if (!q.asked_when) return true;
  return a && a[q.asked_when.question] === q.asked_when.equals;
}

/* Every question the packet *asks* has to be answered. A question whose
   condition is unmet is not asked, so it does not hold the case open. Driven by
   PACKET.questions rather than a hardcoded list, so changing the rubric is a
   change to the catalogue and not to this file. */
function answered(a) {
  return !!a && PACKET.questions.every(q => !isAsked(q, a) || a[q.key] !== undefined);
}

/* An answer that is no longer asked is deleted, not left in place. Otherwise
   picking `hype` after having answered `substance` leaves a stale value in the
   record, the server rejects the submit, and it does so at the end of a sitting
   rather than at the click that caused it. */
function prune(id, a) {
  for (const q of PACKET.questions) {
    if (isAsked(q, a) || a[q.key] === undefined) continue;
    delete a[q.key];
    const el = document.querySelector(`input[name="${q.key}:${id}"]:checked`);
    if (el) el.checked = false;
  }
}

function coerce(question, raw) {
  if (question.value_type === 'int') return parseInt(raw, 10);
  if (question.value_type === 'bool') return raw === 'true';
  return raw;
}

function refresh() {
  let done = 0;
  for (const c of PACKET.cases) {
    const a = answers[c.case_id];
    if (a) prune(c.case_id, a);
    for (const q of PACKET.questions) {
      const fs = document.getElementById(`q-${q.key}-${c.case_id}`);
      if (fs) fs.classList.toggle('hidden', !isAsked(q, a));
    }
    const complete = answered(a);
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
  const question = PACKET.questions.find(q => q.key === kind);
  if (!question) return;
  caseState(id)[kind] = coerce(question, el.value);
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
    format: PACKET.labels_format,
    packet: PACKET.name,
    packet_digest: PACKET.digest,
    plan_digest: PACKET.plan_digest,
    reviewer: document.getElementById('reviewer').value || 'unknown',
    saved_at: new Date().toISOString(),
    cases: PACKET.cases.map(c => {
      const a = answers[c.case_id];
      const row = {case_id: c.case_id, note: a.note || null};
      /* Explicit null for a question that was not asked. Leaving it undefined
         would have JSON.stringify drop the key, so "not asked" and "renderer
         forgot to ask" would arrive at the server looking identical. */
      for (const q of PACKET.questions) {
        row[q.key] = isAsked(q, a) ? a[q.key] : null;
      }
      return row;
    }),
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
    for (const q of PACKET.questions) {
      if (a[q.key] === undefined) continue;
      const el = document.querySelector(
        `input[name="${q.key}:${id}"][value="${String(a[q.key])}"]`);
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
          format: PACKET.draft_format,
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


def _rubric_html(rubric: Sequence[Mapping[str, Any]]) -> str:
    """The reference panel: every question's full wording, collapsed by default.

    The last question is left open because it is the one being measured and the
    one a reviewer is least likely to have memorised.
    """
    blocks = []
    for index, question in enumerate(rubric):
        options = "".join(
            f"<li><b>{html.escape(option['name'])}</b> — {html.escape(option['what'])}"
            + (
                f"<br><em>Not for:</em> {html.escape(option['not_for'])}"
                if option.get("not_for")
                else ""
            )
            + "</li>"
            for option in question["options"]
        )
        open_attr = " open" if index == len(rubric) - 1 else ""
        blocks.append(
            f"<details{open_attr}><summary>{html.escape(question['prompt'])}</summary>"
            f"<p>{html.escape(question['judge'])}</p><ul>{options}</ul></details>"
        )
    return f'<div class="rubric">{"".join(blocks)}</div>'


def _case_html(case: Mapping[str, Any], rubric: Sequence[Mapping[str, Any]]) -> str:
    case_id = case["case_id"]
    parent = case.get("parent_text")
    parent_block = (
        f'<div class="parent"><em>in reply to</em><br>{html.escape(str(parent))}</div>'
        if parent
        else ""
    )
    fieldsets = []
    for index, question in enumerate(rubric):
        options = "".join(
            f'<label class="opt"><input type="radio" '
            f'name="{html.escape(question["key"])}:{case_id}" '
            f'value="{html.escape(str(option["value"]))}"> '
            f'<span class="n">{html.escape(option["name"])}</span> '
            f'<span class="d">— {html.escape(option["what"])}</span></label>'
            for option in question["options"]
        )
        classes = ["disp"] if index == len(rubric) - 1 else []
        if question.get("asked_when"):
            classes.append("hidden")
        css = f' class="{" ".join(classes)}"' if classes else ""
        key = html.escape(question["key"])
        fieldsets.append(
            f'<fieldset id="q-{key}-{case_id}"{css}>'
            f"<legend>{html.escape(question['prompt'])}</legend>"
            f"{options}</fieldset>"
        )
    return f"""
<div class="case" id="case-{case_id}">
  <h3>Case {case_id}</h3>
  {parent_block}
  <div class="text">{html.escape(case["text"])}</div>
  {"".join(fieldsets)}
  <textarea name="note:{case_id}" rows="2" placeholder="Note (optional)"></textarea>
</div>"""


def render_packet_html(
    name: str,
    digest: str,
    plan_digest: str,
    cases: Sequence[Mapping[str, Any]],
    rubric: Sequence[Mapping[str, Any]],
    *,
    endpoints: Endpoints | None = None,
    formats: Formats = FORMATS_V1,
) -> str:
    """One self-contained blind packet page.

    ``rubric`` is an ordered question list; the page asks exactly the questions it
    holds, in that order, and nothing in this module names any of them.

    ``endpoints`` makes the page submit to a server and sync its draft. Left
    unset, the page downloads and makes no network call of any kind.
    """
    payload = {
        "name": name,
        "digest": digest,
        "plan_digest": plan_digest,
        "labels_format": formats.labels,
        "draft_format": formats.draft,
        "questions": [
            {
                "key": question["key"],
                "value_type": question["value_type"],
                "asked_when": question.get("asked_when"),
            }
            for question in rubric
        ],
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
— no author, no prior label, no model decision. Answer every question from the
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
