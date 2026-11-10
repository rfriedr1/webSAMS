// Rename a magazine (Lab → Analysis, ADR-0009): the Actions menu in the
// Magazine panel bar and its dialog. Opening the dialog loads what a rename
// would change, or why the magazine may not be renamed (it was measured).
// The operator types the new name and presses Check (or Enter); only a name
// the server accepted enables Rename, and typing again disables it until the
// next check. Only Rename posts; the server checks everything again.
//
//   [data-magazine-actions]        root (from _magazine_actions.html), data-magazine
//   [data-magazine-rename-open]    menu entry; #action=rename-magazine opens it too
//   [data-magazine-rename-name]    the new name (posted)
//   [data-magazine-rename-body]    preview, built here with textContent only
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  installers.installMagazineRename = () => {
    const root = document.querySelector("[data-magazine-actions]");
    if (!root) return;

    const magazine = root.dataset.magazine;
    const toggle = root.querySelector("[data-magazine-actions-toggle]");
    const menu = root.querySelector("[data-magazine-actions-menu]");
    const dialog = root.querySelector("[data-magazine-rename-dialog]");
    const form = dialog.querySelector("[data-magazine-rename-form]");
    const body = dialog.querySelector("[data-magazine-rename-body]");
    const nameInput = dialog.querySelector("[data-magazine-rename-name]");
    const checkButton = dialog.querySelector("[data-magazine-rename-check]");
    const submit = dialog.querySelector("[data-magazine-rename-submit]");
    let accepted = null; // the name the server last accepted
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
    const syncSubmit = () => {
      const ready = accepted !== null && nameInput.value.trim() === accepted;
      submit.disabled = !ready;
      submit.textContent = ready ? `Rename to ${accepted}` : "Rename";
    };

    const renderPreview = (plan) => {
      body.textContent = "";
      if (plan.blocked.length) {
        nameInput.disabled = true;
        checkButton.disabled = true;
        const box = el("div", "record-action-error");
        box.append(el("p", "", `Magazine ${plan.magazine} was measured, so it cannot be renamed here.`));
        const list = el("ul", "");
        plan.blocked.forEach((reason) => list.append(el("li", "", reason)));
        box.append(list);
        body.append(box);
        return;
      }
      nameInput.disabled = false;
      checkButton.disabled = false;

      const title = el("p", "record-action-section-title", "What changes");
      const list = el("ul", "magazine-rename-changes");
      plan.changes.forEach((change) => {
        const item = el("li", "");
        item.append(el("span", "count", change.count), document.createTextNode(` ${change.label} `), el("code", "", change.table));
        list.append(item);
      });
      body.append(title, list);

      if (plan.error) body.append(el("p", "record-action-error", plan.error));
      else if (plan.new_name) body.append(el("p", "record-action-ok", `✓ ${plan.new_name} is free. Rename writes it into every table above.`));
    };

    const load = async (withName) => {
      const name = nameInput.value.trim();
      const params = new URLSearchParams({ magazine });
      if (withName) params.set("new_name", name);
      accepted = null;
      syncSubmit();
      const thisRequest = ++requestId;
      try {
        const response = await fetch(`/lab/analysis/magazine/rename/preview?${params}`, { headers: { Accept: "application/json" } });
        if (thisRequest !== requestId) return;
        let payload = null;
        try {
          payload = await response.json();
        } catch (_error) {
          payload = null;
        }
        if (!response.ok) {
          body.textContent = "";
          body.append(el("p", "record-action-error", payload?.error || payload?.detail || `Loading failed (HTTP ${response.status}). Reload the page and try again.`));
          return;
        }
        renderPreview(payload);
        if (withName && payload.new_name && nameInput.value.trim() === payload.new_name) accepted = payload.new_name;
        syncSubmit();
      } catch (_error) {
        if (thisRequest !== requestId) return;
        body.textContent = "";
        body.append(el("p", "record-action-error", "The server could not be reached. Check the connection and try again."));
      }
    };

    const check = () => {
      if (!nameInput.value.trim()) {
        nameInput.focus();
        return;
      }
      load(true);
    };

    const open = () => {
      setMenu(false);
      accepted = null;
      nameInput.value = "";
      submit.classList.remove("is-saving");
      body.textContent = "";
      body.append(el("p", "record-action-loading", "Loading the magazine …"));
      syncSubmit();
      if (!dialog.open) dialog.showModal();
      nameInput.focus();
      load(false);
    };

    root.querySelector("[data-magazine-rename-open]").addEventListener("click", open);
    dialog.querySelectorAll("[data-magazine-rename-cancel]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    // Page shortcuts must not fire under the dialog.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") event.stopPropagation();
    });
    checkButton.addEventListener("click", check);
    nameInput.addEventListener("input", syncSubmit);
    nameInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      // Enter on a name already accepted renames; otherwise it checks.
      if (!submit.disabled) form.requestSubmit(submit);
      else check();
    });

    form.addEventListener("submit", (event) => {
      if (accepted === null || nameInput.value.trim() !== accepted) {
        event.preventDefault();
        return;
      }
      submit.classList.add("is-saving");
      window.setTimeout(() => {
        submit.disabled = true;
      }, 0);
    });

    // ---- #action=rename-magazine: the command palette's entry -------------
    const openFromHash = () => {
      if (window.location.hash !== "#action=rename-magazine") return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      open();
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
  };
})();
