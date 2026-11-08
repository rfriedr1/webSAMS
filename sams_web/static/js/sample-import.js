/**
 * Sample-import wizard.
 *
 * The parse endpoint returns a complete review payload; everything after
 * that happens in browser memory until the operator commits. That keeps
 * re-mapping a column or reassigning a group instant, and avoids
 * inventing server-side session state for a draft that may never be saved.
 *
 * Stages: upload -> review (who/what) -> lab (values + prep steps) -> done (+ e-mail).
 *
 * state:
 *   payload   - raw response from /samples/import/parse
 *   draft     - payload.draft, mutated in place as the operator edits
 *   mapping   - column letter -> canonical field
 *   party     - { submitter, invoice }: each { mode, user_nr, values }
 *   project   - { mode: 'new'|'existing', existing_project_nr, values }
 *   groups    - submitter-material -> { type, material, fraction, steps[] }
 *   selection - Set of sample indices ticked for bulk apply
 */
(() => {
  const root = document.querySelector("[data-sample-import]");
  if (!root) return;

  const $ = (sel) => root.querySelector(sel);
  const LOOKUP_FIELDS = ["type", "material", "fraction"];
  /** Lab type every group starts with (matched case-insensitively). */
  const DEFAULT_LAB_TYPE = "arch";

  const state = {
    payload: null,
    draft: null,
    mapping: {},
    party: {
      submitter: { mode: "new", user_nr: null, picking: false, values: {}, browse: [], browseRan: false, query: "" },
      invoice: { enabled: false, mode: "new", user_nr: null, picking: false, values: {}, browse: [], browseRan: false, query: "" },
    },
    project: { mode: "new", existing_project_nr: null, values: {}, existing: [], matches: [] },
    groups: {},
    selection: new Set(),
    // Operator's explicit show/hide per sheet column (field -> bool).
    // Columns without an entry here follow `hasEntries`.
    columnVisibility: new Map(),
    committing: false,
    result: null,
  };

  // ---------------------------------------------------------------- utils

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);

  const TECHNICAL_LABELS = {
    reference: "Reference", time: "Time", stage: "Stage", sheet_row: "Sheet row",
    sample_label: "Sample label", error_type: "Error type", message: "Message",
    database_error: "Database error", sql: "SQL statement", location: "Raised in",
    caused_by: "Caused by", context: "Context",
  };

  // Plain text of the technical details, for the Copy button and the support mail.
  const technicalText = (technical) =>
    Object.entries(technical)
      .map(([key, value]) => {
        const label = TECHNICAL_LABELS[key] || key;
        if (Array.isArray(value)) return `${label}: ${value.join(" <- ")}`;
        if (value && typeof value === "object") {
          return `${label}: ` + Object.entries(value).map(([k, v]) => `${k}=${v}`).join(", ");
        }
        return `${label}: ${value}`;
      })
      .join("\n");

  const showError = (message, technical) => {
    const box = $("[data-import-error]");
    box.textContent = "";
    const text = document.createElement("span");
    text.textContent = message;
    box.append(text);
    if (message && technical) {
      const details = document.createElement("details");
      details.className = "import-error-details";
      const summary = document.createElement("summary");
      summary.textContent = `Technical details (ref. ${technical.reference || "n/a"})`;
      const pre = document.createElement("pre");
      pre.textContent = technicalText(technical);
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "import-error-copy";
      copy.textContent = "Copy details";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(pre.textContent);
          window.SAMSToast?.show("Technical details copied.", "success");
        } catch (_error) {
          const range = document.createRange();
          range.selectNodeContents(pre);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        }
      });
      details.append(summary, pre, copy);
      box.append(details);
    }
    box.hidden = !message;
    if (message) box.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const STEPS = ["upload", "review", "lab", "extras", "done"];
  const setStep = (step) => {
    const index = STEPS.indexOf(step);
    root.querySelectorAll("[data-stage]").forEach((el) => {
      el.hidden = el.dataset.stage !== step;
    });
    root.querySelectorAll(".import-step").forEach((el) => {
      const position = STEPS.indexOf(el.dataset.step);
      el.classList.toggle("is-current", position === index);
      el.classList.toggle("is-done", position < index);
      if (position === index) el.setAttribute("aria-current", "step");
      else el.removeAttribute("aria-current");
    });
    // The action bar serves steps 2-4; each of its parts names its step.
    $("[data-foot]").hidden = !root.querySelector(`[data-foot-for="${step}"]`);
    root.querySelectorAll("[data-foot-for]").forEach((el) => {
      el.hidden = el.dataset.footFor !== step;
    });
    $("[data-file-chip]").hidden = step === "upload" || !state.draft;
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const guardUnload = (event) => {
    if (!state.draft || state.committing || state.result) return;
    event.preventDefault();
    event.returnValue = "";
  };

  const optionList = (options, current, placeholder) =>
    [`<option value="">${esc(placeholder)}</option>`]
      .concat(
        options.map(
          (o) =>
            `<option value="${esc(o)}" ${o === current ? "selected" : ""}>${esc(o)}</option>`
        )
      )
      .join("");

  // -------------------------------------------------------------- step 1

  const dropzone = $("[data-dropzone]");
  const fileInput = $("[data-file-input]");
  const busy = $("[data-dropzone-busy]");

  const uploadFile = async (file) => {
    if (!file) return;
    showError("");
    busy.hidden = false;
    dropzone.classList.add("is-busy");
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/samples/import/parse", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) {
        showError(payload.detail || "The workbook could not be read.", payload.technical);
        return;
      }
      applyPayload(payload);
      setStep("review");
      window.addEventListener("beforeunload", guardUnload);
    } catch (error) {
      showError("Upload failed. Check your connection and try again.", {
        stage: "Uploading the workbook (browser)", error_type: error?.name || "Error",
        message: error?.message || String(error), context: { file: file.name, size_bytes: file.size },
      });
    } finally {
      busy.hidden = true;
      dropzone.classList.remove("is-busy");
      fileInput.value = "";
    }
  };

  fileInput.addEventListener("change", () => uploadFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((t) =>
    dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add("is-dragging"); })
  );
  ["dragleave", "drop"].forEach((t) =>
    dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.remove("is-dragging"); })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });

  $("[data-restart]").addEventListener("click", () => {
    window.removeEventListener("beforeunload", guardUnload);
    state.draft = null;
    state.result = null;
    showError("");
    setStep("upload");
  });
  $("[data-invoice-enabled]").addEventListener("change", (event) => {
    state.party.invoice.enabled = event.target.checked;
    renderParty("invoice");
    renderAlerts();
  });
  $("[data-back-review]").addEventListener("click", () => setStep("review"));
  $("[data-goto-lab]").addEventListener("click", () => {
    if (reviewProblems().length) { renderAlerts(); return; }
    setStep("lab");
    renderLabStage();
  });
  $("[data-back-lab]").addEventListener("click", () => {
    setStep("lab");
    renderLabStage();
  });
  $("[data-goto-extras]").addEventListener("click", () => {
    if (labProblems().length) { renderLabAlerts(); return; }
    setStep("extras");
    renderExtrasStage();
  });

  // ------------------------------------------------------------ bootstrap

  function applyPayload(payload) {
    state.payload = payload;
    state.draft = payload.draft;
    state.selection = new Set();
    state.columnVisibility = new Map();
    state.result = null;

    state.mapping = {};
    payload.draft.columns.forEach((c) => { state.mapping[c.column_letter] = c.field || ""; });

    // Pre-select a confidently matched submitter, else create new.
    const strong = (payload.submitter_candidates || []).find((c) => c.is_strong);
    state.party.submitter = {
      mode: strong ? "existing" : "new",
      user_nr: strong ? strong.user_nr : null,
      picking: false,
      values: { ...payload.draft.submitter.values },
      browse: [],
      browseRan: false,
      query: "",
    };

    const invoiceStrong = (payload.invoice_candidates || []).find((c) => c.is_strong);
    state.party.invoice = {
      enabled: !payload.draft.same_invoice_address && !payload.draft.invoice.is_empty,
      mode: invoiceStrong ? "existing" : "new",
      user_nr: invoiceStrong ? invoiceStrong.user_nr : null,
      picking: false,
      values: { ...payload.draft.invoice.values },
      browse: [],
      browseRan: false,
      query: "",
    };

    state.project = {
      mode: "new",
      existing_project_nr: null,
      values: { ...payload.project_defaults },
      existing: payload.existing_projects || [],
      matches: payload.project_name_matches || [],
    };

    // Seed one group per distinct submitter material. Only an *exact*
    // lookup hit is applied automatically; a fuzzy suggestion is left for
    // the operator to confirm via the chips, because silently turning
    // "collagen" into "collagen user prep." would be a guess about lab
    // procedure, not a spelling correction.
    state.groups = {};
    // Step 1 starts at the "none" method: a sample either gets a real
    // pretreatment chosen here or has none, so "none" is the honest default.
    const noneMethod =
      (payload.method_options || []).find((m) => String(m).trim().toLowerCase() === "none") || "";
    // Type starts at "arch": most submitted samples are archaeological, so
    // the operator only changes the exceptions (standards, blanks, ...).
    const defaultType =
      (payload.lookup_options?.type || []).find(
        (t) => String(t).trim().toLowerCase() === DEFAULT_LAB_TYPE
      ) || "";
    groupKeys().forEach((key) => {
      const resolved = payload.lookup_resolutions?.material?.[key]?.resolved || "";
      state.groups[key] = {
        material: resolved,
        type: defaultType,
        fraction: "",
        steps: [noneMethod, "", "", "", ""],
      };
      payload.draft.samples.forEach((s) => {
        if (groupKeyFor(s) !== key) return;
        if (noneMethod && !s.values.step1_method) s.values.step1_method = noneMethod;
        if (defaultType && !s.values.lab_type) s.values.lab_type = defaultType;
      });
      // Keep the rows in step with the group card: whatever the card
      // shows is what the rows carry, so the "no lab material set"
      // warning can never contradict the visible dropdown.
      if (resolved) {
        payload.draft.samples.forEach((s) => {
          if (groupKeyFor(s) === key) s.values.lab_material = resolved;
        });
      }
    });

    renderReview();
  }

  /** Distinct submitter-material values, in first-seen order. */
  function groupKeys() {
    const keys = [];
    const seen = new Set();
    (state.draft?.samples || []).forEach((s) => {
      const raw = String(s.values.material || "").trim() || "(no material given)";
      if (!seen.has(raw)) { seen.add(raw); keys.push(raw); }
    });
    return keys;
  }

  const groupKeyFor = (sample) =>
    String(sample.values.material || "").trim() || "(no material given)";

  // -------------------------------------------------------------- step 2

  function renderReview() {
    const d = state.draft;
    $("[data-file-name]").textContent = d.file_name;
    $("[data-file-facts]").textContent =
      `sheet “${d.sheet_name}” · header row ${d.header_row} · ${d.sample_count} rows`;
    $("[data-invoice-enabled]").checked = state.party.invoice.enabled;
    renderParty("submitter");
    renderParty("invoice");
    renderProject();
    renderAlerts();
  }

  const PARTY_LABEL = { submitter: "submitter", invoice: "invoice recipient" };
  const EMPTY = '<span class="detail-empty">—</span>';
  const present = (value) => String(value ?? "").trim() !== "";

  const candidatesFor = (which) =>
    (which === "submitter"
      ? state.payload.submitter_candidates
      : state.payload.invoice_candidates) || [];

  /** The stored record currently chosen for this party, or null. */
  function selectedRecord(which) {
    const party = state.party[which];
    if (party.mode !== "existing" || !party.user_nr) return null;
    return (
      [...candidatesFor(which), ...(party.browse || [])].find((c) => c.user_nr === party.user_nr) ||
      null
    );
  }

  /**
   * Submitter / invoice picker.
   *
   * Left: the choices as one compact radio list: scored candidates, "pick
   * another" (a search over all submitters) and "create new". Right: what
   * that choice means. For a stored record, the sheet and the record side
   * by side with differences flagged, because a returning customer may
   * have moved or changed e-mail; for a new record, the editable fields.
   */
  function renderParty(which) {
    const host = $(`[data-${which}]`);
    const party = state.party[which];
    const candidates = candidatesFor(which);
    const parsed = which === "submitter" ? state.draft.submitter : state.draft.invoice;
    const note = $(`[data-${which}-note]`);

    if (which === "invoice" && !party.enabled) {
      note.textContent = "Otherwise the submitter is billed.";
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    note.textContent = candidates.length
      ? `${candidates.length} match${candidates.length === 1 ? "" : "es"} on file`
      : "no match on file";

    const choice = (value, checked, title, lines, extra = "") => `
      <label class="import-choice ${checked ? "is-selected" : ""}">
        <input type="radio" name="${which}-choice" value="${value}" ${checked ? "checked" : ""} />
        <span class="import-choice-body">
          <span class="import-choice-title">${title}</span>
          ${lines.filter(Boolean).map((l) => `<span class="import-choice-meta">${l}</span>`).join("")}
        </span>
      </label>${extra}`;

    const metaOf = (c) => esc([c.organisation, c.town].filter(Boolean).join(" · "));
    const candidateHtml = candidates
      .map((c) =>
        choice(
          c.user_nr,
          party.mode === "existing" && !party.picking && party.user_nr === c.user_nr,
          `${esc(c.display_name)} <span class="import-choice-id">#${c.user_nr}</span>` +
            (c.is_strong ? ' <span class="import-badge-strong">strong match</span>' : ""),
          [metaOf(c), c.reasons?.length ? `<em>${esc(c.reasons.join(", "))}</em>` : ""]
        )
      )
      .join("");

    let browseBlock = "";
    if (party.picking) {
      const results = (party.browse || [])
        .map((r) => {
          const checked = party.user_nr === r.user_nr;
          return `
            <label class="import-choice is-compact ${checked ? "is-selected" : ""}">
              <input type="radio" name="${which}-pick" value="${r.user_nr}" ${checked ? "checked" : ""} />
              <span class="import-choice-body">
                <span class="import-choice-title">${esc(r.display_name)} <span class="import-choice-id">#${r.user_nr}</span></span>
                <span class="import-choice-meta">${esc([r.organisation, r.town, r.email].filter(Boolean).join(" · ")) || EMPTY}</span>
              </span>
            </label>`;
        })
        .join("");
      browseBlock = `
        <div class="import-browse">
          <div class="import-browse-form">
            <input type="search" data-browse-input value="${esc(party.query)}"
                   placeholder="Name, organisation or institute" aria-label="Search submitters" />
            <button type="button" class="import-secondary" data-browse-go>Search</button>
          </div>
          <div class="import-browse-results">
            ${results || `<p class="import-empty">${party.browseRan ? "No submitter found." : "Search to list submitters."}</p>`}
          </div>
        </div>`;
    }

    const choices = `
      <div class="import-choices" role="radiogroup" aria-label="${esc(PARTY_LABEL[which])}">
        ${candidateHtml}
        ${choice("browse", !!party.picking, `Pick another ${esc(PARTY_LABEL[which])}…`, ["Search all submitters"], browseBlock)}
        ${choice("new", party.mode === "new", `Create a new ${esc(PARTY_LABEL[which])}`, ["From the sheet values, which you can edit"])}
      </div>`;

    let detail;
    if (party.mode === "new") {
      detail = renderContactForm(which, party.values);
    } else {
      const record = selectedRecord(which);
      detail = renderComparison(parsed, record);
    }

    host.innerHTML = `<div class="import-party-grid">${choices}<div class="import-party-detail">${detail}</div></div>`;

    const rerender = () => {
      renderParty(which);
      if (which === "submitter") refreshProjectsForSubmitter();
      renderAlerts();
    };
    host.querySelectorAll(`input[name='${which}-choice']`).forEach((input) => {
      input.addEventListener("change", () => {
        if (input.value === "new") {
          Object.assign(party, { mode: "new", user_nr: null, picking: false });
        } else if (input.value === "browse") {
          Object.assign(party, { mode: "existing", user_nr: null, picking: true });
        } else {
          Object.assign(party, { mode: "existing", user_nr: Number(input.value), picking: false });
        }
        rerender();
        if (input.value === "browse") root.querySelector(`[data-${which}] [data-browse-input]`)?.focus();
      });
    });
    host.querySelectorAll(`input[name='${which}-pick']`).forEach((input) => {
      input.addEventListener("change", () => {
        Object.assign(party, { mode: "existing", user_nr: Number(input.value) });
        rerender();
      });
    });

    const browseInput = host.querySelector("[data-browse-input]");
    const runBrowse = async () => {
      party.query = browseInput.value;
      try {
        const res = await fetch(`/samples/import/submitters?q=${encodeURIComponent(party.query)}`);
        const data = await res.json();
        party.browse = data.submitters || [];
        party.browseRan = true;
        renderParty(which);
        root.querySelector(`[data-${which}] [data-browse-input]`)?.focus();
      } catch (_e) {
        showError("Could not search submitters.");
      }
    };
    host.querySelector("[data-browse-go]")?.addEventListener("click", runBrowse);
    browseInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); runBrowse(); }
    });

    host.querySelectorAll("[data-contact-field]").forEach((input) => {
      input.addEventListener("input", () => {
        party.values[input.dataset.contactField] = input.value;
        renderAlerts();
      });
    });
  }

  /**
   * The sheet's contact block next to the chosen stored record. Each sheet
   * value carries its cell address; a record value that differs from what
   * the sheet says is flagged. The import never changes a stored record,
   * so a difference is for the operator to follow up on the submitter page.
   */
  function renderComparison(parsed, record) {
    const sheet = parsed?.values || {};
    const sources = parsed?.sources || {};
    const stored = record?.record || {};
    const labels = new Map((state.payload.contact_fields || []).map((f) => [f.key, f.label]));
    Object.keys(sheet).forEach((k) => { if (!labels.has(k)) labels.set(k, k.replace(/_/g, " ")); });
    const keys = [...labels.keys()].filter((k) => present(sheet[k]) || (record && present(stored[k])));
    if (!keys.length) {
      return `<p class="import-empty">The sheet gives no contact details here${record ? ", and the record has none" : ""}.</p>`;
    }
    const norm = (v) => String(v ?? "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
    let differences = 0;
    const rows = keys
      .map((k) => {
        const fromSheet = sheet[k];
        const fromRecord = stored[k];
        const differs = !!record && present(fromSheet) && norm(fromSheet) !== norm(fromRecord);
        if (differs) differences += 1;
        const cell = sources[k] ? ` <span class="import-cell-ref">${esc(sources[k])}</span>` : "";
        return `
          <tr class="${differs ? "is-diff" : ""}">
            <th scope="row">${esc(labels.get(k))}</th>
            <td>${present(fromSheet) ? esc(fromSheet) + cell : EMPTY}</td>
            ${record
              ? `<td>${differs ? '<span class="import-diff-mark" title="Differs from the sheet">≠</span>' : ""}${present(fromRecord) ? esc(fromRecord) : EMPTY}</td>`
              : ""}
          </tr>`;
      })
      .join("");
    const note = !record
      ? "Choose a record on the left to compare it with the sheet."
      : differences
        ? `${differences} field${differences === 1 ? " differs" : "s differ"} from the sheet. The import keeps the stored record as it is; update it on the <a href="/submitters/${record.user_nr}" target="_blank" rel="noopener">submitter page</a> if the customer's details changed.`
        : "The stored record matches the sheet.";
    return `
      <div class="table-wrap import-compare-wrap">
        <table class="import-compare" data-table-plain>
          <thead><tr><th>Field</th><th>From the sheet</th>${record ? `<th>Record #${record.user_nr}</th>` : ""}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="import-hint ${differences ? "is-warning" : ""}">${note}</p>`;
  }

  /** Editable field set shown when creating a NEW submitter/invoice record. */
  function renderContactForm(which, values) {
    const fields = state.payload.contact_fields || [];
    const body = fields
      .map((f) => {
        const value = values[f.key] ?? "";
        const id = `import-${which}-${f.key}`;
        let control;
        if (f.kind === "textarea") {
          control = `<textarea id="${id}" data-contact-field="${f.key}" rows="2">${esc(value)}</textarea>`;
        } else if (f.kind === "select") {
          control = `<select id="${id}" data-contact-field="${f.key}" data-no-searchable>${optionList(
            f.options.map((o) => o.value), value, "—"
          )}</select>`;
        } else {
          control = `<input id="${id}" type="${f.kind === "email" ? "email" : "text"}"
                            data-contact-field="${f.key}" value="${esc(value)}" />`;
        }
        return `<div class="import-field ${f.kind === "textarea" ? "is-full" : ""}">
                  <label for="${id}">${esc(f.label)}</label>${control}
                </div>`;
      })
      .join("");
    return `
      <p class="import-hint">Saved as a new record, from the sheet's values. Salutation, title, language and comment are not in the sheet; language picks the e-mail template (blank = German).</p>
      <div class="import-form-grid">${body}</div>`;
  }

  /** Reload the existing-project list when the submitter selection changes. */
  async function refreshProjectsForSubmitter() {
    const party = state.party.submitter;
    if (party.mode !== "existing" || !party.user_nr) {
      state.project.existing = [];
      state.project.matches = [];
      state.project.mode = "new";
      state.project.existing_project_nr = null;
      renderProject();
      return;
    }
    try {
      const name = encodeURIComponent(state.project.values.project || "");
      const res = await fetch(
        `/samples/import/projects?user_nr=${party.user_nr}&name=${name}`
      );
      const data = await res.json();
      state.project.existing = data.projects || [];
      state.project.matches = matchProjectNames(
        state.project.values.project || "", state.project.existing
      );
      state.payload.project_variant_suggestion = data.variant_suggestion;
      renderProject();
      renderAlerts();
    } catch (_e) {
      /* non-fatal: the operator can still create a new project */
    }
  }

  /**
   * `<name>_<Month>_<Year>` for a follow-up batch.
   *
   * Computed from the name currently in the field rather than reusing
   * the server's parse-time suggestion, which would go stale the moment
   * the operator edits the project name.
   */
  function variantName(name) {
    const base = String(name || "").trim();
    if (!base) return "";
    const now = new Date();
    const suffix = `_${now.toLocaleString("en-US", { month: "long" })}_${now.getFullYear()}`;
    return base.endsWith(suffix) ? base : base + suffix;
  }

  const normalize = (s) =>
    String(s || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, " ").trim();

  function matchProjectNames(name, projects) {
    const key = normalize(name);
    if (!key) return [];
    return projects
      .map((p) => {
        const other = normalize(p.project);
        if (!other) return null;
        if (other === key) return { ...p, match: "exact" };
        if (other.startsWith(key) || key.startsWith(other)) return { ...p, match: "similar" };
        return null;
      })
      .filter(Boolean);
  }

  const PROJECT_SELECTS = [
    { key: "project_type", label: "Project type" },
    { key: "research", label: "Research" },
    { key: "report_type", label: "Report type" },
    { key: "supervisor", label: "Supervisor" },
  ];
  const PROJECT_CHECKS = [
    { key: "free_of_charge", label: "Free of charge" },
    { key: "return_to_sender", label: "Return samples to sender" },
    { key: "prep_return_to_sender", label: "Return preparations to sender" },
  ];

  /**
   * The duplicate-project prompt and the suggested-name hint.
   *
   * Rendered into their own containers so they can refresh on every
   * keystroke in the project-name field without re-rendering (and
   * therefore blurring) the inputs around them.
   */
  function renderDuplicatePrompt() {
    const p = state.project;
    const host = $("[data-project-duplicate]");
    const hint = $("[data-project-name-hint]");
    if (!host || !hint) return;

    let duplicateHtml = "";
    if (p.matches.length) {
      const rows = p.matches
        .map((m) => {
          const checked = p.mode === "existing" && p.existing_project_nr === m.project_nr;
          return `
            <label class="import-choice ${checked ? "is-selected" : ""}">
              <input type="radio" name="project-mode" value="existing:${m.project_nr}" ${checked ? "checked" : ""} />
              <span class="import-choice-body">
                <span class="import-choice-title">Add to project #${m.project_nr}
                  ${m.match === "exact" ? '<span class="import-badge-strong">same name</span>' : ""}</span>
                <span class="import-choice-meta">${esc(m.project)}${m.status ? " · " + esc(m.status) : ""}${m.in_date ? " · in " + esc(m.in_date) : ""}</span>
              </span>
            </label>`;
        })
        .join("");
      const newChecked = p.mode === "new";
      duplicateHtml = `
        <div class="import-duplicate">
          <p class="import-duplicate-title">This submitter already has a project with this name.</p>
          <div class="import-choices is-row">
            ${rows}
            <label class="import-choice ${newChecked ? "is-selected" : ""}">
              <input type="radio" name="project-mode" value="new" ${newChecked ? "checked" : ""} />
              <span class="import-choice-body">
                <span class="import-choice-title">Create a separate project</span>
                <span class="import-choice-meta">with the name below</span>
              </span>
            </label>
          </div>
        </div>`;
    }
    host.innerHTML = duplicateHtml;
    host.hidden = !duplicateHtml;

    // The lab's `<name>_<Month>_<Year>` convention, offered as one click
    // and never applied on its own.
    const suggestion = p.mode === "new" ? variantName(p.values.project) : "";
    hint.innerHTML =
      suggestion && suggestion !== String(p.values.project || "").trim()
        ? `Suggested: <span class="import-hint-value">${esc(suggestion)}</span>
           <button type="button" class="import-link" data-use-variant>use it</button>`
        : "";

    host.querySelectorAll("input[name='project-mode']").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.value === "new") {
          p.mode = "new"; p.existing_project_nr = null;
        } else {
          p.mode = "existing";
          p.existing_project_nr = Number(input.value.split(":")[1]);
        }
        renderProject();
        renderAlerts();
      });
    });
    hint.querySelector("[data-use-variant]")?.addEventListener("click", () => {
      p.values.project = variantName(p.values.project) || p.values.project;
      p.matches = matchProjectNames(p.values.project, p.existing);
      renderProject();
      renderAlerts();
    });
  }

  function renderProject() {
    const p = state.project;
    const opts = state.payload.project_options;
    const sub = state.party.submitter;

    $("[data-project-note]").textContent =
      p.mode === "existing"
        ? `adding to project #${p.existing_project_nr}; its settings stay as they are`
        : sub.mode === "existing" && sub.user_nr
          ? `new project for submitter #${sub.user_nr}`
          : sub.mode === "new"
            ? "new project for the new submitter"
            : "new project";

    // When appending, project settings belong to the existing project.
    const off = p.mode === "existing" ? "disabled" : "";
    const value = (key) => esc(p.values[key] ?? "");
    const field = (key, label, control, cls = "") => `
      <div class="import-field ${cls}">
        <label for="import-project-${key}">${esc(label)}</label>${control}
      </div>`;
    const input = (key, type) =>
      `<input id="import-project-${key}" type="${type}" data-project-field="${key}" value="${value(key)}" ${off} />`;
    const select = (key) =>
      `<select id="import-project-${key}" data-project-field="${key}" ${off}>
         ${optionList(opts[key] || [], p.values[key] ?? "", "—")}
       </select>`;
    const priority = `
      <select id="import-project-priority" data-project-field="priority" data-no-searchable ${off}>
        ${(opts.priority || [])
          .map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(p.values.priority) ? "selected" : ""}>${esc(o.label)}</option>`)
          .join("")}
      </select>`;
    const checks = PROJECT_CHECKS.map(
      (f) => `
        <label class="import-inline-check">
          <input type="checkbox" data-project-check="${f.key}" ${p.values[f.key] ? "checked" : ""} ${off} />
          ${esc(f.label)}
        </label>`
    ).join("");

    $("[data-project]").innerHTML = `
      <div data-project-duplicate hidden></div>
      <div class="import-form-grid is-project">
        <div class="import-field is-wide">
          <label for="import-project-project">Project name</label>
          ${input("project", "text")}
          <p class="import-hint" data-project-name-hint></p>
        </div>
        ${field("in_date", "In date", input("in_date", "date"))}
        ${field("desired_date", "Desired date", input("desired_date", "date"))}
        ${PROJECT_SELECTS.map((f) => field(f.key, f.label, select(f.key))).join("")}
        ${field("priority", "Priority", priority)}
        <div class="import-checks">${checks}</div>
        ${field("project_comment", "Comment",
          `<textarea id="import-project-project_comment" data-project-field="project_comment" rows="2" ${off}>${value("project_comment")}</textarea>`,
          "is-full")}
      </div>`;

    const host = $("[data-project]");
    renderDuplicatePrompt();
    host.querySelectorAll("[data-project-field]").forEach((el) => {
      el.addEventListener("input", () => {
        p.values[el.dataset.projectField] = el.value;
        if (el.dataset.projectField === "project") {
          // Recompute and refresh only the prompt, so the field the
          // operator is typing in keeps focus and cursor position.
          p.matches = matchProjectNames(el.value, p.existing);
          renderDuplicatePrompt();
        }
        renderAlerts();
      });
      el.addEventListener("change", () => {
        p.values[el.dataset.projectField] = el.value;
      });
    });
    host.querySelectorAll("[data-project-check]").forEach((box) => {
      box.addEventListener("change", () => {
        p.values[box.dataset.projectCheck] = box.checked;
      });
    });
  }

  // ---- review-stage validation ----------------------------------------

  /** The action bar's status line: "Ready · …", or what blocks the step. */
  function footStatus(el, blocked, text) {
    el.innerHTML = blocked
      ? '<span class="is-blocked">Fix the items above to continue</span>'
      : `<strong>Ready</strong> · ${esc(text)}`;
  }

  function reviewProblems() {
    const problems = [];
    const sub = state.party.submitter;
    if (sub.mode === "new" && !String(sub.values.last_name || "").trim()) {
      problems.push("The new submitter needs a last name.");
    }
    if (sub.mode === "existing" && !sub.user_nr) {
      problems.push("Choose an existing submitter, or switch to creating a new one.");
    }
    const inv = state.party.invoice;
    if (inv.enabled && inv.mode === "new" && !String(inv.values.last_name || "").trim()) {
      problems.push("The new invoice recipient needs a last name.");
    }
    if (inv.enabled && inv.mode === "existing" && !inv.user_nr) {
      problems.push("Choose an existing invoice recipient, or switch to creating a new one.");
    }
    if (state.project.mode === "new" && !String(state.project.values.project || "").trim()) {
      problems.push("Enter a project name.");
    }
    if (state.project.mode === "existing" && !state.project.existing_project_nr) {
      problems.push("Choose the existing project to add these samples to.");
    }
    return problems;
  }

  function renderAlerts() {
    const problems = reviewProblems();
    const notices = (state.draft.issues || []).filter(
      (i) => i.severity !== "error" && !String(i.target).startsWith("project")
    );
    const items = [
      ...problems.map((m) => ({ severity: "error", message: m })),
      ...notices.map((i) => ({ severity: i.severity, message: i.message })),
    ];
    const section = $("[data-alerts]");
    if (!items.length) {
      section.hidden = true;
    } else {
      section.hidden = false;
      section.classList.toggle("has-errors", problems.length > 0);
      $("[data-alerts-title]").textContent = problems.length
        ? `${problems.length === 1 ? "One thing" : `${problems.length} things`} to fix`
        : items.length === 1 ? "Note" : "Notes";
      $("[data-alert-list]").innerHTML = items
        .map((i) => `<li class="is-${i.severity}">${esc(i.message)}</li>`)
        .join("");
    }
    $("[data-goto-lab]").disabled = problems.length > 0;
    const sub = state.party.submitter;
    footStatus(
      $("[data-review-status]"),
      problems.length,
      [
        sub.mode === "existing" ? `submitter #${sub.user_nr}` : "new submitter",
        state.project.mode === "existing" ? `add to project #${state.project.existing_project_nr}` : "new project",
      ].join(" · ")
    );
  }

  // -------------------------------------------------------------- step 3

  function renderLabStage() {
    renderGroups();
    renderMapping();
    renderSamples();
    renderBulkBar();
    renderLabAlerts();
  }

  const includedSamples = () => state.draft.samples.filter((s) => s.include);

  /**
   * Group rows: one per distinct submitter material.
   *
   * The customer's wording ("collagen") heads the row and the lab's own
   * vocabulary is chosen beside it. A material suggestion from the
   * server's fuzzy match sits under the select, so the usual case is one
   * confirming click.
   */
  function renderGroups() {
    const opts = state.payload.lookup_options;
    const methods = state.payload.method_options || [];
    const suggestions = state.payload.group_suggestions || {};

    const rowsHtml = groupKeys()
      .map((key) => {
        const rows = state.draft.samples.filter((s) => s.include && groupKeyFor(s) === key).length;
        if (!rows) return "";
        const g = state.groups[key] || { steps: [] };
        // Quick picks: a quiet "a · b" text line, not buttons in boxes.
        // The value already selected is left out.
        const picks = (field) =>
          (suggestions[key]?.[field] || [])
            .filter((v) => v !== g[field])
            .slice(0, 3)
            .map(
              (v) =>
                `<button type="button" class="import-suggest" data-group-suggest="${esc(key)}"
                         data-group-field="${field}" data-group-value="${esc(v)}"
                         title="Set ${esc(field)} to ${esc(v)}">${esc(v)}</button>`
            )
            .join("");
        const lookups = LOOKUP_FIELDS.map((field) => {
          const label = state.payload.field_labels.sample[field] || field;
          const quick = picks(field);
          return `
            <td>
              <select class="${g[field] ? "" : "is-unset"}" data-group-select="${esc(key)}"
                      data-group-field="${field}" aria-label="${esc(label)} for “${esc(key)}”">
                ${optionList(opts[field] || [], g[field] || "", "— undefined —")}
              </select>
              ${quick ? `<div class="import-suggests">${quick}</div>` : ""}
            </td>`;
        }).join("");
        const steps = g.steps
          .map(
            (value, index) => `
              <td>
                <select data-group-step="${esc(key)}" data-step-index="${index}"
                        aria-label="Preparation step ${index + 1} for “${esc(key)}”">
                  ${optionList(methods, value || "", "—")}
                </select>
              </td>`
          )
          .join("");
        return `
          <tr>
            <th scope="row" class="import-group-name">“${esc(key)}”<span>${rows} row${rows === 1 ? "" : "s"}</span></th>
            ${lookups}${steps}
          </tr>`;
      })
      .join("");
    const host = $("[data-groups]");
    host.innerHTML =
      rowsHtml ||
      `<tr><td class="table-empty-row" colspan="9">No rows are included. Tick <strong>Import</strong> on a row below to bring it back.</td></tr>`;

    host.querySelectorAll("[data-group-select]").forEach((sel) => {
      sel.addEventListener("change", () => {
        applyGroupValue(sel.dataset.groupSelect, sel.dataset.groupField, sel.value);
      });
    });
    host.querySelectorAll("[data-group-suggest]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyGroupValue(btn.dataset.groupSuggest, btn.dataset.groupField, btn.dataset.groupValue);
      });
    });
    host.querySelectorAll("[data-group-step]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const key = sel.dataset.groupStep;
        const index = Number(sel.dataset.stepIndex);
        state.groups[key].steps[index] = sel.value;
        state.draft.samples.forEach((s) => {
          if (s.include && groupKeyFor(s) === key) {
            s.values[`step${index + 1}_method`] = sel.value;
          }
        });
        renderGroups();
        renderSamples();
        renderLabAlerts();
      });
    });
  }

  /** Write a group's lab value onto every row in that group. */
  function applyGroupValue(key, field, value) {
    state.groups[key] = state.groups[key] || { steps: ["", "", "", "", ""] };
    state.groups[key][field] = value;
    state.draft.samples.forEach((s) => {
      if (s.include && groupKeyFor(s) === key) s.values[`lab_${field}`] = value;
    });
    renderGroups();
    renderSamples();
    renderLabAlerts();
  }

  // ---- column mapping --------------------------------------------------

  function renderMapping() {
    const fields = state.payload.mappable_fields;
    const columns = state.draft.columns;
    const mapped = columns.filter((c) => state.mapping[c.column_letter]).length;
    $("[data-mapping-count]").textContent = `· ${mapped} of ${columns.length} mapped`;
    $("[data-mapping-grid]").innerHTML = columns
      .map((column) => {
        const current = state.mapping[column.column_letter] || "";
        return `
          <label class="import-map-row ${current ? "" : "is-unmapped"}">
            <span class="import-map-col">${column.column_letter}</span>
            <span class="import-map-header" title="${esc(column.header_text)}">
              ${esc(column.header_text || "(no heading)")}</span>
            <select data-map-column="${column.column_letter}">
              ${optionList(fields.map((f) => f.value), current, "— not imported —")}
            </select>
          </label>`;
      })
      .join("");
    // Label the options properly (optionList only knows raw values).
    $("[data-mapping-grid]").querySelectorAll("[data-map-column]").forEach((select) => {
      Array.from(select.options).forEach((opt) => {
        const match = fields.find((f) => f.value === opt.value);
        if (match) opt.textContent = match.label;
      });
      select.addEventListener("change", () =>
        remapColumn(select.dataset.mapColumn, select.value)
      );
    });
  }

  function remapColumn(letter, newField) {
    const column = state.draft.columns.find((c) => c.column_letter === letter);
    if (!column) return;
    const oldField = state.mapping[letter] || "";
    const header = column.header_text || letter;

    if (newField) {
      Object.entries(state.mapping).forEach(([otherLetter, field]) => {
        if (otherLetter !== letter && field === newField) {
          remapColumn(otherLetter, "");
          const sel = root.querySelector(`[data-map-column="${otherLetter}"]`);
          if (sel) sel.value = "";
        }
      });
    }

    state.draft.samples.forEach((sample) => {
      let carried;
      if (oldField) { carried = sample.values[oldField]; delete sample.values[oldField]; }
      else { carried = sample.extras[header]; delete sample.extras[header]; }
      if (carried === undefined || carried === "") return;
      if (newField) {
        sample.values[newField] = newField === "weight" ? parseWeight(carried) : String(carried);
      } else {
        sample.extras[header] = String(carried);
      }
    });

    state.mapping[letter] = newField;
    column.field = newField || null;
    renderMapping();
    renderGroups();
    renderSamples();
    renderLabAlerts();
  }

  function parseWeight(value) {
    if (typeof value === "number") return value;
    const cleaned = String(value).replace(/[^0-9.,\-]/g, "").replace(",", ".");
    const parsed = Number.parseFloat(cleaned);
    return Number.isFinite(parsed) ? parsed : "";
  }

  // ---- sample table ----------------------------------------------------

  /** Every mapped sheet column, in the canonical field order. */
  function mappedSheetFields() {
    const order = state.payload.mappable_fields.map((f) => f.value);
    const used = new Set(Object.values(state.mapping).filter(Boolean));
    return order.filter((f) => used.has(f));
  }

  /** True when at least one row has a value in this sheet column. */
  function hasEntries(field) {
    return state.draft.samples.some((sample) => {
      const value = sample.values[field];
      return value !== undefined && value !== null && String(value).trim() !== "";
    });
  }

  /**
   * Whether a sheet column is shown: the operator's pill click if there
   * was one, else shown exactly when it has entries — data is never
   * hidden by default, empty columns are.
   */
  function isColumnShown(field) {
    const chosen = state.columnVisibility.get(field);
    return chosen === undefined ? hasEntries(field) : chosen;
  }

  /** The mapped sheet columns the table actually shows. */
  function sheetFields() {
    return mappedSheetFields().filter(isColumnShown);
  }

  const LAB_COLUMNS = LOOKUP_FIELDS.map((f) => `lab_${f}`);
  const STEP_COLUMNS = ["step1_method", "step2_method", "step3_method", "step4_method", "step5_method"];

  /** Chip row for showing/hiding the sheet columns of the lab table. */
  function renderColumnToggles() {
    const labels = state.payload.field_labels.sample;
    const host = $("[data-column-chips]");
    const fields = mappedSheetFields();
    host.innerHTML = fields
      .map((field) => {
        const shown = isColumnShown(field);
        return `<button type="button" class="import-column-chip ${shown ? "is-on" : ""}"
                        data-column-toggle="${esc(field)}" aria-pressed="${shown}">
                  ${esc(labels[field] || field)}
                </button>`;
      })
      .join("");
    host.querySelectorAll("[data-column-toggle]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const field = chip.dataset.columnToggle;
        state.columnVisibility.set(field, !isColumnShown(field));
        renderSamples();
      });
    });
  }

  function renderSamples() {
    renderColumnToggles();
    const sheet = sheetFields();
    const labels = state.payload.field_labels.sample;
    const total = state.draft.samples.length;
    const included = includedSamples().length;
    $("[data-sample-count]").textContent =
      included === total ? `all ${total} will be imported` : `${included} of ${total} will be imported`;

    const allSelected = state.selection.size === total && total > 0;
    $("[data-sample-head]").innerHTML =
      "<tr>" +
      `<th class="import-col-check"><input type="checkbox" data-select-all aria-label="Select all rows" ${allSelected ? "checked" : ""} /></th>` +
      '<th class="import-col-include">Import</th>' +
      sheet.map((f) => `<th>${esc(labels[f] || f)}</th>`).join("") +
      LOOKUP_FIELDS.map((f) => `<th class="import-col-lab">Lab ${esc((labels[f] || f).toLowerCase())}</th>`).join("") +
      STEP_COLUMNS.map((_, i) => `<th class="import-col-step">Prep ${i + 1}</th>`).join("") +
      "</tr>";
    const selectAll = $("[data-select-all]");
    selectAll.indeterminate = state.selection.size > 0 && !allSelected;

    const opts = state.payload.lookup_options;
    const methods = state.payload.method_options || [];
    // Each sheet column is as wide as its longest value (within reason):
    // an input has no content width of its own, so `size` sets it.
    const widths = Object.fromEntries(
      sheet.map((field) => [
        field,
        Math.min(
          24,
          Math.max(4, ...state.draft.samples.map((s) => String(s.values[field] ?? "").length + 1))
        ),
      ])
    );

    $("[data-sample-body]").innerHTML = state.draft.samples
      .map((sample, index) => {
        const sheetCells = sheet
          .map(
            (field) =>
              `<td class="import-col-sheet"><input size="${widths[field]}" data-cell-row="${index}" data-cell-field="${field}"
                          aria-label="${esc(labels[field] || field)}, row ${sample.row_number}"
                          value="${esc(sample.values[field] ?? "")}" /></td>`
          )
          .join("");
        const labCells = LOOKUP_FIELDS.map((field) => {
          const value = sample.values[`lab_${field}`] || "";
          return `<td class="import-col-lab">
                    <select class="${value ? "" : "is-unset"}" data-cell-row="${index}" data-lab-field="${field}"
                            aria-label="Lab ${esc(labels[field] || field)}, row ${sample.row_number}">
                      ${optionList(opts[field] || [], value, "— undefined —")}
                    </select></td>`;
        }).join("");
        const stepCells = STEP_COLUMNS.map(
          (col, i) => `<td class="import-col-step">
              <select data-cell-row="${index}" data-step-field="${col}"
                      aria-label="Preparation step ${i + 1}, row ${sample.row_number}">
                ${optionList(methods, sample.values[col] || "", "—")}
              </select></td>`
        ).join("");
        const errors = (sample.issues || []).filter((i) => i.severity === "error");
        const noLabel = sample.include && !String(sample.values.user_label || "").trim();
        const selected = state.selection.has(index);
        return `
          <tr class="${sample.include ? "" : "is-excluded"} ${errors.length || noLabel ? "has-error" : ""} ${selected ? "is-selected-row" : ""}">
            <td class="import-col-check">
              <input type="checkbox" data-select-row="${index}" ${selected ? "checked" : ""}
                     aria-label="Select row ${sample.row_number}" />
            </td>
            <td class="import-col-include">
              <input type="checkbox" role="switch" class="import-switch" data-include-row="${index}"
                     ${sample.include ? "checked" : ""} aria-label="Import row ${sample.row_number}"
                     title="${sample.include ? "Imported; click to leave this row out" : "Left out; click to import this row"}" />
            </td>
            ${sheetCells}${labCells}${stepCells}
          </tr>`;
      })
      .join("");

    const body = $("[data-sample-body]");
    body.querySelectorAll("[data-include-row]").forEach((box) => {
      box.addEventListener("change", () => {
        state.draft.samples[Number(box.dataset.includeRow)].include = box.checked;
        renderSamples(); renderGroups(); renderLabAlerts();
      });
    });
    body.querySelectorAll("[data-select-row]").forEach((box) => {
      box.addEventListener("change", () => {
        const i = Number(box.dataset.selectRow);
        if (box.checked) state.selection.add(i); else state.selection.delete(i);
        renderSamples(); renderBulkBar();
      });
    });
    body.querySelectorAll("[data-cell-field]").forEach((input) => {
      input.addEventListener("change", () => {
        const sample = state.draft.samples[Number(input.dataset.cellRow)];
        const field = input.dataset.cellField;
        sample.values[field] = field === "weight" ? parseWeight(input.value) : input.value.trim();
        renderSamples(); renderGroups(); renderLabAlerts();
      });
    });
    body.querySelectorAll("[data-lab-field]").forEach((sel) => {
      sel.addEventListener("change", () => {
        state.draft.samples[Number(sel.dataset.cellRow)].values[`lab_${sel.dataset.labField}`] = sel.value;
        renderSamples(); renderLabAlerts();
      });
    });
    body.querySelectorAll("[data-step-field]").forEach((sel) => {
      sel.addEventListener("change", () => {
        state.draft.samples[Number(sel.dataset.cellRow)].values[sel.dataset.stepField] = sel.value;
        renderSamples();
      });
    });
    $("[data-select-all]")?.addEventListener("change", (e) => {
      state.selection = e.target.checked
        ? new Set(state.draft.samples.map((_, i) => i))
        : new Set();
      renderSamples(); renderBulkBar();
    });
  }

  // ---- tick-and-apply toolbar -----------------------------------------

  function renderBulkBar() {
    const bar = $("[data-bulkbar]");
    if (!state.selection.size) { bar.hidden = true; return; }
    bar.hidden = false;
    $("[data-bulk-count]").textContent = `${state.selection.size} selected`;

    const fieldSelect = $("[data-bulk-field]");
    if (!fieldSelect.options.length) {
      const labels = state.payload.field_labels.sample;
      fieldSelect.innerHTML = LOOKUP_FIELDS.map(
        (f) => `<option value="lab_${f}">Lab ${esc((labels[f] || f).toLowerCase())}</option>`
      ).concat(
        STEP_COLUMNS.map((c, i) => `<option value="${c}">Prep ${i + 1}</option>`)
      ).join("");
      fieldSelect.addEventListener("change", renderBulkValues);
    }
    renderBulkValues();
  }

  function renderBulkValues() {
    const field = $("[data-bulk-field]").value;
    const valueSelect = $("[data-bulk-value]");
    const options = field.startsWith("lab_")
      ? state.payload.lookup_options[field.slice(4)] || []
      : state.payload.method_options || [];
    valueSelect.innerHTML = optionList(options, "", "— choose a value —");
  }

  $("[data-bulk-apply]").addEventListener("click", () => {
    const field = $("[data-bulk-field]").value;
    const value = $("[data-bulk-value]").value;
    if (!field) return;
    state.selection.forEach((index) => {
      state.draft.samples[index].values[field] = value;
    });
    renderSamples(); renderGroups(); renderLabAlerts();
  });
  const includeSelected = (include) => {
    state.selection.forEach((index) => { state.draft.samples[index].include = include; });
    renderSamples(); renderGroups(); renderLabAlerts();
  };
  $("[data-bulk-exclude]").addEventListener("click", () => includeSelected(false));
  $("[data-bulk-include]").addEventListener("click", () => includeSelected(true));
  $("[data-bulk-clear]").addEventListener("click", () => {
    state.selection = new Set();
    renderSamples(); renderBulkBar();
  });

  // ---- lab-stage validation -------------------------------------------

  function labProblems() {
    const problems = [];
    if (!Object.values(state.mapping).includes("user_label")) {
      problems.push("Map one column to “Sample Label”.");
    }
    if (!includedSamples().length) problems.push("Select at least one sample row.");
    // The table shows no sheet row numbers, so these rows are marked red
    // there instead of being named by number.
    const unnamed = includedSamples().filter((s) => !String(s.values.user_label || "").trim()).length;
    if (unnamed) {
      problems.push(
        `${unnamed === 1 ? "One row has" : `${unnamed} rows have`} no sample label (marked red below): fill it in or switch the row off.`
      );
    }
    return problems;
  }

  function labNotices() {
    const notices = [];
    const missing = includedSamples().filter((s) => !s.values.lab_material);
    if (missing.length) {
      notices.push(
        `${missing.length} row(s) have no lab material set — they will be saved as “undefined”.`
      );
    }
    const noType = includedSamples().filter((s) => !s.values.lab_type);
    if (noType.length) {
      notices.push(`${noType.length} row(s) have no sample type set — they will be saved as “undefined”.`);
    }
    const noSteps = includedSamples().filter(
      (s) => !STEP_COLUMNS.some((c) => s.values[c])
    );
    if (noSteps.length) {
      notices.push(`${noSteps.length} row(s) have no preparation steps assigned.`);
    }
    // Mirrors `needs_no_preparation()` in commit.py: step 1 = "none" and
    // no real method in steps 2-5.
    const isNone = (v) => String(v || "").trim().toLowerCase() === "none";
    const noPrep = includedSamples().filter(
      (s) =>
        isNone(s.values[STEP_COLUMNS[0]]) &&
        STEP_COLUMNS.slice(1).every((c) => !s.values[c] || isNone(s.values[c]))
    );
    if (noPrep.length) {
      notices.push(
        `${noPrep.length} row(s) need no preparation (step 1 is “none”) — their Prep End is set to today on import.`
      );
    }
    return notices;
  }

  function renderLabAlerts() {
    const problems = labProblems();
    const notices = labNotices();
    const items = [
      ...problems.map((m) => ({ severity: "error", message: m })),
      ...notices.map((m) => ({ severity: "warning", message: m })),
    ];
    const section = $("[data-lab-alerts]");
    if (!items.length) section.hidden = true;
    else {
      section.hidden = false;
      section.classList.toggle("has-errors", problems.length > 0);
      $("[data-lab-alerts-title]").textContent = problems.length
        ? `${problems.length === 1 ? "One thing" : `${problems.length} things`} to fix before importing`
        : items.length === 1 ? "Note" : "Notes";
      $("[data-lab-alert-list]").innerHTML = items
        .map((i) => `<li class="is-${i.severity}">${esc(i.message)}</li>`)
        .join("");
    }
    $("[data-commit]").disabled = problems.length > 0 || state.committing;
    $("[data-goto-extras]").disabled = problems.length > 0;
    const count = includedSamples().length;
    const noMaterial = includedSamples().filter((s) => !s.values.lab_material).length;
    footStatus(
      $("[data-lab-status]"),
      problems.length,
      `${count} sample${count === 1 ? "" : "s"}` + (noMaterial ? ` · ${noMaterial} without lab material` : "")
    );
  }

  // ------------------------------------------------- step 4: extra analyses

  /** The analyses requested beyond C14 dating; set by hand, not by the sheet. */
  const EXTRA_FLAGS = [
    { key: "cn_isotop_a", label: "C/N isotope analysis", short: "C/N isotope" },
    { key: "dendro_a", label: "Dendro analysis", short: "Dendro" },
  ];

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };

  /**
   * One compact table: row, label, lab material, and a checkbox column per
   * analysis. Each column head carries its own count and All / None, so
   * the set-all controls sit where they act.
   */
  function renderExtrasStage() {
    const rows = includedSamples();

    const headRow = el("tr");
    headRow.append(
      el("th", "import-col-row", "Row"),
      el("th", "", "Sample Label"),
      el("th", "", "Lab material")
    );
    EXTRA_FLAGS.forEach(({ key, short }) => {
      const th = el("th", "import-col-flag");
      const on = rows.filter((r) => r.values[key]).length;
      const tools = el("span", "import-flag-tools");
      const all = el("button", "import-link", "All");
      all.type = "button";
      all.setAttribute("aria-label", `Tick ${short} for every sample`);
      all.addEventListener("click", () => setAllFlags(key, true));
      const none = el("button", "import-link", "None");
      none.type = "button";
      none.setAttribute("aria-label", `Clear ${short} for every sample`);
      none.addEventListener("click", () => setAllFlags(key, false));
      tools.append(el("span", "", `${on} of ${rows.length}`), all, none);
      th.append(el("span", "import-flag-name", short), tools);
      headRow.append(th);
    });
    $("[data-extras-head]").replaceChildren(headRow);

    $("[data-extras-body]").replaceChildren(
      ...rows.map((sample) => {
        const tr = el("tr");
        const material = sample.values.lab_material;
        const materialCell = el("td");
        if (material) materialCell.textContent = material;
        else materialCell.append(el("span", "detail-empty", "undefined"));
        tr.append(
          el("td", "import-col-row", String(sample.row_number)),
          el("td", "", sample.values.user_label || "—"),
          materialCell
        );
        EXTRA_FLAGS.forEach(({ key, label }) => {
          const td = el("td", "import-col-flag");
          const box = el("input");
          box.type = "checkbox";
          box.checked = !!sample.values[key];
          box.setAttribute("aria-label", `${label}, row ${sample.row_number}`);
          box.addEventListener("change", () => {
            sample.values[key] = box.checked;
            renderExtrasStage();
          });
          td.append(box);
          tr.append(td);
        });
        return tr;
      })
    );

    const extras = EXTRA_FLAGS
      .map(({ key, short }) => [short, rows.filter((r) => r.values[key]).length])
      .filter(([, n]) => n)
      .map(([short, n]) => `${n} ${short}`);
    footStatus(
      $("[data-commit-status]"),
      0,
      `${rows.length} sample${rows.length === 1 ? "" : "s"} will be created` + (extras.length ? ` · ${extras.join(" · ")}` : "")
    );
  }

  function setAllFlags(key, value) {
    includedSamples().forEach((sample) => { sample.values[key] = value; });
    renderExtrasStage();
  }

  // -------------------------------------------------------------- commit

  function buildCommitPayload() {
    const sub = state.party.submitter;
    const inv = state.party.invoice;
    const p = state.project;
    // Every *mapped* column, not just the visible ones — hiding a column
    // in the table must never drop its values from the import.
    const sheet = mappedSheetFields();

    return {
      submitter: {
        user_nr: sub.mode === "existing" ? sub.user_nr : null,
        values: sub.values,
      },
      invoice: {
        enabled: inv.enabled,
        user_nr: inv.enabled && inv.mode === "existing" ? inv.user_nr : null,
        values: inv.values,
      },
      project: {
        existing_project_nr: p.mode === "existing" ? p.existing_project_nr : null,
        project: p.values.project,
        in_date: p.values.in_date,
        desired_date: p.values.desired_date,
        project_comment: p.values.project_comment,
        priority: p.values.priority,
        project_type: p.values.project_type,
        research: p.values.research,
        report_type: p.values.report_type,
        supervisor: p.values.supervisor,
        free_of_charge: !!p.values.free_of_charge,
        return_to_sender: !!p.values.return_to_sender,
        prep_return_to_sender: !!p.values.prep_return_to_sender,
      },
      samples: includedSamples().map((sample) => {
        const values = {};
        sheet.forEach((field) => {
          // The sheet's own material is the grouping key only; the lab
          // value below is what actually gets written.
          if (LOOKUP_FIELDS.includes(field)) return;
          const v = sample.values[field];
          if (v !== "" && v != null) values[field] = v;
        });
        LOOKUP_FIELDS.forEach((field) => {
          const v = sample.values[`lab_${field}`];
          if (v) values[field] = v;
        });
        STEP_COLUMNS.forEach((col) => {
          if (sample.values[col]) values[col] = sample.values[col];
        });
        EXTRA_FLAGS.forEach(({ key }) => { values[key] = sample.values[key] ? 1 : 0; });
        return { include: true, row_number: sample.row_number, values };
      }),
    };
  }

  /** "Name #nr" of the submitter / invoice recipient the commit will use. */
  function partySummary(which) {
    const party = state.party[which];
    if (party.mode === "existing") {
      const pool = [
        ...((which === "submitter" ? state.payload.submitter_candidates : state.payload.invoice_candidates) || []),
        ...(party.browse || []),
      ];
      const hit = pool.find((c) => c.user_nr === party.user_nr);
      return `${hit ? hit.display_name : "Submitter"} #${party.user_nr} (existing)`;
    }
    const v = party.values || {};
    const name = [v.last_name, v.first_name].filter(Boolean).join(", ");
    return `${name || "—"} (new record)`;
  }

  function projectSummary() {
    const p = state.project;
    if (p.mode === "existing") {
      const hit = (p.matches || []).find((m) => m.project_nr === p.existing_project_nr);
      return `Add to #${p.existing_project_nr}${hit ? ` “${hit.project}”` : ""}`;
    }
    return `“${p.values.project || "—"}” (new project)`;
  }

  /**
   * Ask before writing: the button is the wizard's last step and saves at
   * once, which operators did not expect. Resolves true only on "Yes".
   */
  function confirmCommit() {
    const dialog = root.querySelector("[data-commit-dialog]");
    if (!dialog?.showModal) return Promise.resolve(window.confirm("Import the samples now? This saves them to the database."));
    const rows = [
      ["Samples", `${includedSamples().length} of ${state.draft.samples.length} row(s)`],
      ["Submitter", partySummary("submitter")],
      ...(state.party.invoice.enabled ? [["Invoice to", partySummary("invoice")]] : []),
      ["Project", projectSummary()],
      ...EXTRA_FLAGS.map(({ key, label }) => [
        label, `${includedSamples().filter((r) => r.values[key]).length} sample(s)`,
      ]),
    ];
    const count = includedSamples().length;
    dialog.querySelector("[data-commit-title]").textContent =
      `Import ${count} sample${count === 1 ? "" : "s"} now?`;
    const summary = dialog.querySelector("[data-commit-summary]");
    summary.replaceChildren(
      ...rows.flatMap(([label, value]) => {
        const dt = document.createElement("dt"); dt.textContent = label;
        const dd = document.createElement("dd"); dd.textContent = value;
        return [dt, dd];
      })
    );
    dialog.returnValue = "";
    dialog.showModal();
    return new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
    });
  }

  $("[data-commit]").addEventListener("click", async () => {
    if (state.committing) return;
    if (!(await confirmCommit())) return;
    if (state.committing) return;
    state.committing = true;
    showError("");
    const button = $("[data-commit]");
    button.disabled = true;
    button.textContent = "Importing…";
    try {
      const response = await fetch("/samples/import/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildCommitPayload()),
      });
      const result = await response.json();
      if (!response.ok) {
        showError(result.detail || "The import could not be saved.", result.technical);
        return;
      }
      state.result = result;
      window.removeEventListener("beforeunload", guardUnload);
      renderDone(result);
      setStep("done");
      window.SAMSToast?.show(`Imported ${result.sample_count} sample(s).`, "success");
      loadEmailPreview(result);
    } catch (error) {
      showError("The import request failed. Nothing was saved — please try again.", {
        stage: "Sending the import (browser)", error_type: error?.name || "Error",
        message: error?.message || String(error),
        note: "The server answered with something that was not JSON, or did not answer at all; check the server log.",
      });
    } finally {
      state.committing = false;
      button.disabled = false;
      button.textContent = "Import samples…";
    }
  });

  // -------------------------------------------------------------- step 4

  function renderDone(result) {
    const nrs = result.sample_nrs || [];
    const sampleLink = (nr) => `<a href="/samples/${encodeURIComponent(nr)}">${esc(nr)}</a>`;
    const range = nrs.length
      ? nrs.length === 1
        ? sampleLink(nrs[0])
        : `${sampleLink(nrs[0])} – ${sampleLink(nrs[nrs.length - 1])}`
      : EMPTY;
    const count = result.sample_count;
    $("[data-done]").innerHTML = `
      <div class="import-done-line">
        <span class="import-done-mark" aria-hidden="true">✓</span>
        <h2>Imported ${count} sample${count === 1 ? "" : "s"}</h2>
        <div class="import-done-actions">
          <a class="import-primary" href="${esc(result.project_url)}">Open project</a>
          ${result.first_sample_url ? `<a class="import-secondary" href="${esc(result.first_sample_url)}">Open first sample</a>` : ""}
          <a class="import-ghost" href="/samples/import">Import another file</a>
        </div>
      </div>
      <dl class="import-done-facts">
        <div>
          <dt>Project</dt>
          <dd><a href="${esc(result.project_url)}">#${esc(result.project_nr)}</a>
            <span class="import-done-tag">${result.project_created ? "new" : "existing"}</span>
            <span class="import-done-meta">${esc(result.project_name)}</span></dd>
        </div>
        <div>
          <dt>Submitter</dt>
          <dd><a href="${esc(result.submitter_url)}">#${esc(result.user_nr)}</a>
            <span class="import-done-tag">${result.submitter_created ? "new" : "existing"}</span>
            <span class="import-done-meta">${esc(result.submitter_name)}</span></dd>
        </div>
        <div>
          <dt>Samples</dt>
          <dd>${range}
            <span class="import-done-meta">each with preparation #1 and target #1</span></dd>
        </div>
      </dl>`;
  }

  /**
   * Render the confirmation e-mail. Nothing is sent here — the operator
   * reviews (and may edit) the text, then explicitly clicks Send.
   */
  function fetchEmailPreview(result, templateCode) {
    return fetch("/samples/import/email/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_nr: result.user_nr,
        project_nr: result.project_nr,
        project_name: result.project_name,
        sample_nrs: result.sample_nrs,
        sample_labels: result.sample_labels,
        template: templateCode || null,
      }),
    });
  }

  async function loadEmailPreview(result) {
    const section = $("[data-email-section]");
    const host = $("[data-email]");
    section.hidden = false;
    host.innerHTML = `<p class="import-hint"><span class="import-spinner" aria-hidden="true"></span> Preparing the confirmation e-mail…</p>`;
    try {
      const res = await fetchEmailPreview(result, null);
      const data = await res.json();
      if (!res.ok) { host.innerHTML = `<p class="import-empty">${esc(data.detail || "No preview available.")}</p>`; return; }
      renderEmailForm(data, result);
    } catch (_e) {
      host.innerHTML = `<p class="import-empty">The e-mail preview could not be loaded. The import itself is complete.</p>`;
    }
  }

  /** One sentence on why this template was picked. */
  function templateReasonText(data) {
    const label = (data.templates || []).find((t) => t.code === data.template)?.label || data.template;
    switch (data.template_reason) {
      case "language": return `Picked from the submitter's language (${data.language}).`;
      case "no_language": return `The submitter has no language stored, so ${label} is used by default.`;
      case "unsupported": return `There is no template for the submitter's language (${data.language}), so ${label} is used.`;
      default: return "";
    }
  }

  function renderEmailForm(data, result) {
    const email = data.email;
    const host = $("[data-email]");
    const blockers = [];
    if (!data.configured) blockers.push("No mail server is configured yet.");
    if (!email.to_address) blockers.push("This submitter has no e-mail address.");
    const templateOptions = (data.templates || [])
      .map((t) => `<option value="${esc(t.code)}" ${t.code === data.template ? "selected" : ""}>${esc(t.label)}</option>`)
      .join("");

    const from = email.from_name ? `${email.from_name} <${email.from_address}>` : email.from_address;
    host.innerHTML = `
      ${blockers.length
        ? `<p class="import-hint is-warning">${blockers.map(esc).join(" ")}
             <a href="/setup?section=email_settings">Open e-mail settings</a></p>`
        : ""}
      <div class="import-mail">
        <label for="import-email-template">Template</label>
        <div class="import-mail-template">
          <select id="import-email-template" data-email-template data-no-searchable>${templateOptions}</select>
          <span class="import-hint" data-email-template-reason>${esc(templateReasonText(data))}</span>
        </div>
        <label for="import-email-to">To</label>
        <input id="import-email-to" type="email" data-email-to value="${esc(email.to_address)}" />
        <label for="import-email-from">From</label>
        <input id="import-email-from" type="text" value="${esc(from || "")}" disabled />
        <label for="import-email-subject">Subject</label>
        <input id="import-email-subject" type="text" data-email-subject value="${esc(email.subject)}" />
        <label for="import-email-body" class="is-top">Message</label>
        <textarea id="import-email-body" data-email-body rows="14">${esc(email.body)}</textarea>
      </div>
      <div class="import-mail-actions">
        <p class="import-foot-status" data-email-status></p>
        <button type="button" class="import-ghost" data-email-skip>Skip e-mail</button>
        <button type="button" class="import-primary" data-email-send ${blockers.length ? "disabled" : ""}>Send e-mail</button>
      </div>`;

    // Switching template re-renders subject and body only; the To field
    // keeps whatever the operator typed. Edits to the text would be lost,
    // so ask first.
    const subjectInput = host.querySelector("[data-email-subject]");
    const bodyInput = host.querySelector("[data-email-body]");
    const templateSelect = host.querySelector("[data-email-template]");
    // Compare against what the fields actually hold, not the server text:
    // the HTML parser turns the template's CRLFs into LFs, which would
    // make an untouched message look edited.
    let rendered = { subject: subjectInput.value, body: bodyInput.value };
    let currentTemplate = data.template;
    templateSelect.addEventListener("change", async () => {
      const edited = subjectInput.value !== rendered.subject || bodyInput.value !== rendered.body;
      if (edited && !window.confirm("Switching template replaces the subject and message, including your edits. Continue?")) {
        templateSelect.value = currentTemplate;
        return;
      }
      templateSelect.disabled = true;
      try {
        const res = await fetchEmailPreview(result, templateSelect.value);
        const next = await res.json();
        if (!res.ok) throw new Error(next.detail || "");
        currentTemplate = next.template;
        subjectInput.value = next.email.subject;
        bodyInput.value = next.email.body;
        rendered = { subject: subjectInput.value, body: bodyInput.value };
        host.querySelector("[data-email-template-reason]").textContent = templateReasonText(next);
      } catch (_e) {
        templateSelect.value = currentTemplate;
        window.SAMSToast?.show("That template could not be loaded.", "error");
      } finally {
        templateSelect.disabled = false;
      }
    });

    host.querySelector("[data-email-skip]").addEventListener("click", () => {
      $("[data-email-section]").hidden = true;
      window.SAMSToast?.show("No e-mail sent.", "info");
    });

    host.querySelector("[data-email-send]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Sending…";
      const status = host.querySelector("[data-email-status]");
      status.textContent = "";
      try {
        const res = await fetch("/samples/import/email/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            to_address: host.querySelector("[data-email-to]").value,
            subject: host.querySelector("[data-email-subject]").value,
            body: host.querySelector("[data-email-body]").value,
          }),
        });
        const data2 = await res.json();
        if (!res.ok) {
          status.textContent = data2.detail || "The e-mail could not be sent.";
          status.classList.add("is-error");
          button.disabled = false;
          button.textContent = "Send e-mail";
          return;
        }
        host.innerHTML = `<p class="import-sent">✓ Confirmation e-mail sent to ${esc(data2.to_address)}.</p>`;
        window.SAMSToast?.show("Confirmation e-mail sent.", "success");
      } catch (_e) {
        status.textContent = "The e-mail could not be sent. The import itself is unaffected.";
        status.classList.add("is-error");
        button.disabled = false;
        button.textContent = "Send e-mail";
      }
    });
  }
})();
