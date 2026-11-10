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
//
// An Edit action (`mode: "edit"`, e.g. Sample Storage Location) shows an
// editor instead of a preview: every record with its current value in a
// box, a "Fill all" field, and a dirty dot on each changed row. Only the
// changed rows are posted, as JSON in the hidden `values` field.
// When the action names a `mark_suffix` (storage locations: "E", entnommen)
// an "Add E" button appends it to every filled box (266 → 266E), and the
// download icon saves the list (number, label, value, new value) as Excel
// for finding the samples in the lab.
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
    const valuesInput = dialog?.querySelector("[data-record-action-values]");
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

    // ---- Edit actions: one box per record --------------------------------
    let editorInputs = [];

    const changedValues = () => {
      const changed = {};
      editorInputs.forEach((input) => {
        if (input.disabled) return;
        if (input.value.trim() !== input.dataset.initialValue) changed[input.dataset.ref] = input.value.trim();
      });
      return changed;
    };

    const syncEditor = (plan) => {
      const child = plan.child;
      const count = Object.keys(changedValues()).length;
      editorInputs.forEach((input) => {
        input.closest("tr")?.classList.toggle("is-dirty", !input.disabled && input.value.trim() !== input.dataset.initialValue);
      });
      submit.disabled = count === 0;
      submit.textContent = count === 0 ? "Nothing changed yet" : `Save on ${count} ${plural(count, child.singular, child.plural)}`;
    };

    // "Project 246" from the page's base URL (/projects/246), for the file name.
    const ownerTitle = () => {
      const [kind, nr] = baseUrl.split("/").filter(Boolean);
      const word = (kind || "record").replace(/s$/, "");
      return `${word.charAt(0).toUpperCase()}${word.slice(1)} ${nr || ""}`.trim();
    };

    // The editor's list as Excel: number, label, value as stored and, when
    // boxes were changed, the new value beside it.
    const downloadButton = (plan) => {
      const button = el("button", "record-action-download");
      button.type = "button";
      const label = `Download the list as Excel (${plan.editor.columns.join(", ")}, ${plan.field})`;
      button.title = label;
      button.setAttribute("aria-label", label);
      const svgNs = "http://www.w3.org/2000/svg";
      const icon = document.createElementNS(svgNs, "svg");
      icon.setAttribute("viewBox", "0 0 24 24");
      icon.setAttribute("aria-hidden", "true");
      const path = document.createElementNS(svgNs, "path");
      path.setAttribute("d", "M12 3v10m0 0l4-4m-4 4-4-4M5 17h14v4H5z");
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "2");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      icon.append(path);
      button.append(icon);
      button.addEventListener("click", () => {
        const byRef = new Map(editorInputs.map((input) => [input.dataset.ref, input]));
        const changed = editorInputs.some((input) => input.value.trim() !== input.dataset.initialValue);
        const headers = [...plan.editor.columns, plan.field];
        if (changed) headers.push(`New ${plan.field}`);
        const rows = plan.editor.rows.map((row) => {
          const line = [row.ref, row.label || "", row.value || ""];
          if (changed) {
            const input = byRef.get(row.ref);
            const next = input ? input.value.trim() : row.value || "";
            line.push(next !== (row.value || "") ? next : "");
          }
          return line;
        });
        // The value columns stay text: "007" or "266" is a place, not a number.
        const textColumns = changed ? [1, 2, 3] : [1, 2];
        window.SAMSTableExport?.download(`${ownerTitle()} ${plan.field}`, headers, rows, {
          sheetName: plan.field,
          textColumns,
        });
      });
      return button;
    };

    const renderEditor = (plan) => {
      body.textContent = "";
      const child = plan.child;
      const rows = plan.editor.rows;
      const maxLength = plan.editor.max_length;
      const editable = rows.filter((row) => !row.refused);

      const fromLine = ticked().length
        ? `${rows.length} ${plural(rows.length, child.singular, child.plural)} from the ticked rows. Change a value, or fill them all.`
        : `All ${rows.length} ${plural(rows.length, child.singular, child.plural)} of this record. Tick rows first to edit only those.`;
      body.append(el("p", "record-action-from", fromLine));

      // Fill all: copies one value into every editable box.
      const fill = el("div", "record-action-fill");
      const fillInput = el("input");
      fillInput.type = "text";
      fillInput.className = "record-action-fill-input";
      fillInput.placeholder = `New ${plan.field} for all`;
      fillInput.setAttribute("aria-label", `New ${plan.field} for all ${child.plural}`);
      if (maxLength) fillInput.maxLength = maxLength;
      const distinct = [...new Set(editable.map((row) => row.value).filter(Boolean))];
      if (distinct.length === 1) fillInput.value = distinct[0];
      const fillButton = el("button", "record-action-fill-button", "Fill all");
      fillButton.type = "button";
      const applyFill = () => {
        editorInputs.forEach((input) => {
          if (!input.disabled) input.value = fillInput.value;
        });
        syncEditor(plan);
      };
      fillButton.addEventListener("click", applyFill);
      fillInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          applyFill();
        }
      });
      fill.append(fillInput, fillButton);

      // Add E: appends the action's mark to every filled, editable box that
      // does not end with it yet. Nothing is saved until Save.
      const suffix = plan.editor.mark_suffix;
      const markNote = el("p", "record-action-note record-action-mark-note");
      markNote.hidden = true;
      if (suffix) {
        const markButton = el("button", "record-action-fill-button record-action-mark-button", `Add ${suffix}`);
        markButton.type = "button";
        markButton.title = `Add “${suffix}” to every ${plan.field}: 266 → 266${suffix}. Empty boxes and values that already end in ${suffix} stay as they are.`;
        markButton.addEventListener("click", () => {
          let added = 0;
          let already = 0;
          let empty = 0;
          let tooLong = 0;
          editorInputs.forEach((input) => {
            if (input.disabled) return;
            const value = input.value.trim();
            if (!value) empty += 1;
            else if (value.toUpperCase().endsWith(suffix.toUpperCase())) already += 1;
            else if (maxLength && value.length + suffix.length > maxLength) tooLong += 1;
            else {
              input.value = `${value}${suffix}`;
              added += 1;
            }
          });
          const parts = [`${suffix} added to ${added} ${plural(added, child.singular, child.plural)}`];
          if (already) parts.push(`${already} already had it`);
          if (empty) parts.push(`${empty} empty, left as they are`);
          if (tooLong) parts.push(`${tooLong} too long to add it (at most ${maxLength} characters)`);
          markNote.textContent = `${parts.join(" · ")}. Check the list, then Save.`;
          markNote.hidden = false;
          syncEditor(plan);
        });
        fill.append(markButton);
      }
      body.append(fill, markNote);

      const section = el("section", "record-action-section");
      const head = el("div", "record-action-section-head");
      head.append(el("h4", "record-action-section-title", plan.field));
      head.append(downloadButton(plan));
      section.append(head);
      const wrap = el("div", "record-action-table-wrap is-editor");
      const table = el("table", "record-action-table record-action-editor");
      table.setAttribute("data-table-plain", "");
      const tbody = el("tbody");
      editorInputs = [];
      rows.forEach((row) => {
        const tr = el("tr");
        const ref = el("td", "record-action-ref-cell");
        ref.append(recordLink(row));
        tr.append(ref, el("td", "record-action-label", row.label || "—"));
        const cell = el("td", "record-action-value-cell");
        const input = el("input", "record-action-value");
        input.type = "text";
        input.value = row.value || "";
        input.placeholder = "—";
        input.dataset.ref = row.ref;
        input.dataset.initialValue = row.value || "";
        input.setAttribute("aria-label", `${plan.field} of ${child.singular} ${row.ref}`);
        if (maxLength) input.maxLength = maxLength;
        cell.append(input);
        if (row.refused) {
          input.disabled = true;
          input.title = row.refused;
          cell.append(el("span", "record-action-reason", row.refused));
          tr.classList.add("is-refused");
        }
        input.addEventListener("input", () => syncEditor(plan));
        input.addEventListener("keydown", (event) => {
          // Enter moves down the list, like a spreadsheet; it never saves.
          if (event.key !== "Enter") return;
          event.preventDefault();
          const live = editorInputs.filter((box) => !box.disabled);
          const next = live[live.indexOf(input) + (event.shiftKey ? -1 : 1)];
          next?.focus();
          next?.select();
        });
        tr.append(cell);
        tbody.append(tr);
        editorInputs.push(input);
      });
      table.append(tbody);
      wrap.append(table);
      section.append(wrap);
      body.append(section);

      const refusedCount = rows.length - editable.length;
      if (refusedCount) {
        body.append(
          el(
            "p",
            "record-action-note",
            `${refusedCount} ${plural(refusedCount, child.singular, child.plural)} cannot be changed here — fix them on their own page.`,
          ),
        );
      }
      syncEditor(plan);
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
      if (valuesInput) valuesInput.value = "";
      editorInputs = [];
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
        if (payload?.mode === "edit") renderEditor(payload);
        else renderPlan(payload);
      } catch (_error) {
        if (thisRequest !== requestId) return;
        renderError("The server could not be reached. Check the connection and try again.");
      }
    };

    form.addEventListener("submit", (event) => {
      if (editorInputs.length) {
        const changed = changedValues();
        if (!Object.keys(changed).length) {
          event.preventDefault();
          return;
        }
        if (valuesInput) valuesInput.value = JSON.stringify(changed);
      }
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
