// Swap target info (ADR-0008): the Actions menu on the target page and its
// dialog. The operator names the other target (sample / prep / target #),
// presses Show, and sees both targets' values per group with a tick box
// each (ticked unless both sides are equal). Only the dialog's Swap button posts, to
// `<base>/swap`; the server checks again and redirects with a toast.
//
//   [data-target-swap]          root (from _target_swap.html), data-base-url
//   [data-target-swap-open]     menu entry; #action=swap-target opens it too
//   [data-target-swap-nr]       the three number fields (posted)
//   [data-target-swap-body]     comparison, built here with textContent only
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  installers.installTargetSwap = () => {
    const root = document.querySelector("[data-target-swap]");
    if (!root) return;

    const baseUrl = root.dataset.baseUrl;
    const toggle = root.querySelector("[data-target-swap-toggle]");
    const menu = root.querySelector("[data-target-swap-menu]");
    const dialog = root.querySelector("[data-target-swap-dialog]");
    const form = dialog.querySelector("[data-target-swap-form]");
    const body = dialog.querySelector("[data-target-swap-body]");
    const submit = dialog.querySelector("[data-target-swap-submit]");
    const loadButton = dialog.querySelector("[data-target-swap-load]");
    const numberInputs = Array.from(dialog.querySelectorAll("[data-target-swap-nr]"));
    let preview = null;
    let requestId = 0;

    // ---- Menu (same behaviour as the record-action menu) -----------------
    const setMenu = (open) => {
      menu.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) menu.querySelector("button")?.focus();
    };
    toggle.addEventListener("click", () => setMenu(menu.hidden));
    document.addEventListener("click", (event) => {
      if (!menu.hidden && !root.contains(event.target)) setMenu(false);
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setMenu(false);
        toggle.focus();
      }
    });

    // ---- Dialog -----------------------------------------------------------
    const note = (text, className = "record-action-note") => {
      body.textContent = "";
      body.append(el("p", className, text));
    };

    const tickedGroups = () =>
      Array.from(body.querySelectorAll("input[name=groups]")).filter((box) => box.checked).map((box) => box.value);

    const syncSubmit = () => {
      const count = preview ? tickedGroups().length : 0;
      submit.disabled = count === 0;
      submit.textContent = count === 0 ? "Swap" : `Swap ${count} ${count === 1 ? "group" : "groups"}`;
      // Notes apply only while their group is ticked.
      const ticked = new Set(tickedGroups());
      body.querySelectorAll("[data-swap-note-group]").forEach((item) => {
        item.hidden = !ticked.has(item.dataset.swapNoteGroup);
      });
      const list = body.querySelector(".record-action-warnings");
      if (list) list.hidden = !list.querySelector("li:not([hidden])");
      body.querySelectorAll("[data-swap-group]").forEach((section) => {
        section.classList.toggle("is-off", !ticked.has(section.dataset.swapGroup));
      });
    };

    const renderPreview = (plan) => {
      body.textContent = "";
      const link = (ref) => {
        const a = el("a", "record-action-ref", ref.ref);
        a.href = ref.href;
        a.target = "_blank";
        a.rel = "noopener";
        return a;
      };

      const facts = el("p", "record-action-summary");
      facts.append(document.createTextNode("This target "), link(plan.this), document.createTextNode(" ⇄ target "), link(plan.other));
      if (plan.other.label) facts.append(document.createTextNode(` · ${plan.other.label}`));
      body.append(facts);

      if (plan.warnings.length) {
        const list = el("ul", "record-action-warnings");
        plan.warnings.forEach((warning) => {
          const item = el("li", "", warning.text);
          item.dataset.swapNoteGroup = warning.group;
          list.append(item);
        });
        body.append(list);
      }

      plan.groups.forEach((group) => {
        const section = el("section", "record-action-section target-swap-group");
        section.dataset.swapGroup = group.key;
        const head = el("label", "target-swap-group-head");
        const box = el("input");
        box.type = "checkbox";
        box.name = "groups";
        box.value = group.key;
        // A group whose values are equal on both targets changes nothing.
        box.checked = group.differs > 0;
        box.disabled = group.differs === 0;
        box.addEventListener("change", syncSubmit);
        const count = group.rows.length === 0
          ? "both empty, nothing to swap"
          : group.differs === 0 ? "identical, nothing to swap" : `${group.differs} ${group.differs === 1 ? "field differs" : "fields differ"}`;
        head.append(box, el("span", "record-action-section-title", group.title), el("span", "target-swap-group-count", count));
        section.append(head);

        if (group.rows.length && group.differs > 0) {
          const wrap = el("div", "record-action-table-wrap");
          const table = el("table", "record-action-table target-swap-table");
          table.setAttribute("data-table-plain", "");
          const thead = el("thead");
          const headRow = el("tr");
          headRow.append(el("th", "", ""), el("th", "", `This target ${plan.this.ref}`), el("th", "target-swap-arrow", ""), el("th", "", `Target ${plan.other.ref}`));
          thead.append(headRow);
          const tbody = el("tbody");
          group.rows.forEach((row) => {
            const tr = el("tr", row.same ? "is-same" : "");
            const value = (text) => (text === null ? el("td", "target-swap-value detail-empty", "—") : el("td", "target-swap-value", text));
            tr.append(el("th", "target-swap-label", row.label), value(row.this), el("td", "target-swap-arrow", row.same ? "=" : "⇄"), value(row.other));
            tbody.append(tr);
          });
          table.append(thead, tbody);
          wrap.append(table);
          section.append(wrap);
        }
        body.append(section);
      });
      syncSubmit();
    };

    const readNumbers = () => {
      const values = numberInputs.map((input) => Number.parseInt(input.value, 10));
      return values.every((value) => Number.isInteger(value) && value > 0) ? values : null;
    };

    const load = async () => {
      const numbers = readNumbers();
      if (!numbers) {
        note("Enter a sample, prep and target number (whole numbers above 0).", "record-action-error");
        return;
      }
      const [sample, prep, target] = numbers;
      preview = null;
      syncSubmit();
      note("Loading both targets …", "record-action-loading");
      const thisRequest = ++requestId;
      const url = `${baseUrl}/swap/preview?with_sample=${sample}&with_prep=${prep}&with_target=${target}`;
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
          note(payload?.error || payload?.detail || `Loading failed (HTTP ${response.status}). Reload the page and try again.`, "record-action-error");
          return;
        }
        preview = payload;
        renderPreview(payload);
      } catch (_error) {
        if (thisRequest !== requestId) return;
        note("The server could not be reached. Check the connection and try again.", "record-action-error");
      }
    };

    const open = () => {
      if (window.SAMSDetailEdit?.hasUnsavedChanges?.()) {
        window.SAMSToast?.show("Save or cancel the unsaved changes on this target first.", "info");
        return;
      }
      setMenu(false);
      preview = null;
      submit.classList.remove("is-saving");
      note("Enter the other target and press Show to compare.");
      syncSubmit();
      if (!dialog.open) dialog.showModal();
      numberInputs[0].focus();
    };

    root.querySelector("[data-target-swap-open]").addEventListener("click", open);
    dialog.querySelectorAll("[data-target-swap-cancel]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    // The record's shortcuts ([ ] j k ?) must not fire under the dialog.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") event.stopPropagation();
    });
    loadButton.addEventListener("click", load);
    numberInputs.forEach((input) => {
      // A changed number makes the comparison stale: Swap waits for Show.
      input.addEventListener("input", () => {
        if (!preview) return;
        preview = null;
        note("The target changed: press Show to compare again.");
        syncSubmit();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        load();
      });
    });

    form.addEventListener("submit", (event) => {
      if (!preview || tickedGroups().length === 0) {
        event.preventDefault();
        return;
      }
      submit.classList.add("is-saving");
      window.setTimeout(() => {
        submit.disabled = true;
      }, 0);
    });

    // ---- #action=swap-target: the command palette's entry -----------------
    const openFromHash = () => {
      if (window.location.hash !== "#action=swap-target") return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      open();
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
  };
})();
