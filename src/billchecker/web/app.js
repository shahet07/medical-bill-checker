// Medical Bill Checker front end. No dependencies.
// Every value from the server or a document is inserted with textContent
// (via el()), never as HTML, so bill text cannot run as code.
"use strict";

const POLL_MS = 3000;
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const MAX_EOBS = 5;
const CASE_KEY = "billchecker.case";
const VIEWS = ["upload-view", "status-view", "confirm-view", "failed-view", "results-view"];

const RULE_TITLES = {
  duplicate_line: "Possible duplicate charge",
  balance_mismatch: "Amount due doesn't match your insurance statement",
  billed_after_denial: "Billed for a service your insurer denied",
  network_mismatch: "Out-of-network billing for in-network care",
  no_itemization: "No itemized list of charges",
  not_on_eob: "Service not on your insurance statement",
  charge_mismatch: "Charge differs from what your insurer was billed",
  payment_not_applied: "Insurance payment may not be applied",
};
// Plain-language definitions written for this tool.
const GLOSSARY = [
  ["EOB (Explanation of Benefits)", "A statement from your insurer showing what the provider charged, what your plan paid, and what you may owe. It is not a bill."],
  ["Itemized bill", "A bill that lists each service separately, with its date, code, and charge."],
  ["Allowed amount", "The most your plan will pay for a covered service, as agreed with in-network providers. Charges above this are usually written off."],
  ["Adjustment", "An amount taken off the bill, often the discount your insurer negotiated with the provider."],
  ["Deductible", "What you pay each year for covered care before your plan starts to pay."],
  ["Copay", "A fixed amount you pay for a service, such as $30 for a visit."],
  ["Coinsurance", "Your share of the cost as a percentage, such as 20% of the allowed amount, after your deductible."],
  ["In network / out of network", "In-network providers have a contract with your insurer and usually cost you less. Out-of-network providers do not."],
  ["Denied claim", "A service your insurer decided not to pay for. You can ask your insurer to review the decision."],
  ["Procedure code (CPT or HCPCS)", "A short code that identifies the service you received. Hospitals may also use revenue codes for departments."],
  ["Financial assistance (charity care)", "Free or reduced-cost care that many hospitals offer based on income. Nonprofit hospitals are required to have a policy."],
];

const CONFIDENCE = { high: "Strong signal", medium: "Worth a look", low: "Weak signal" };
const FAILED_TEXT = {
  unreadable: "We could not read this bill. Please try a clearer, flat photo in good light, or the PDF version.",
  llm_unavailable: "The reading service was unavailable for too long. Please try again in a little while.",
  expired: "Your upload expired. Please upload it again.",
  internal_error: "Something went wrong on our side. Please try again.",
};

let caseId = null;
let caseData = null;
let pollTimer = null;
let lastLetter = null;
let lastLetterRequest = null;

// --- Small helpers -------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function show(id) {
  for (const v of VIEWS) $("#" + v).hidden = v !== id;
  window.scrollTo(0, 0);
}

function showError(message) {
  const b = $("#error-banner");
  b.textContent = message || "";
  b.hidden = !message;
}

function remember(id) {
  caseId = id;
  try {
    if (id) sessionStorage.setItem(CASE_KEY, id);
    else sessionStorage.removeItem(CASE_KEY);
  } catch (e) { /* storage unavailable: resume-on-reload just won't work */ }
}

function recalled() {
  try { return sessionStorage.getItem(CASE_KEY); } catch (e) { return null; }
}

// "1250.5" -> "$1,250.50"; works on the decimal string, never a float.
function money(value) {
  if (value === null || value === undefined) return "—";
  const s = String(value);
  const neg = s.startsWith("-");
  const [whole, frac = ""] = s.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "−" : "") + "$" + grouped + "." + (frac + "00").slice(0, 2);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function shortDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return MONTHS[m - 1] + " " + d + ", " + y;
}

async function api(method, path, body) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (e) {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  if (resp.status === 204) return null;
  let data = null;
  try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
  if (!resp.ok) {
    const detail = data && data.detail;
    const err = new Error(
      detail && detail.message ? detail.message
        : resp.status === 429 ? "Too many requests. Please wait a while and try again."
        : resp.status === 422 ? "Please check the details you entered."
        : "Something went wrong. Please try again."
    );
    err.status = resp.status;
    throw err;
  }
  return data;
}

// --- Upload --------------------------------------------------------------------------

