// Medical Bill Checker front end. No dependencies.
// Every value from the server or a document is inserted with textContent
// (via el()), never as HTML, so bill text cannot run as code.
"use strict";

const POLL_MS = 3000;
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const MAX_EOBS = 5;
const CASE_KEY = "billchecker.case";
const VIEWS = ["auth-view", "account-view", "upload-view", "status-view", "confirm-view", "failed-view", "results-view"];

const LANG_KEY = "billchecker.lang";
let LANG = "en";

function t(key, vars) {
  let text = (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key;
  for (const [k, v] of Object.entries(vars || {})) text = text.replace("{" + k + "}", v);
  return text;
}

let currentUser = null;
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
  $("#user-menu").hidden = !currentUser || id === "auth-view";
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

function shortDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  const month = t("months")[m - 1];
  return LANG === "es" ? d + " " + month + " " + y : month + " " + d + ", " + y;
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
    throw new Error(t("err_network"));
  }
  if (resp.status === 204) return null;
  let data = null;
  try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
  if (!resp.ok) {
    const detail = data && data.detail;
    if (resp.status === 401 && detail && detail.error === "login_required" && !path.startsWith("/api/auth/")) {
      showAuth(t("session_expired"));
    }
    const translated = LANG === "es" && detail && SERVER_ERRORS_ES[detail.error];
    const err = new Error(
      translated ? translated
        : detail && detail.message ? detail.message
        : resp.status === 429 ? t("err_429")
        : resp.status === 422 ? t("err_422")
        : t("err_generic")
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
  if (list.length > MAX_FILES) throw new Error(t("err_too_many_files"));
  if (list.reduce((n, f) => n + f.size, 0) > MAX_UPLOAD_BYTES) throw new Error(t("err_too_large"));
  const form = new FormData();
  form.append("kind", kind);
  for (const f of list) form.append("file", f);
  return api("POST", "/api/uploads", form);
}

function addEobInput() {
  const box = $("#eob-inputs");
  if (box.children.length >= MAX_EOBS) return;
  const n = box.children.length + 1;
  box.append(el("input", { class: "eob-file", type: "file", multiple: true, "aria-label": t("eob_n", { n }), accept: $("#eob-file").getAttribute("accept") }));
  $("#add-eob").hidden = box.children.length >= MAX_EOBS;
}

async function onUpload(event) {
  event.preventDefault();
  showError("");
  const bill = $("#bill-file").files;
  const eobs = [...document.querySelectorAll(".eob-file")].map((i) => i.files).filter((f) => f.length);
  if (!bill.length) return showError(t("err_choose_bill"));
  const button = $("#upload-button");
  button.disabled = true;
  button.textContent = t("uploading");
  try {
    const billUp = await uploadFiles("bill", bill);
    const eobIds = [];
    for (const files of eobs) eobIds.push((await uploadFiles("eob", files)).upload_id);
    const created = await api("POST", "/api/cases", { bill_upload_id: billUp.upload_id, eob_upload_ids: eobIds, language: LANG });
    remember(created.case_id);
    show("status-view");
    poll();
  } catch (e) {
    showError(e.message);
  } finally {
    button.disabled = false;
    button.textContent = LANG === "es" ? STATIC_ES.check_button : button.dataset.en || "Check my bill";
  }
}

// --- Polling -------------------------------------------------------------------------

function statusText(c) {
  if (c.status === "queued" && c.error_code === "llm_unavailable") {
    return t("status_busy");
  }
  if (c.status === "queued") return t("status_waiting");
  return t("status_reading");
}

async function poll() {
  clearTimeout(pollTimer);
  if (!caseId) return;
  let c;
  try {
    c = await api("GET", "/api/cases/" + caseId);
  } catch (e) {
    if (e.status === 404) return reset(t("expired_or_deleted"));
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
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) throw new Error(t("err_amount_format"));
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
  const known = STRINGS.en["failed_" + c.error_code];
  $("#failed-text").textContent =
    LANG === "es" ? (known ? t("failed_" + c.error_code) : t("failed_internal_error"))
      : c.error_message || (known ? t("failed_" + c.error_code) : t("failed_internal_error"));
  show("failed-view");
}

// --- Results -------------------------------------------------------------------------

function renderResults(c) {
  const bill = c.bill;
  const totals = bill.totals;
  const rows = [
    [t("sum_provider"), bill.provider_name || "—"],
    [t("sum_statement_date"), shortDate(bill.statement_date)],
    [t("sum_total_charges"), money(totals.billed)],
    [t("sum_adjustments"), money(totals.adjustments)],
    [t("sum_amount_due"), money(totals.patient_balance), "strong"],
  ];
  if (c.eob && c.eob.totals) rows.push([t("sum_insurer_says"), money(c.eob.totals.patient_responsibility), "strong"]);
  $("#summary").replaceChildren(...rows.flatMap(([k, v, cls]) => [el("dt", {}, k), el("dd", { class: cls }, v)]));

  const eobNote = $("#eob-note");
  eobNote.hidden = c.eob_status !== "unreadable" && c.eob_status !== "partial";
  eobNote.textContent = c.eob_status === "partial" ? t("eob_partial") : t("eob_unreadable");
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
    const msg = c.eob ? t("none_found_eob") : t("none_found_no_eob");
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
        el("h3", {}, t("rule_" + f.rule), el("span", { class: "badge" }, t("conf_" + f.confidence))),
        el("p", {}, text),
        el(
          "ul",
          { class: "evidence", "aria-label": t("evidence") },
          f.evidence.map((e) =>
            el(
              "li",
              {},
              el("span", { class: "src" }, (e.source === "eob" ? t("src_eob") : t("src_bill")) + (e.page ? t("page", { n: e.page }) : "")),
              el("q", {}, e.text)
            )
          )
        ),
        el(
          "label",
          { class: "include", for: checkboxId },
          el("input", { type: "checkbox", id: checkboxId, "data-flag-id": f.flag_id, checked: true }),
          t("include_letter")
        ),
        feedbackRow(f.flag_id)
      );
    })
  );
}

