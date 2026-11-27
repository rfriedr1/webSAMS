// Fetch LE/HE currents of a magazine from the raw AMS database (Lab →
// Analysis, ADR-0011). Opening the dialog loads the preview: per target the
// stored and the raw currents and what a fetch would do. Only Fetch posts;
// the server reads the raw database again before it writes.
//
// The raw databases may be unavailable at any time. Then the preview carries
// `problem` (title, advice, error) and the dialog says why, that nothing was
// changed, and offers Try again; Fetch stays disabled. Nothing else on the
// page touches the raw databases.
//
//   [data-magazine-actions]     root (from _magazine_actions.html), data-magazine
//   [data-raw-currents-open]    menu entry; #action=fetch-currents opens it too
//   [data-raw-currents-body]    preview, built here with textContent only
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const STATUS_TEXT = { new: "New", differs: "Replaces", same: "Same", no_raw: "No raw data" };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const fmt = (value) => (value === null || value === undefined ? "—" : Number(value).toFixed(2));

  installers.installRawCurrents = () => {
    const root = document.querySelector("[data-magazine-actions]");
    const opener = root?.querySelector("[data-raw-currents-open]");
    if (!root || !opener) return;

    const magazine = root.dataset.magazine;
    const toggle = root.querySelector("[data-magazine-actions-toggle]");
    const menu = root.querySelector("[data-magazine-actions-menu]");
    const dialog = root.querySelector("[data-raw-currents-dialog]");
    const form = dialog.querySelector("[data-raw-currents-form]");
    const body = dialog.querySelector("[data-raw-currents-body]");
    const submit = dialog.querySelector("[data-raw-currents-submit]");
    let requestId = 0;

    const setSubmit = (writes) => {
      submit.disabled = !writes;
      submit.textContent = writes ? `Fetch ${plural(writes, "target", "targets")}` : "Fetch";
    };

    const showError = (title, advice, detail) => {
      body.textContent = "";
      const box = el("div", "record-action-error raw-currents-problem");
      box.append(el("p", "raw-currents-problem-title", title));
      if (advice) box.append(el("p", "", advice));
      box.append(el("p", "", "Nothing was changed."));
      if (detail) box.append(el("p", "raw-currents-problem-detail", detail));
      body.append(box);
      const retry = el("button", "record-action-fill-button", "Try again");
      retry.type = "button";
      retry.addEventListener("click", load);
      body.append(retry);
    };

    const cell = (row, text, className) => {
      const td = el("td", className || "", text);
      row.append(td);
      return td;
    };

    const valueCell = (row, stored, raw, writes) => {
      const td = el("td", "raw-currents-value");
      if (writes) {
        td.append(el("span", "raw-currents-old", fmt(stored)), document.createTextNode(" → "), el("strong", "", fmt(raw)));
      } else {
        td.textContent = fmt(stored === null || stored === undefined ? raw : stored);
      }
      row.append(td);
    };

    const render = (plan) => {
      body.textContent = "";
      if (plan.problem) {
        const code = plan.problem.code ? `Error ${plan.problem.code}: ` : "";
        showError(plan.problem.title, plan.problem.advice, `${code}${plan.problem.detail || ""}`.trim());
        setSubmit(0);
        return;
      }
      if (plan.refusal) {
        showError(plan.refusal, "", "");
        body.querySelector(".record-action-fill-button")?.remove();
        setSubmit(0);
        return;
      }

      const counts = plan.counts;
      const summary = el("p", "record-action-from");
      summary.append(
        document.createTextNode(`From ${plan.raw_db}: `),
        el("strong", "", plural(counts.new, "new", "new")),
        document.createTextNode(` · ${counts.differs} replace a stored value · ${counts.same} same · ${counts.no_raw} without raw data`),
      );
      body.append(summary);
      const notes = [];
      if (plan.frozen_writes) notes.push(`${plural(plan.frozen_writes, "target is", "targets are")} frozen in BATS; the currents are written anyway (they are raw values, not BATS results).`);
      if (plan.several_rows) notes.push(`${plural(plan.several_rows, "target has", "targets have")} several raw rows; the newest is used.`);
      if (counts.no_raw) notes.push("Targets without raw data keep what is stored.");
      notes.forEach((note) => body.append(el("p", "raw-currents-note", note)));
      if (!plan.writes) body.append(el("p", "record-action-ok", "✓ All currents are up to date."));

      const wrap = el("div", "raw-currents-wrap");
      const table = el("table", "raw-currents-table");
      table.setAttribute("data-table-plain", "");
      const head = el("tr");
      ["Pos", "Target", "Label", "LE Current", "HE Current", ""].forEach((label) => head.append(el("th", "", label)));
      const thead = el("thead");
      thead.append(head);
      table.append(thead);
      const tbody = el("tbody");
      plan.rows.forEach((row) => {
        const tr = el("tr", `is-${row.status}`);
        cell(tr, row.position ?? "—", "raw-currents-num");
        cell(tr, row.target_id);
        cell(tr, row.label ?? "—", "raw-currents-label");
        valueCell(tr, row.stored.le_curr, row.raw.le_curr, "le_curr" in row.writes);
        valueCell(tr, row.stored.he_curr, row.raw.he_curr, "he_curr" in row.writes);
        const status = cell(tr, "", "raw-currents-status");
        status.append(el("span", `raw-currents-chip is-${row.status}`, STATUS_TEXT[row.status] || row.status));
        if (row.frozen && Object.keys(row.writes).length) status.append(el("span", "raw-currents-chip is-frozen", "Frozen"));
        tbody.append(tr);
      });
      table.append(tbody);
      wrap.append(table);
      body.append(wrap);
      setSubmit(plan.writes);
    };

    async function load() {
      const thisRequest = ++requestId;
      setSubmit(0);
      body.textContent = "";
      body.append(el("p", "record-action-loading", "Reading the raw AMS database …"));
      try {
        const params = new URLSearchParams({ magazine });
        const response = await fetch(`/lab/analysis/magazine/currents/preview?${params}`, { headers: { Accept: "application/json" } });
        if (thisRequest !== requestId) return;
        let payload = null;
        try {
          payload = await response.json();
        } catch (_error) {
          payload = null;
        }
        if (!response.ok || !payload) {
          showError(payload?.error || payload?.detail || `Loading failed (HTTP ${response.status}).`, "Reload the page and try again.", "");
          return;
        }
        render(payload);
      } catch (_error) {
        if (thisRequest !== requestId) return;
        showError("The server could not be reached.", "Check the connection and try again.", "");
      }
    }

    const open = () => {
      if (menu) menu.hidden = true;
      toggle?.setAttribute("aria-expanded", "false");
      submit.classList.remove("is-saving");
      if (!dialog.open) dialog.showModal();
      load();
    };

    opener.addEventListener("click", open);
    dialog.querySelectorAll("[data-raw-currents-cancel]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    // Page shortcuts must not fire under the dialog.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") event.stopPropagation();
    });
    form.addEventListener("submit", (event) => {
      if (submit.disabled) {
        event.preventDefault();
        return;
      }
      submit.classList.add("is-saving");
      window.setTimeout(() => {
        submit.disabled = true;
      }, 0);
    });

    // ---- #action=fetch-currents: the command palette's entry --------------
    const openFromHash = () => {
      if (window.location.hash !== "#action=fetch-currents") return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      open();
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
  };
})();