// One document as one or more files (e.g. a photo of each page).
async function uploadFiles(kind, files) {
  const list = [...files];
  if (list.length > MAX_FILES) throw new Error("Please choose at most 10 files for one document.");
  if (list.reduce((n, f) => n + f.size, 0) > MAX_UPLOAD_BYTES) throw new Error("These files add up to more than 20 MB.");
  const form = new FormData();
  form.append("kind", kind);
  for (const f of list) form.append("file", f);
  return api("POST", "/api/uploads", form);
}

function addEobInput() {
  const box = $("#eob-inputs");
  if (box.children.length >= MAX_EOBS) return;
  const n = box.children.length + 1;
  box.append(el("input", { class: "eob-file", type: "file", multiple: true, "aria-label": "EOB " + n, accept: $("#eob-file").getAttribute("accept") }));
  $("#add-eob").hidden = box.children.length >= MAX_EOBS;
}

async function onUpload(event) {
  event.preventDefault();
  showError("");
  const bill = $("#bill-file").files;
  const eobs = [...document.querySelectorAll(".eob-file")].map((i) => i.files).filter((f) => f.length);
  if (!bill.length) return showError("Please choose your bill to upload.");
  const button = $("#upload-button");
  button.disabled = true;
  button.textContent = "Uploading…";
  try {
    const billUp = await uploadFiles("bill", bill);
    const eobIds = [];
    for (const files of eobs) eobIds.push((await uploadFiles("eob", files)).upload_id);
    const created = await api("POST", "/api/cases", { bill_upload_id: billUp.upload_id, eob_upload_ids: eobIds });
    remember(created.case_id);
    show("status-view");
    poll();
  } catch (e) {
    showError(e.message);
  } finally {
    button.disabled = false;
    button.textContent = "Check my bill";
  }
}

// --- Polling -------------------------------------------------------------------------

function statusText(c) {
  if (c.status === "queued" && c.error_code === "llm_unavailable") {
    return "The reading service is busy right now. We'll keep trying automatically. You can leave this page open.";
  }
  if (c.status === "queued") return "Waiting to start…";
  return "Reading your documents. This usually takes under a minute.";
}

async function poll() {
  clearTimeout(pollTimer);
  if (!caseId) return;
  let c;
  try {
    c = await api("GET", "/api/cases/" + caseId);
  } catch (e) {
    if (e.status === 404) return reset("This check has expired or was deleted.");
    pollTimer = setTimeout(poll, POLL_MS * 2);
    return;
  }
  caseData = c;
  if (c.status === "ready") return renderResults(c);
  if (c.status === "needs_confirmation") return renderConfirm(c);
  if (c.status === "failed") return renderFailed(c);
  show("status-view");
  $("#status-text").textContent = statusText(c);
  pollTimer = setTimeout(poll, POLL_MS);
}

// --- Confirm -------------------------------------------------------------------------

function renderConfirm(c) {
  const list = $("#confirm-problems");
  list.replaceChildren(...(c.problems || []).map((p) => el("li", {}, p)));
  const totals = (c.bill && c.bill.totals) || {};
  $("#confirm-billed").value = totals.billed || "";
  $("#confirm-balance").value = totals.patient_balance || "";
  show("confirm-view");
}

function parseAmount(raw) {
  const s = raw.trim().replace(/[$,\s]/g, "");
  if (!s) return null;
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) throw new Error("Please enter amounts like 1250.00");
  return s;
}

async function onConfirm(event) {
  event.preventDefault();
  showError("");
  try {
    const body = { billed: parseAmount($("#confirm-billed").value), patient_balance: parseAmount($("#confirm-balance").value) };
    await api("POST", "/api/cases/" + caseId + "/confirm", body);
    show("status-view");
    poll();
  } catch (e) {
    showError(e.message);
  }
}

// --- Failed --------------------------------------------------------------------------

function renderFailed(c) {
  $("#failed-text").textContent = c.error_message || FAILED_TEXT[c.error_code] || FAILED_TEXT.internal_error;
  show("failed-view");
}

// --- Results -------------------------------------------------------------------------

function renderResults(c) {
  const bill = c.bill;
  const totals = bill.totals;
  const rows = [
    ["Provider", bill.provider_name || "—"],
    ["Statement date", shortDate(bill.statement_date)],
    ["Total charges", money(totals.billed)],
    ["Payments and adjustments", money(totals.adjustments)],
    ["Amount due", money(totals.patient_balance), "strong"],
  ];
  if (c.eob && c.eob.totals) rows.push(["Your insurer says you owe", money(c.eob.totals.patient_responsibility), "strong"]);
  $("#summary").replaceChildren(...rows.flatMap(([k, v, cls]) => [el("dt", {}, k), el("dd", { class: cls }, v)]));

  const eobNote = $("#eob-note");
  eobNote.hidden = c.eob_status !== "unreadable" && c.eob_status !== "partial";
  eobNote.textContent = c.eob_status === "partial"
    ? "We could not read one of your EOBs, so checks that compare the whole bill with your insurance were skipped. Try uploading a clearer copy."
    : "We could not read your EOB, so the bill was checked on its own. Try uploading a clearer copy to compare them.";
  $("#warning-note").hidden = (!(c.warnings && c.warnings.length) && bill.extraction_confidence !== "low") || c.user_edited;
  $("#edited-note").hidden = !c.user_edited;
  closeEditor();

  renderFlags(c);
  renderLines(c);
  setupLetterForm(c);
  show("results-view");
}