const VERDICTS = ["correct", "incorrect", "unsure"];

function feedbackRow(flagId) {
  const row = el("div", { class: "feedback" }, el("span", { class: "feedback-q" }, t("was_right")));
  const status = el("span", { class: "thanks", role: "status" });
  for (const verdict of VERDICTS) {
    const b = el("button", { type: "button", class: "small" }, t("verdict_" + verdict));
    b.addEventListener("click", async () => {
      try {
        await api("POST", "/api/cases/" + caseId + "/feedback", { flag_id: flagId, verdict });
        row.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        status.textContent = t("thanks");
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
  if (!helpful || !useful) return showError(t("err_answer_both"));
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
  const prices = c.price_context || {};
  const body = $("#lines tbody");
  if (!lines.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: 3, class: "muted" }, t("no_lines"))));
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
          li.code ? el("div", { class: "line-code" }, t("code", { code: li.code }) + units) : null,
          e && e.source === "llm" ? el("div", { class: "line-expl" }, e.text) : null,
          prices[li.line_id]
            ? el("div", { class: "line-ref" }, t("reference_price", { label: c.prices_label, price: money(prices[li.line_id].reference_price) }))
            : null
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
  const remove = el("button", { type: "button", class: "small danger", "aria-label": t("remove_line") }, t("remove"));
  remove.addEventListener("click", () => row.remove());
  row.append(
    field(t("edit_date"), "service_date", li.service_date, { type: "date" }),
    field(t("edit_code"), "code", li.code, { type: "text", maxlength: 20 }),
    field(t("edit_service"), "description", li.description, { type: "text", maxlength: 300, required: true }),
    field(t("edit_units"), "units", li.units, { type: "text", inputmode: "decimal" }),
    field(t("edit_charge"), "charge", li.charge, { type: "text", inputmode: "decimal", required: true }),
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
      if (!v("description")) throw new Error(t("err_line_desc", { n: i + 1 }));
      const charge = parseAmount(v("charge"));
      if (charge === null) throw new Error(t("err_line_charge", { n: i + 1 }));
      const units = v("units");
      if (units && !/^\d+(\.\d+)?$/.test(units)) throw new Error(t("err_line_units", { n: i + 1 }));
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
  $("#glossary").replaceChildren(...GLOSSARY[LANG].flatMap(([term, def]) => [el("dt", {}, term), el("dd", {}, def)]));
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
  if (!name) return showError(t("err_name"));
  const address = $("#p-address").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (address.length > 4) return showError(t("err_address"));
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
    if (!body.flag_ids.length) return showError(t("err_tick"));
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
    $("#copy-letter").textContent = t("copied");
    setTimeout(() => ($("#copy-letter").textContent = t("copy_text")), 2000);
  } catch (e) {
    showError(t("err_copy"));
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
    if (!resp.ok) throw new Error(t("err_pdf"));
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
  loadHistory();
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
  if (!window.confirm(t("confirm_delete"))) return;
  try {
    await api("DELETE", "/api/cases/" + caseId);
  } catch (e) {
    if (e.status !== 404) return showError(e.message);
  }
  reset(t("deleted"));
}

// --- Language ------------------------------------------------------------------------

function applyLanguage(lang) {
  LANG = lang === "es" ? "es" : "en";
  document.documentElement.lang = LANG;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    if (node.dataset.en === undefined) node.dataset.en = node.textContent;
    node.textContent = LANG === "es" ? STATIC_ES[node.dataset.i18n] || node.dataset.en : node.dataset.en;
  }
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) {
    if (node.dataset.enPlaceholder === undefined) node.dataset.enPlaceholder = node.placeholder;
    node.placeholder = LANG === "es" ? STATIC_ES[node.dataset.i18nPlaceholder] || node.dataset.enPlaceholder : node.dataset.enPlaceholder;
  }
  const toggle = $("#lang-toggle");
  toggle.textContent = t("lang_toggle");
  toggle.lang = LANG === "es" ? "en" : "es";
  renderGlossary();
  // Re-render what is on screen so text built in JS switches too.
  if (caseData && caseData.status === "ready" && caseData.language !== LANG) {
    // Explanations were written in the other language; ask for them again.
    api("PUT", "/api/cases/" + caseId + "/language", { language: LANG })
      .then(() => { show("status-view"); $("#status-text").textContent = t("status_reading"); poll(); })
      .catch((e) => showError(e.message));
  } else if (caseData && caseData.status === "ready") {
    const pending = selectedFlagIds();
    renderResults(caseData);
    document.querySelectorAll("#flags input[data-flag-id]").forEach((i) => (i.checked = pending.includes(i.dataset.flagId)));
  } else if (caseData && !$("#status-view").hidden) {
    $("#status-text").textContent = statusText(caseData);
  }
  try { localStorage.setItem(LANG_KEY, LANG); } catch (e) { /* preference just won't persist */ }
}

