// Record actions (ADR-0007): the "Actions" menu on project and submitter
// pages, the tick column of their related table, and the preview dialog.
//
//   [data-record-actions]            menu root (from _record_actions.html)
//     data-base-url                  /projects/246 — the routes hang off it
//   [data-record-action="<key>"]     menu buttons (Set / Clear)
//   [data-record-action-row]         tick boxes in the related table
//   [data-record-action-all]         head tick box: ticks the rows shown
//   #action=<key>                    a URL hash (the command palette's
//                                    entries) opens that action's preview
//
// Choosing an action fetches `<base>/actions/<key>/preview?nrs=…` and shows
// what would change. Only the dialog's primary button posts, to
// `<base>/actions/<key>`; the server re-checks everything. All text is
// set with textContent: sample labels come from customers' sheets.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const plural = (count, singular, pluralWord) => (count === 1 ? singular : pluralWord);

  installers.installRecordActions = () => {
    const root = document.querySelector("[data-record-actions]");
    if (!root) return;

    const baseUrl = root.dataset.baseUrl;
    const rowSingular = root.dataset.rowSingular || "row";
    const rowPlural = root.dataset.rowPlural || "rows";
    const rowTotal = Number(root.dataset.rowTotal || 0);
    const toggle = root.querySelector("[data-record-actions-toggle]");
    const menu = root.querySelector("[data-record-actions-menu]");
    const scopeLine = root.querySelector("[data-record-actions-scope]");
    const dialog = root.querySelector("[data-record-action-dialog]");
    const form = dialog?.querySelector("[data-record-action-form]");
    const titleNode = dialog?.querySelector("[data-record-action-title]");
    const body = dialog?.querySelector("[data-record-action-body]");
    const nrsInput = dialog?.querySelector("[data-record-action-nrs]");
    const submit = dialog?.querySelector("[data-record-action-submit]");
    const tickAll = document.querySelector("[data-record-action-all]");
    const rowBoxes = () => Array.from(document.querySelectorAll("[data-record-action-row]"));
    const ticked = () => rowBoxes().filter((box) => box.checked).map((box) => box.value);

    // ---- Scope: ticked rows, or all of them -----------------------------
    const scopeText = () => {
      const count = ticked().length;
      if (count === 0) return `All ${rowTotal} ${plural(rowTotal, rowSingular, rowPlural)}`;
      return `${count} ticked ${plural(count, rowSingular, rowPlural)}`;
    };

    const syncTicks = () => {
      if (scopeLine) scopeLine.textContent = scopeText();
      if (!tickAll) return;
      const shown = rowBoxes().filter((box) => !box.closest("tr")?.hidden);
      const shownTicked = shown.filter((box) => box.checked).length;
      tickAll.checked = shown.length > 0 && shownTicked === shown.length;
      tickAll.indeterminate = shownTicked > 0 && shownTicked < shown.length;
    };

    document.addEventListener("change", (event) => {
      const target = event.target;
      if (target === tickAll) {
        // Only the rows the table filter shows: filter "bone", tick all.
        rowBoxes().forEach((box) => {
          if (!box.closest("tr")?.hidden) box.checked = tickAll.checked;
        });
        syncTicks();
      } else if (target?.matches?.("[data-record-action-row]")) {
        syncTicks();
      }
    });
    syncTicks();

    // ---- Menu -----------------------------------------------------------
    const setMenu = (open) => {
      if (!menu || !toggle) return;
      menu.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) {
        syncTicks();
        menu.querySelector("[data-record-action]")?.focus();
      }
    };

    toggle?.addEventListener("click", () => setMenu(menu.hidden));
    document.addEventListener("click", (event) => {
      if (menu && !menu.hidden && !root.contains(event.target)) setMenu(false);
    });
    menu?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setMenu(false);
        toggle?.focus();
      }
    });
    root.querySelectorAll("[data-record-action]").forEach((button) => {
      button.addEventListener("click", () => {
        setMenu(false);
        openAction(button.dataset.recordAction);
      });
    });

    if (!dialog || !form || !body || !submit) return;

    // The record's shortcuts ([ ] j k ?) must not fire under the dialog.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") event.stopPropagation();
    });
    dialog.querySelectorAll("[data-record-action-cancel]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });

    let requestId = 0;

    // ---- Preview ----------------------------------------------------------
    const recordLink = (item) => {
      const link = el("a", "record-action-ref", item.ref);
      link.href = item.href;
      link.target = "_blank";
      link.rel = "noopener";
      return link;
    };

    const renderList = (title, items, total, renderRow, extraClass) => {
      const section = el("section", `record-action-section ${extraClass || ""}`.trim());
      section.append(el("h4", "record-action-section-title", title));
      const wrap = el("div", "record-action-table-wrap");
      const table = el("table", "record-action-table");
      table.setAttribute("data-table-plain", "");
      const tbody = el("tbody");
      items.forEach((item) => tbody.append(renderRow(item)));
      table.append(tbody);
      wrap.append(table);
      section.append(wrap);
      if (total > items.length) {
        section.append(el("p", "record-action-note", `First ${items.length} of ${total} shown.`));
      }
      return section;
    };

    const renderPlan = (plan) => {
      body.textContent = "";
      const child = plan.child;
      const done = plan.verb === "Clear" ? "cleared" : "set";

      const facts = el("p", "record-action-summary");
      const changeCount = el("strong", "", `${plan.change_count} ${plural(plan.change_count, child.singular, child.plural)} change`);
      facts.append(changeCount);
      if (plan.unchanged) facts.append(document.createTextNode(` · ${plan.unchanged} already ${done}`));
      if (plan.refused_count) facts.append(document.createTextNode(` · ${plan.refused_count} cannot be changed`));
      body.append(facts);

      const fromLine = ticked().length
        ? `From ${plan.rows.count} ticked ${plan.rows.noun}.`
        : `From all ${plan.rows.count} ${plan.rows.noun} of this record.`;
      body.append(el("p", "record-action-from", fromLine));

      if (plan.warnings.length) {
        const list = el("ul", "record-action-warnings");
        plan.warnings.forEach((text) => list.append(el("li", "", text)));
        body.append(list);
      }

      if (plan.changes.length) {
        body.append(
          renderList(
            `${plan.field} will change`,
            plan.changes,
            plan.change_count,
            (item) => {
              const row = el("tr");
              const ref = el("td", "record-action-ref-cell");
              ref.append(recordLink(item));
              row.append(ref, el("td", "record-action-label", item.label || "—"));
              const change = el("td", "record-action-change");
              change.append(el("span", "record-action-old", item.old), document.createTextNode(" → "), el("span", "record-action-new", item.new));
              row.append(change);
              return row;
            },
          ),
        );
      }

      if (plan.refused.length) {
        body.append(
          renderList(
            "Cannot be changed — fix these on their own page",
            plan.refused,
            plan.refused_count,
            (item) => {
              const row = el("tr");
              const ref = el("td", "record-action-ref-cell");
              ref.append(recordLink(item));
              row.append(ref, el("td", "record-action-label", item.label || "—"), el("td", "record-action-reason", item.reason));
              return row;
            },
            "is-refused",
          ),
        );
      }

      if (plan.change_count === 0) {
        body.append(el("p", "record-action-note", "Nothing to change."));
        submit.disabled = true;
        submit.textContent = "Nothing to change";
      } else {
        submit.disabled = false;
        submit.textContent = `${plan.verb} on ${plan.change_count} ${plural(plan.change_count, child.singular, child.plural)}`;
      }
    };

    const renderError = (message) => {
      body.textContent = "";
      body.append(el("p", "record-action-error", message));
      submit.disabled = true;
      submit.textContent = "Run";
    };

    const openAction = async (key) => {
      if (!key) return;
      if (window.SAMSDetailEdit?.hasUnsavedChanges?.()) {
        window.SAMSToast?.show("Save or cancel the unsaved changes on this record first.", "info");
        return;
      }
      const button = root.querySelector(`[data-record-action="${CSS.escape(key)}"]`);
      titleNode.textContent = button?.title || "Action";
      const nrs = ticked().join(",");
      form.action = `${baseUrl}/actions/${encodeURIComponent(key)}`;
      nrsInput.value = nrs;
      submit.disabled = true;
      submit.classList.remove("is-saving");
      submit.textContent = "Run";
      body.textContent = "";
      body.append(el("p", "record-action-loading", "Checking which records change …"));
      if (!dialog.open) dialog.showModal();

      const thisRequest = ++requestId;
      const url = `${baseUrl}/actions/${encodeURIComponent(key)}/preview${nrs ? `?nrs=${encodeURIComponent(nrs)}` : ""}`;
      try {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (thisRequest !== requestId) return;
        let payload = null;
        try {
          payload = await response.json();
        } catch (_error) {
          payload = null;
        }
        if (!response.ok) {
          const reason = payload?.error || payload?.detail;
          renderError(reason || `The preview failed (HTTP ${response.status}). Reload the page and try again.`);
          return;
        }
        if (payload?.title) titleNode.textContent = payload.title;
        renderPlan(payload);
      } catch (_error) {
        if (thisRequest !== requestId) return;
        renderError("The server could not be reached. Check the connection and try again.");
      }
    };

    form.addEventListener("submit", () => {
      submit.classList.add("is-saving");
      // Disable after the submit has been collected, so the post still goes.
      window.setTimeout(() => {
        submit.disabled = true;
      }, 0);
    });

    // ---- #action=<key>: the command palette's entries ---------------------
    const openFromHash = () => {
      const match = /^#action=(.+)$/.exec(window.location.hash);
      if (!match) return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      openAction(decodeURIComponent(match[1]));
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
  };
})();