function renderFlags(c) {
  const box = $("#flags");
  const flags = c.flags || [];
  const expl = (c.explanations && c.explanations.flags) || {};
  $("#flags-intro").hidden = flags.length === 0;
  if (!flags.length) {
    const msg = c.eob
      ? "We did not find anything that needs checking. That does not guarantee the bill is correct, but the basic checks passed."
      : "We did not find anything that needs checking. Adding your insurer's EOB lets us run more checks.";
    box.replaceChildren(el("p", { class: "none-found" }, msg));
    return;
  }
  box.replaceChildren(
    ...flags.map((f) => {
      const text = (expl[f.flag_id] && expl[f.flag_id].text) || f.summary;
      const checkboxId = "include-" + f.flag_id.replace(/[^a-zA-Z0-9]/g, "-");
      return el(
        "article",
        { class: "flag" },
        el("h3", {}, RULE_TITLES[f.rule] || f.rule, el("span", { class: "badge" }, CONFIDENCE[f.confidence] || "")),
        el("p", {}, text),
        el(
          "ul",
          { class: "evidence", "aria-label": "Evidence" },
          f.evidence.map((e) =>
            el(
              "li",
              {},
              el("span", { class: "src" }, (e.source === "eob" ? "Insurance statement" : "Your bill") + (e.page ? ", page " + e.page : "")),
              el("q", {}, e.text)
            )
          )
        ),
        el(
          "label",
          { class: "include", for: checkboxId },
          el("input", { type: "checkbox", id: checkboxId, "data-flag-id": f.flag_id, checked: true }),
          "Include in my letter"
        ),
        feedbackRow(f.flag_id)
      );
    })
  );
}

const VERDICTS = [["correct", "Yes, a real problem"], ["incorrect", "No, it was fine"], ["unsure", "Not sure yet"]];

function feedbackRow(flagId) {
  const row = el("div", { class: "feedback" }, el("span", { class: "feedback-q" }, "Was this right?"));
  const status = el("span", { class: "thanks", role: "status" });
  for (const [verdict, label] of VERDICTS) {
    const b = el("button", { type: "button", class: "small" }, label);
    b.addEventListener("click", async () => {
      try {
        await api("POST", "/api/cases/" + caseId + "/feedback", { flag_id: flagId, verdict });
        row.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        status.textContent = "Thanks";
      } catch (e) {
        status.textContent = "";
        showError(e.message);
      }
    });
    row.append(b);
  }
  row.append(status);
  return row;
}

async function onSurvey(event) {
  event.preventDefault();
  const helpful = document.querySelector('input[name="helpful"]:checked');
  const useful = document.querySelector('input[name="most_useful"]:checked');
  if (!helpful || !useful) return showError("Please answer both questions.");
  try {
    await api("POST", "/api/cases/" + caseId + "/survey", { helpful: Number(helpful.value), most_useful: useful.value });
    showError("");
    $("#survey-thanks").hidden = false;
  } catch (e) {
    showError(e.message);
  }
}

function renderLines(c) {
  const lines = c.bill.line_items || [];
  const expl = (c.explanations && c.explanations.lines) || {};
  const body = $("#lines tbody");
  if (!lines.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: 3, class: "muted" }, "This bill lists no individual services, only a total. You can ask for an itemized bill below.")));
    return;
  }
  body.replaceChildren(
    ...lines.map((li) => {
      const e = expl[li.line_id];
      const units = li.units && Number(li.units) !== 1 ? " × " + li.units : "";
      return el(
        "tr",
        {},
        el("td", { class: "date" }, shortDate(li.service_date)),
        el(
          "td",
          {},
          el("div", { class: "line-desc" }, li.description),
          el("div", { class: "line-date" }, shortDate(li.service_date)),
          li.code ? el("div", { class: "line-code" }, "Code " + li.code + units) : null,
          e && e.source === "llm" ? el("div", { class: "line-expl" }, e.text) : null
        ),
        el("td", { class: "num" }, money(li.charge))
      );
    })
  );
}