function initialLanguage() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved) return saved;
  } catch (e) { /* ignore */ }
  return (navigator.language || "").toLowerCase().startsWith("es") ? "es" : "en";
}

// --- Accounts ------------------------------------------------------------------------

function showAuth(message, register) {
  clearTimeout(pollTimer);
  currentUser = null;
  caseData = null;
  remember(null);
  $("#login-form").hidden = !!register;
  $("#register-form").hidden = !register;
  show("auth-view");
  showError(message || "");
}

function loggedIn(user) {
  currentUser = user;
  $("#user-email").textContent = user.email;
  $("#login-form").reset();
  $("#register-form").reset();
}

async function onLogin(event) {
  event.preventDefault();
  showError("");
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  if (!email || !password) return showError(t("err_login_fields"));
  try {
    loggedIn(await api("POST", "/api/auth/login", { email, password }));
    reset();
  } catch (e) {
    showError(e.message);
  }
}

async function onRegister(event) {
  event.preventDefault();
  showError("");
  const email = $("#reg-email").value.trim();
  const password = $("#reg-password").value;
  if (!email || !password) return showError(t("err_login_fields"));
  try {
    loggedIn(await api("POST", "/api/auth/register", { email, password, research_consent: $("#reg-consent").checked }));
    reset();
  } catch (e) {
    showError(e.message);
  }
}

