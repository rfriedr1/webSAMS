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

  const state = {
    payload: null,
    draft: null,
    mapping: {},
    party: {
      submitter: { mode: "new", user_nr: null, values: {}, browse: [], query: "" },
      invoice: { enabled: false, mode: "new", user_nr: null, values: {}, browse: [], query: "" },
    },
    project: { mode: "new", existing_project_nr: null, values: {}, existing: [], matches: [] },
    groups: {},
    selection: new Set(),
    hiddenColumns: new Set(),
    committing: false,
    result: null,
  };

  //: Sheet columns the lab-values table hides by default. This step is
  //: about assigning lab vocabulary, so the wide free-text/measurement
  //: columns only add noise — they stay one click away via "Columns".
  const DEFAULT_HIDDEN_COLUMNS = ["weight", "user_desc2"];

  // ---------------------------------------------------------------- utils

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);

  const showError = (message) => {
    const box = $("[data-import-error]");
    box.textContent = message;
    box.hidden = !message;
    if (message) box.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const STEPS = ["upload", "review", "lab", "done"];
  const setStep = (step) => {
    const index = STEPS.indexOf(step);
    root.querySelectorAll("[data-stage]").forEach((el) => {
      el.hidden = el.dataset.stage !== step;
    });
    root.querySelectorAll(".import-step").forEach((el) => {
      const position = STEPS.indexOf(el.dataset.step);
      el.classList.toggle("is-current", position === index);
      el.classList.toggle("is-done", position < index);
    });
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
        showError(payload.detail || "The workbook could not be read.");
        return;
      }
      applyPayload(payload);
      setStep("review");
      window.addEventListener("beforeunload", guardUnload);
    } catch (_error) {
      showError("Upload failed. Check your connection and try again.");
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
  $("[data-back-review]").addEventListener("click", () => setStep("review"));
  $("[data-goto-lab]").addEventListener("click", () => {
    if (reviewProblems().length) { renderAlerts(); return; }
    setStep("lab");
    renderLabStage();
  });

  // ------------------------------------------------------------ bootstrap

  function applyPayload(payload) {
    state.payload = payload;
    state.draft = payload.draft;
    state.selection = new Set();
    state.hiddenColumns = new Set(DEFAULT_HIDDEN_COLUMNS);
    state.result = null;

    state.mapping = {};
    payload.draft.columns.forEach((c) => { state.mapping[c.column_letter] = c.field || ""; });

    // Pre-select a confidently matched submitter, else create new.
    const strong = (payload.submitter_candidates || []).find((c) => c.is_strong);
    state.party.submitter = {
      mode: strong ? "existing" : "new",
      user_nr: strong ? strong.user_nr : null,
      values: { ...payload.draft.submitter.values },
      browse: [],
      query: "",
    };

    const invoiceStrong = (payload.invoice_candidates || []).find((c) => c.is_strong);
    state.party.invoice = {
      enabled: !payload.draft.same_invoice_address && !payload.draft.invoice.is_empty,
      mode: invoiceStrong ? "existing" : "new",
      user_nr: invoiceStrong ? invoiceStrong.user_nr : null,
      values: { ...payload.draft.invoice.values },
      browse: [],
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
    groupKeys().forEach((key) => {
      const resolved = payload.lookup_resolutions?.material?.[key]?.resolved || "";
      state.groups[key] = {
        material: resolved,
        type: "",
        fraction: "",
        steps: ["", "", "", "", ""],
      };
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
    $("[data-source-summary]").innerHTML =
      `<strong>${esc(d.file_name)}</strong> &middot; sheet “${esc(d.sheet_name)}” ` +
      `&middot; header row ${d.header_row} &middot; ${d.sample_count} sample row(s)`;
    renderParty("submitter");
    renderParty("invoice");
    renderProject();
    renderAlerts();
  }

  const PARTY_LABEL = { submitter: "submitter", invoice: "invoice recipient" };

  /**
   * Submitter / invoice picker.
   *
   * Three ways to choose: a scored candidate, a browsable search over all
   * submitters, or create a new record from editable fields. The scored
   * list stays on top because it is right most of the time; the browse
   * box exists for when it isn't.
   */
  function renderParty(which) {
    const host = $(`[data-${which}]`);
    const party = state.party[which];
    const candidates =
      which === "submitter"
        ? state.payload.submitter_candidates || []
        : state.payload.invoice_candidates || [];
    const parsed = which === "submitter" ? state.draft.submitter : state.draft.invoice;

    // The invoice block is optional; everything hides behind one toggle.
    const toggle =
      which === "invoice"
        ? `<label class="import-toggle">
             <input type="checkbox" data-invoice-enabled ${party.enabled ? "checked" : ""} />
             <span>Bill a different person or address than the submitter</span>
           </label>`
        : "";

    if (which === "invoice" && !party.enabled) {
      host.innerHTML =
        toggle +
        `<p class="import-fixups-hint">The submitter's own address will be used for billing.</p>`;
      host.querySelector("[data-invoice-enabled]").addEventListener("change", (e) => {
        party.enabled = e.target.checked;
        renderParty("invoice");
        renderAlerts();
      });
      return;
    }

    const candidateHtml = candidates
      .map((c) => {
        const checked = party.mode === "existing" && party.user_nr === c.user_nr;
        return `
          <label class="import-choice ${checked ? "is-selected" : ""}">
            <input type="radio" name="${which}-choice" value="${c.user_nr}" ${checked ? "checked" : ""} />
            <span class="import-choice-body">
              <span class="import-choice-title">${esc(c.display_name)}
                <span class="import-choice-id">#${c.user_nr}</span>
                ${c.is_strong ? '<span class="import-badge-strong">strong match</span>' : ""}
              </span>
              <span class="import-choice-meta">${esc(c.organisation || "—")}${c.email ? " &middot; " + esc(c.email) : ""}</span>
              <span class="import-choice-why">${esc(c.reasons.join(", "))}</span>
            </span>
          </label>`;
      })
      .join("");

    const browseHtml = party.browse
      .map((r) => {
        const checked = party.mode === "existing" && party.user_nr === r.user_nr;
        return `
          <label class="import-choice is-compact ${checked ? "is-selected" : ""}">
            <input type="radio" name="${which}-choice" value="${r.user_nr}" ${checked ? "checked" : ""} />
            <span class="import-choice-body">
              <span class="import-choice-title">${esc(r.display_name)}
                <span class="import-choice-id">#${r.user_nr}</span></span>
              <span class="import-choice-meta">${esc(r.organisation || "—")}${r.town ? " &middot; " + esc(r.town) : ""}${r.email ? " &middot; " + esc(r.email) : ""}</span>
            </span>
          </label>`;
      })
      .join("");

    const newChecked = party.mode === "new";
    host.innerHTML = `
      ${toggle}
      ${candidates.length
        ? `<p class="import-fixups-hint">${candidates.length} existing ${PARTY_LABEL[which]}(s) match this sheet.</p>`
        : `<p class="import-fixups-hint">Nothing matched automatically — search below, or create a new record.</p>`}
      <div class="import-choices">${candidateHtml}</div>

      <details class="import-details" data-browse-details ${party.browse.length ? "open" : ""}>
        <summary>Browse all submitters</summary>
        <div class="import-browse">
          <input type="search" data-browse-input value="${esc(party.query)}"
                 placeholder="Search by name, organisation or institute" />
          <button type="button" class="import-secondary" data-browse-go>Search</button>
        </div>
        <div class="import-choices import-browse-results">
          ${browseHtml || '<p class="import-empty">No search yet.</p>'}
        </div>
      </details>

      <div class="import-choices">
        <label class="import-choice ${newChecked ? "is-selected" : ""}">
          <input type="radio" name="${which}-choice" value="new" ${newChecked ? "checked" : ""} />
          <span class="import-choice-body">
            <span class="import-choice-title">Create a new ${esc(PARTY_LABEL[which])}</span>
            <span class="import-choice-meta">${esc(parsed.display_name)}</span>
          </span>
        </label>
      </div>

      ${newChecked ? renderContactForm(which, party.values) : ""}`;

    host.querySelectorAll(`input[name='${which}-choice']`).forEach((input) => {
      input.addEventListener("change", () => {
        if (input.value === "new") {
          party.mode = "new";
          party.user_nr = null;
        } else {
          party.mode = "existing";
          party.user_nr = Number(input.value);
        }
        renderParty(which);
        if (which === "submitter") refreshProjectsForSubmitter();
        renderAlerts();
      });
    });

    const browseInput = host.querySelector("[data-browse-input]");
    const runBrowse = async () => {
      party.query = browseInput.value;
      try {
        const res = await fetch(
          `/samples/import/submitters?q=${encodeURIComponent(party.query)}`
        );
        const data = await res.json();
        party.browse = data.submitters || [];
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

    if (which === "invoice") {
      host.querySelector("[data-invoice-enabled]")?.addEventListener("change", (e) => {
        party.enabled = e.target.checked;
        renderParty("invoice");
        renderAlerts();
      });
    }
  }

  /** Editable field set shown when creating a NEW submitter/invoice record. */
  function renderContactForm(which, values) {
    const fields = state.payload.contact_fields || [];
    const body = fields
      .map((f) => {
        const value = values[f.key] ?? "";
        let control;
        if (f.kind === "textarea") {
          control = `<textarea data-contact-field="${f.key}" rows="3">${esc(value)}</textarea>`;
        } else if (f.kind === "select") {
          control = `<select data-contact-field="${f.key}">${optionList(
            f.options.map((o) => o.value), value, "—"
          )}</select>`;
        } else {
          control = `<input type="${f.kind === "email" ? "email" : "text"}"
                            data-contact-field="${f.key}" value="${esc(value)}" />`;
        }
        return `<div class="import-field ${f.kind === "textarea" ? "import-span-2" : ""}">
                  <label>${esc(f.label)}</label>${control}
                </div>`;
      })
      .join("");
    return `
      <div class="import-newrecord">
        <p class="import-fixups-hint">
          These values will be saved as a new record — check them before importing.
          Salutation, title, language and comment are not in the sheet; fill them in as needed.
          <em>Language decides which confirmation-e-mail template is used.</em>
        </p>
        <div class="import-field-grid">${body}</div>
      </div>`;
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

  const PROJECT_TEXT_FIELDS = [
    { key: "project", label: "Project Name", type: "text", span: 2 },
    { key: "in_date", label: "In Date", type: "date" },
    { key: "desired_date", label: "Desired Date", type: "date" },
  ];
  const PROJECT_SELECTS = [
    { key: "project_type", label: "Project Type" },
    { key: "research", label: "Research" },
    { key: "report_type", label: "Report Type" },
    { key: "supervisor", label: "Supervisor" },
  ];
  const PROJECT_CHECKS = [
    { key: "free_of_charge", label: "Free of charge" },
    { key: "return_to_sender", label: "Return samples to sender" },
    { key: "prep_return_to_sender", label: "Return preparations to sender" },
  ];

  /**
   * The duplicate-project prompt.
   *
   * Rendered into its own container so it can refresh on every keystroke
   * in the project-name field without re-rendering (and therefore
   * blurring) the form inputs around it.
   */
  function renderDuplicatePrompt() {
    const p = state.project;
    const host = $("[data-project-duplicate]");
    if (!host) return;
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
                <span class="import-choice-meta">${esc(m.project)}</span>
                <span class="import-choice-why">${esc(m.status)}${m.in_date ? " &middot; in " + esc(m.in_date) : ""}</span>
              </span>
            </label>`;
        })
        .join("");
      const newChecked = p.mode === "new";
      duplicateHtml = `
        <div class="import-duplicate">
          <p class="import-duplicate-title">
            This submitter already has a project with this name.
          </p>
          <div class="import-choices">
            ${rows}
            <label class="import-choice ${newChecked ? "is-selected" : ""}">
              <input type="radio" name="project-mode" value="new" ${newChecked ? "checked" : ""} />
              <span class="import-choice-body">
                <span class="import-choice-title">Create a separate project</span>
                <span class="import-choice-meta">Suggested name: ${esc(variantName(p.values.project))}</span>
              </span>
            </label>
          </div>
          ${newChecked
            ? `<button type="button" class="import-secondary" data-use-variant>Use the suggested name</button>`
            : ""}
        </div>`;
    }
    host.innerHTML = duplicateHtml;

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
    host.querySelector("[data-use-variant]")?.addEventListener("click", () => {
      p.values.project = variantName(p.values.project) || p.values.project;
      p.matches = matchProjectNames(p.values.project, p.existing);
      renderProject();
      renderAlerts();
    });
  }

  function renderProject() {
    const p = state.project;
    const opts = state.payload.project_options;

    // When appending, project settings belong to the existing project.
    const settingsDisabled = p.mode === "existing";
    const textFields = PROJECT_TEXT_FIELDS.map(
      (f) => `
        <div class="import-field ${f.span === 2 ? "import-span-2" : ""}">
          <label>${esc(f.label)}</label>
          <input type="${f.type}" data-project-field="${f.key}"
                 value="${esc(p.values[f.key] ?? "")}" ${settingsDisabled ? "disabled" : ""} />
        </div>`
    ).join("");

    const selects = PROJECT_SELECTS.map(
      (f) => `
        <div class="import-field">
          <label>${esc(f.label)}</label>
          <select data-project-field="${f.key}" ${settingsDisabled ? "disabled" : ""}>
            ${optionList(opts[f.key] || [], p.values[f.key] ?? "", "—")}
          </select>
        </div>`
    ).join("");

    const priority = `
      <div class="import-field">
        <label>Priority</label>
        <select data-project-field="priority" ${settingsDisabled ? "disabled" : ""}>
          ${(opts.priority || [])
            .map(
              (o) =>
                `<option value="${o.value}" ${String(o.value) === String(p.values.priority) ? "selected" : ""}>${esc(o.label)}</option>`
            )
            .join("")}
        </select>
      </div>`;

    const checks = PROJECT_CHECKS.map(
      (f) => `
        <label class="import-check">
          <input type="checkbox" data-project-check="${f.key}"
                 ${p.values[f.key] ? "checked" : ""} ${settingsDisabled ? "disabled" : ""} />
          <span>${esc(f.label)}</span>
        </label>`
    ).join("");

    $("[data-project]").innerHTML = `
      <div data-project-duplicate></div>
      ${settingsDisabled
        ? `<p class="import-fixups-hint">Samples will be added to the existing project — its settings are left unchanged.</p>`
        : ""}
      <div class="import-field-grid">${textFields}${selects}${priority}</div>
      <div class="import-checks">${checks}</div>
      <div class="import-field import-span-2">
        <label>Comment</label>
        <textarea data-project-field="project_comment" rows="2" ${settingsDisabled ? "disabled" : ""}>${esc(p.values.project_comment ?? "")}</textarea>
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
        ? `${problems.length} thing(s) to fix`
        : `${items.length} note(s)`;
      $("[data-alert-list]").innerHTML = items
        .map((i) => `<li class="is-${i.severity}">${esc(i.message)}</li>`)
        .join("");
    }
    $("[data-goto-lab]").disabled = problems.length > 0;
    $("[data-review-status]").textContent = problems.length
      ? "Resolve the items above to continue"
      : "Ready — continue to assign lab values";
  }

  // -------------------------------------------------------------- step 3

  function renderLabStage() {
    $("[data-lab-summary]").innerHTML =
      `<strong>${esc(state.draft.file_name)}</strong> &middot; ` +
      `${includedSamples().length} sample(s) selected`;
    renderGroups();
    renderMapping();
    renderSamples();
    renderBulkBar();
    renderLabAlerts();
  }

  const includedSamples = () => state.draft.samples.filter((s) => s.include);

  /**
   * Group cards: one per distinct submitter material.
   *
   * The customer's wording ("collagen") is shown as the heading, and the
   * lab's own vocabulary is chosen beneath it. Suggestions come from the
   * server's fuzzy match so the usual case is a confirming click.
   */
  function renderGroups() {
    const opts = state.payload.lookup_options;
    const methods = state.payload.method_options || [];
    const suggestions = state.payload.group_suggestions || {};

    $("[data-groups]").innerHTML = groupKeys()
      .map((key) => {
        const rows = state.draft.samples.filter(
          (s) => s.include && groupKeyFor(s) === key
        ).length;
        if (!rows) return "";
        const g = state.groups[key] || { steps: [] };
        const chips = (field) =>
          (suggestions[key]?.[field] || [])
            .slice(0, 3)
            .map(
              (v) =>
                `<button type="button" class="import-suggest" data-group-suggest="${esc(key)}"
                         data-group-field="${field}" data-group-value="${esc(v)}">${esc(v)}</button>`
            )
            .join("");
        const selects = LOOKUP_FIELDS.map(
          (field) => `
            <div class="import-field">
              <label>${esc(state.payload.field_labels.sample[field] || field)}</label>
              <select data-group-select="${esc(key)}" data-group-field="${field}">
                ${optionList(opts[field] || [], g[field] || "", "— undefined —")}
              </select>
              ${chips(field) ? `<div class="import-suggests">${chips(field)}</div>` : ""}
            </div>`
        ).join("");
        const steps = g.steps
          .map(
            (value, index) => `
              <select data-group-step="${esc(key)}" data-step-index="${index}"
                      aria-label="Preparation step ${index + 1}">
                ${optionList(methods, value || "", `Step ${index + 1}`)}
              </select>`
          )
          .join("");
        return `
          <article class="import-group">
            <header class="import-group-head">
              <span class="import-group-name">“${esc(key)}”</span>
              <span class="import-group-count">${rows} row(s)</span>
            </header>
            <div class="import-field-grid import-group-fields">${selects}</div>
            <div class="import-group-steps">
              <label>Preparation steps</label>
              <div class="import-step-selects">${steps}</div>
            </div>
          </article>`;
      })
      .join("");

    const host = $("[data-groups]");
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
    $("[data-mapping-count]").textContent = `${mapped} of ${columns.length} mapped`;
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

  /** The mapped sheet columns the table actually shows. */
  function sheetFields() {
    return mappedSheetFields().filter((f) => !state.hiddenColumns.has(f));
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
        const shown = !state.hiddenColumns.has(field);
        return `<button type="button" class="import-column-chip ${shown ? "is-on" : ""}"
                        data-column-toggle="${esc(field)}" aria-pressed="${shown}">
                  ${esc(labels[field] || field)}
                </button>`;
      })
      .join("");
    host.querySelectorAll("[data-column-toggle]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const field = chip.dataset.columnToggle;
        if (state.hiddenColumns.has(field)) state.hiddenColumns.delete(field);
        else state.hiddenColumns.add(field);
        renderSamples();
      });
    });
  }

  function renderSamples() {
    renderColumnToggles();
    const sheet = sheetFields();
    const labels = state.payload.field_labels.sample;
    $("[data-sample-count]").textContent =
      `${includedSamples().length} of ${state.draft.samples.length} row(s) will be imported`;

    $("[data-sample-head]").innerHTML =
      "<tr>" +
      '<th class="import-col-check"><input type="checkbox" data-select-all title="Select all" /></th>' +
      '<th class="import-col-row">Row</th>' +
      sheet.map((f) => `<th>${esc(labels[f] || f)}</th>`).join("") +
      LOOKUP_FIELDS.map(
        (f) => `<th class="import-col-lab">Lab ${esc(labels[f] || f)}</th>`
      ).join("") +
      STEP_COLUMNS.map((_, i) => `<th class="import-col-step">Step ${i + 1}</th>`).join("") +
      "</tr>";

    const opts = state.payload.lookup_options;
    const methods = state.payload.method_options || [];

    $("[data-sample-body]").innerHTML = state.draft.samples
      .map((sample, index) => {
        const sheetCells = sheet
          .map(
            (field) =>
              `<td><input data-cell-row="${index}" data-cell-field="${field}"
                          value="${esc(sample.values[field] ?? "")}" /></td>`
          )
          .join("");
        const labCells = LOOKUP_FIELDS.map((field) => {
          const value = sample.values[`lab_${field}`] || "";
          return `<td class="import-col-lab ${value ? "" : "is-unset"}">
                    <select data-cell-row="${index}" data-lab-field="${field}">
                      ${optionList(opts[field] || [], value, "— undefined —")}
                    </select></td>`;
        }).join("");
        const stepCells = STEP_COLUMNS.map(
          (col, i) => `<td class="import-col-step">
              <select data-cell-row="${index}" data-step-field="${col}">
                ${optionList(methods, sample.values[col] || "", `Step ${i + 1}`)}
              </select></td>`
        ).join("");
        const errors = (sample.issues || []).filter((i) => i.severity === "error");
        return `
          <tr class="${sample.include ? "" : "is-excluded"} ${errors.length ? "has-error" : ""}
                     ${state.selection.has(index) ? "is-selected-row" : ""}">
            <td class="import-col-check">
              <input type="checkbox" data-select-row="${index}" ${state.selection.has(index) ? "checked" : ""} />
            </td>
            <td class="import-col-row">
              <label class="import-include">
                <input type="checkbox" data-include-row="${index}" ${sample.include ? "checked" : ""}
                       title="Include this row" />
                <span>${sample.row_number}</span>
              </label>
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
    $("[data-bulk-count]").textContent = `${state.selection.size} row(s) selected`;

    const fieldSelect = $("[data-bulk-field]");
    if (!fieldSelect.options.length) {
      const labels = state.payload.field_labels.sample;
      fieldSelect.innerHTML = LOOKUP_FIELDS.map(
        (f) => `<option value="lab_${f}">Lab ${esc(labels[f] || f)}</option>`
      ).concat(
        STEP_COLUMNS.map((c, i) => `<option value="${c}">Preparation step ${i + 1}</option>`)
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
    includedSamples().forEach((s) => {
      if (!String(s.values.user_label || "").trim()) {
        problems.push(`Row ${s.row_number} has no sample name — fix it or untick the row.`);
      }
    });
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
        ? `${problems.length} thing(s) to fix before importing`
        : `${items.length} note(s)`;
      $("[data-lab-alert-list]").innerHTML = items
        .map((i) => `<li class="is-${i.severity}">${esc(i.message)}</li>`)
        .join("");
    }
    $("[data-commit]").disabled = problems.length > 0 || state.committing;
    $("[data-commit-status]").textContent = problems.length
      ? "Resolve the items above to continue"
      : `Ready — ${includedSamples().length} sample(s) will be created`;
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
        return { include: true, row_number: sample.row_number, values };
      }),
    };
  }

  $("[data-commit]").addEventListener("click", async () => {
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
        showError(result.detail || "The import could not be saved.");
        return;
      }
      state.result = result;
      window.removeEventListener("beforeunload", guardUnload);
      renderDone(result);
      setStep("done");
      window.SAMSToast?.show(`Imported ${result.sample_count} sample(s).`, "success");
      loadEmailPreview(result);
    } catch (_error) {
      showError("The import request failed. Nothing was saved — please try again.");
    } finally {
      state.committing = false;
      button.disabled = false;
      button.textContent = "Import samples";
    }
  });

  // -------------------------------------------------------------- step 4

  function renderDone(result) {
    const range = result.sample_nrs.length
      ? `${result.sample_nrs[0]}–${result.sample_nrs[result.sample_nrs.length - 1]}`
      : "—";
    $("[data-done]").innerHTML = `
      <div class="import-done-head">
        <span class="import-done-mark" aria-hidden="true">&#10003;</span>
        <div>
          <h3>Imported ${result.sample_count} sample${result.sample_count === 1 ? "" : "s"}</h3>
          <p>Each sample has preparation&nbsp;#1 and target&nbsp;#1 ready for the bench.</p>
        </div>
      </div>
      <div class="cards import-done-cards">
        <article>
          <h3>Project</h3>
          <p><a href="${result.project_url}">#${result.project_nr}</a></p>
          <span class="import-done-meta">${esc(result.project_name)}${result.project_created ? " (new)" : " (existing)"}</span>
        </article>
        <article>
          <h3>Submitter</h3>
          <p><a href="${result.submitter_url}">#${result.user_nr}</a></p>
          <span class="import-done-meta">${esc(result.submitter_name)}${result.submitter_created ? " (new)" : " (existing)"}</span>
        </article>
        <article>
          <h3>Samples</h3>
          <p>${range}</p>
          <span class="import-done-meta">${result.sample_count} created</span>
        </article>
      </div>
      <div class="import-done-actions">
        <a class="import-primary" href="${result.project_url}">Open the project</a>
        ${result.first_sample_url ? `<a class="import-secondary" href="${result.first_sample_url}">Open first sample</a>` : ""}
        <a class="import-secondary" href="/samples/import">Import another file</a>
      </div>`;
  }

  /**
   * Render the confirmation e-mail. Nothing is sent here — the operator
   * reviews (and may edit) the text, then explicitly clicks Send.
   */
  async function loadEmailPreview(result) {
    const section = $("[data-email-section]");
    const host = $("[data-email]");
    section.hidden = false;
    host.innerHTML = `<p class="import-fixups-hint"><span class="import-spinner"></span> Preparing the confirmation e-mail…</p>`;
    try {
      const res = await fetch("/samples/import/email/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_nr: result.user_nr,
          project_nr: result.project_nr,
          project_name: result.project_name,
          sample_nrs: result.sample_nrs,
          sample_labels: result.sample_labels,
        }),
      });
      const data = await res.json();
      if (!res.ok) { host.innerHTML = `<p class="import-empty">${esc(data.detail || "No preview available.")}</p>`; return; }
      renderEmailForm(data);
    } catch (_e) {
      host.innerHTML = `<p class="import-empty">The e-mail preview could not be loaded. The import itself is complete.</p>`;
    }
  }

  function renderEmailForm(data) {
    const email = data.email;
    const host = $("[data-email]");
    const blockers = [];
    if (!data.configured) blockers.push("No mail server is configured yet.");
    if (!email.to_address) blockers.push("This submitter has no e-mail address.");

    host.innerHTML = `
      ${blockers.length
        ? `<p class="table-truncation-notice">${blockers.map(esc).join(" ")}
             <a href="/setup?section=email_settings">Open e-mail settings</a></p>`
        : `<p class="import-fixups-hint">
             Review the message below — it is <strong>not sent</strong> until you click Send.
             ${data.language ? `Template language: <strong>${esc(data.language)}</strong>.` : ""}
           </p>`}
      <div class="import-field-grid import-email-grid">
        <div class="import-field"><label>To</label>
          <input type="email" data-email-to value="${esc(email.to_address)}" /></div>
        <div class="import-field"><label>From</label>
          <input type="text" value="${esc(email.from_name ? email.from_name + " <" + email.from_address + ">" : email.from_address)}" disabled /></div>
        <div class="import-field import-span-2"><label>Subject</label>
          <input type="text" data-email-subject value="${esc(email.subject)}" /></div>
        <div class="import-field import-span-2"><label>Message</label>
          <textarea data-email-body rows="16">${esc(email.body)}</textarea></div>
      </div>
      <div class="import-actions">
        <p class="import-actions-status" data-email-status></p>
        <button type="button" class="import-restart" data-email-skip>Skip — don't send</button>
        <button type="button" class="import-primary" data-email-send ${blockers.length ? "disabled" : ""}>Send e-mail</button>
      </div>`;

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
        host.innerHTML = `<p class="import-sent">&#10003; Confirmation e-mail sent to ${esc(data2.to_address)}.</p>`;
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