// --- Editing ---------------------------------------------------------------------------

function editRow(li) {
  const row = el("fieldset", { class: "edit-row", "data-line-id": li.line_id || "" });
  const field = (label, name, value, attrs) =>
    el("label", { class: "edit-cell edit-" + name }, el("span", {}, label), el("input", Object.assign({ name, value: value || "" }, attrs || {})));
  const remove = el("button", { type: "button", class: "small danger", "aria-label": "Remove this line" }, "Remove");
  remove.addEventListener("click", () => row.remove());
  row.append(
    field("Date", "service_date", li.service_date, { type: "date" }),
    field("Code", "code", li.code, { type: "text", maxlength: 20 }),
    field("Service", "description", li.description, { type: "text", maxlength: 300, required: true }),
    field("Units", "units", li.units, { type: "text", inputmode: "decimal" }),
    field("Charge", "charge", li.charge, { type: "text", inputmode: "decimal", required: true }),
    remove
  );
  return row;
}

function openEditor() {
  const bill = caseData.bill;
  $("#edit-rows").replaceChildren(...bill.line_items.map(editRow));
  $("#edit-billed").value = bill.totals.billed || "";
  $("#edit-adjust").value = bill.totals.adjustments || "";
  $("#edit-balance").value = bill.totals.patient_balance || "";
  $("#edit-form").hidden = false;
  $("#lines-wrap").hidden = true;
  $("#edit-lines").hidden = true;
}

function closeEditor() {
  $("#edit-form").hidden = true;
  $("#lines-wrap").hidden = false;
  $("#edit-lines").hidden = false;
}

async function onSaveEdit(event) {
  event.preventDefault();
  showError("");
  try {
    const lines = [...document.querySelectorAll("#edit-rows .edit-row")].map((row, i) => {
      const v = (name) => row.querySelector('[name="' + name + '"]').value.trim();
      if (!v("description")) throw new Error("Line " + (i + 1) + " needs a description.");
      const charge = parseAmount(v("charge"));
      if (charge === null) throw new Error("Line " + (i + 1) + " needs a charge.");
      const units = v("units");
      if (units && !/^\d+(\.\d+)?$/.test(units)) throw new Error("Line " + (i + 1) + ": units should be a number.");
      return {
        line_id: row.dataset.lineId || null,
        service_date: v("service_date") || null,
        description: v("description"),
        code: v("code") || null,
        units: units || null,
        charge,
      };
    });
    const totals = {
      billed: parseAmount($("#edit-billed").value),
      adjustments: parseAmount($("#edit-adjust").value),
      patient_balance: parseAmount($("#edit-balance").value),
    };
    await api("PUT", "/api/cases/" + caseId + "/bill", { line_items: lines, totals });
    show("status-view");
    poll();
  } catch (e) {
    showError(e.message);
  }
}

function renderGlossary() {
  $("#glossary").replaceChildren(...GLOSSARY.flatMap(([term, def]) => [el("dt", {}, term), el("dd", {}, def)]));
}

// --- Letter --------------------------------------------------------------------------

function hasDenials(c) {
  return !!(c.eob && c.eob.service_lines.some((sl) => sl.status === "denied" || sl.status === "not_processed"));
}

function setupLetterForm(c) {
  const hasFlags = (c.flags || []).length > 0;
  const dispute = $("#kind-dispute");
  dispute.disabled = !hasFlags;
  (hasFlags ? dispute : $("#kind-itemized")).checked = true;
  $("#appeal-choice").hidden = !hasDenials(c);
  $("#letter-output").hidden = true;
  onKindChange();
}

function onKindChange() {
  const checked = document.querySelector('input[name="kind"]:checked');
  const kind = checked ? checked.value : "";
  $("#dispute-hint").hidden = kind !== "dispute";
  $("#assistance-hint").hidden = kind !== "financial_assistance";
  $("#plan-field").hidden = kind !== "payment_plan";
  $("#member-field").hidden = kind !== "insurer_appeal";
  $("#p-account").closest(".field").hidden = kind === "insurer_appeal";
}

function selectedFlagIds() {
  return [...document.querySelectorAll("#flags input[data-flag-id]")].filter((i) => i.checked).map((i) => i.dataset.flagId);
}