async function onLogout() {
  try { await api("POST", "/api/auth/logout"); } catch (e) { /* already logged out */ }
  showAuth(t("logged_out"));
}

function openAccount() {
  showError("");
  $("#account-email").textContent = currentUser.email;
  $("#account-consent").checked = !!currentUser.research_consent;
  $("#consent-saved").hidden = true;
  $("#password-saved").hidden = true;
  $("#password-form").reset();
  $("#delete-account-form").reset();
  clearTimeout(pollTimer);
  show("account-view");
}

async function onConsent(event) {
  event.preventDefault();
  try {
    currentUser = await api("PUT", "/api/auth/consent", { research_consent: $("#account-consent").checked });
    $("#consent-saved").hidden = false;
  } catch (e) {
    showError(e.message);
  }
}

async function onChangePassword(event) {
  event.preventDefault();
  showError("");
  const current = $("#pw-current").value;
  const next = $("#pw-new").value;
  if (!current || !next) return showError(t("err_new_password"));
  try {
    await api("POST", "/api/auth/password", { current_password: current, new_password: next });
    $("#password-form").reset();
    $("#password-saved").hidden = false;
  } catch (e) {
    showError(e.message);
  }
}

async function onDeleteAccount(event) {
  event.preventDefault();
  showError("");
  const password = $("#del-password").value;
  if (!password) return showError(t("err_login_fields"));
  if (!window.confirm(t("confirm_delete_account"))) return;
  try {
    await api("DELETE", "/api/auth/account", { password });
    showAuth(t("account_deleted"));
  } catch (e) {
    showError(e.message);
  }
}

// --- History -------------------------------------------------------------------------

async function loadHistory() {
  if (!currentUser) return;
  let data;
  try {
    data = await api("GET", "/api/cases");
  } catch (e) {
    return;
  }
  const list = $("#history-list");
  list.replaceChildren(
    ...data.cases.map((c) => {
      const when = shortDate(c.created_at.slice(0, 10));
      const detail =
        c.status === "ready"
          ? [c.amount_due ? t("history_due", { amount: money(c.amount_due) }) : null, c.flag_count ? t("history_flags", { n: c.flag_count }) : t("history_none")]
          : [t("status_short_" + c.status)];
      const button = el(
        "button",
        { type: "button", class: "history-item" },
        el("span", { class: "history-main" }, c.provider_name || t("history_bill")),
        el("span", { class: "history-meta" }, [when].concat(detail.filter(Boolean)).join(" · "))
      );
      button.addEventListener("click", () => openCase(c.case_id));
      return el("li", {}, button);
    })
  );
  $("#history").hidden = data.cases.length === 0;
}

function openCase(id) {
  remember(id);
  caseData = null;
  show("status-view");
  $("#status-text").textContent = t("status_reading");
  poll();
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
  $("#lang-toggle").addEventListener("click", () => applyLanguage(LANG === "es" ? "en" : "es"));
  applyLanguage(initialLanguage());
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

  $("#login-form").addEventListener("submit", onLogin);
  $("#register-form").addEventListener("submit", onRegister);
  $("#show-register").addEventListener("click", () => showAuth("", true));
  $("#show-login").addEventListener("click", () => showAuth("", false));
  $("#logout-button").addEventListener("click", onLogout);
  $("#account-button").addEventListener("click", openAccount);
  $("#account-back").addEventListener("click", () => reset());
  $("#consent-form").addEventListener("submit", onConsent);
  $("#password-form").addEventListener("submit", onChangePassword);
  $("#delete-account-form").addEventListener("submit", onDeleteAccount);

  api("GET", "/api/auth/session")
    .then(({ user }) => {
      if (!user) return showAuth("");
      loggedIn(user);
      const saved = recalled();
      if (saved) openCase(saved);
      else reset();
    })
    .catch(() => showAuth(""));
});