async function onLetter(event) {
  event.preventDefault();
  showError("");
  const kind = document.querySelector('input[name="kind"]:checked').value;
  const name = $("#p-name").value.trim();
  if (!name) return showError("Please enter your name for the letter.");
  const address = $("#p-address").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (address.length > 4) return showError("Please keep your address to 4 lines.");
  const body = {
    kind,
    patient: {
      name,
      address_lines: address,
      phone: $("#p-phone").value.trim() || null,
      email: $("#p-email").value.trim() || null,
      account_number: $("#p-account").value.trim() || null,
      member_id: $("#p-member").value.trim() || null,
    },
    note: $("#p-note").value.trim() || null,
  };
  if (kind === "payment_plan") {
    try {
      body.monthly_amount = parseAmount($("#p-monthly").value);
    } catch (e) {
      return showError(e.message);
    }
  }
  if (kind === "dispute") {
    body.flag_ids = selectedFlagIds();
    if (!body.flag_ids.length) return showError("Tick at least one item above to include in the letter.");
  }
  try {
    const letter = await api("POST", "/api/cases/" + caseId + "/letter", body);
    lastLetter = letter;
    lastLetterRequest = body;
    $("#letter-text").textContent = letter.text;
    $("#letter-output").hidden = false;
    $("#letter-text").focus();
  } catch (e) {
    showError(e.message);
  }
}

async function onCopy() {
  if (!lastLetter) return;
  try {
    await navigator.clipboard.writeText(lastLetter.text);
    $("#copy-letter").textContent = "Copied";
    setTimeout(() => ($("#copy-letter").textContent = "Copy"), 2000);
  } catch (e) {
    showError("Copy did not work. Select the letter text and copy it yourself.");
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function letterFilename(ext) {
  return (lastLetter ? lastLetter.kind.replace(/_/g, "-") : "letter") + "." + ext;
}

function onDownload() {
  if (!lastLetter) return;
  saveBlob(new Blob([lastLetter.text], { type: "text/plain;charset=utf-8" }), letterFilename("txt"));
}

async function onDownloadPdf() {
  if (!lastLetterRequest) return;
  const button = $("#download-pdf");
  button.disabled = true;
  try {
    const resp = await fetch("/api/cases/" + caseId + "/letter", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(Object.assign({}, lastLetterRequest, { format: "pdf" })),
    });
    if (!resp.ok) throw new Error("The PDF could not be created. Please try again.");
    saveBlob(await resp.blob(), letterFilename("pdf"));
  } catch (e) {
    showError(e.message);
  } finally {
    button.disabled = false;
  }
}

// --- Reset and delete ----------------------------------------------------------------

function reset(message) {
  clearTimeout(pollTimer);
  remember(null);
  caseData = null;
  lastLetter = null;
  lastLetterRequest = null;
  $("#upload-form").reset();
  [...document.querySelectorAll(".eob-file")].slice(1).forEach((i) => i.remove());
  $("#add-eob").hidden = false;
  $("#letter-form").reset();
  $("#survey-form").reset();
  $("#survey-thanks").hidden = true;
  showError(message || "");
  show("upload-view");
}

// Failed checks have nothing to come back to, so remove them without asking.
async function discardAndReset() {
  if (caseId) {
    try { await api("DELETE", "/api/cases/" + caseId); } catch (e) { /* expired or already gone */ }
  }
  reset();
}

async function deleteCase() {
  if (!caseId) return reset();
  if (!window.confirm("Delete your uploaded files and results now? This cannot be undone.")) return;
  try {
    await api("DELETE", "/api/cases/" + caseId);
  } catch (e) {
    if (e.status !== 404) return showError(e.message);
  }
  reset("Your files and results have been deleted.");
}

// --- Start ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  $("#upload-form").addEventListener("submit", onUpload);
  $("#add-eob").addEventListener("click", addEobInput);
  $("#survey-form").addEventListener("submit", onSurvey);
  $("#edit-lines").addEventListener("click", openEditor);
  $("#edit-cancel").addEventListener("click", closeEditor);
  $("#add-line").addEventListener("click", () => $("#edit-rows").append(editRow({})));
  $("#edit-form").addEventListener("submit", onSaveEdit);
  renderGlossary();
  document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener("change", onKindChange));
  $("#confirm-form").addEventListener("submit", onConfirm);
  $("#letter-form").addEventListener("submit", onLetter);
  $("#copy-letter").addEventListener("click", onCopy);
  $("#download-letter").addEventListener("click", onDownload);
  $("#download-pdf").addEventListener("click", onDownloadPdf);
  $("#delete-case").addEventListener("click", deleteCase);
  $("#cancel-button").addEventListener("click", deleteCase);
  $("#failed-restart").addEventListener("click", discardAndReset);
  $("#new-bill").addEventListener("click", () => reset());

  const saved = recalled();
  if (saved) {
    caseId = saved;
    show("status-view");
    poll();
  } else {
    show("upload-view");
  }
});
