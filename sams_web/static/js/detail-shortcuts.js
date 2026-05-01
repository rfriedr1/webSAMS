// Keyboard shortcuts available within a detail page (sample / preparation /
// target / project / submitter). Activates only when the page contains a
// `[data-edit-scope]` panel — so listing pages, the dashboard, and the lab
// benches don't fight for the same keys.
//
// Bindings:
//   e         → toggle edit mode (click the Edit / Cancel button)
//   Esc       → cancel edit mode (when in edit mode)
//   Ctrl/Cmd+S → submit the edit form
//   [ or j   → previous record (clicks the prev arrow if present)
//   ] or k   → next record
//   ?         → open a shortcuts cheat sheet
//
// All shortcuts are suppressed while typing inside an editable input,
// textarea, or contenteditable element — except Ctrl/Cmd+S, which always
// saves.
(() => {
  const SHORTCUTS = [
    { keys: "e", description: "Toggle edit mode" },
    { keys: "Esc", description: "Cancel edit mode" },
    { keys: "Ctrl/Cmd + S", description: "Save changes" },
    { keys: "[ or j", description: "Open previous record" },
    { keys: "] or k", description: "Open next record" },
    { keys: "?", description: "Show this cheat sheet" },
  ];

  const editScope = () => document.querySelector("[data-edit-scope]");

  const isTyping = (target) => {
    if (!target) return false;
    if (target.isContentEditable) return true;
    const tag = target.tagName ? target.tagName.toLowerCase() : "";
    if (tag === "textarea") return true;
    if (tag === "select") return true;
    if (tag === "input") {
      const type = (target.type || "").toLowerCase();
      const nonText = ["checkbox", "radio", "button", "submit", "reset", "file"];
      return !nonText.includes(type);
    }
    return false;
  };

  const clickPrevArrow = () => {
    const prev = document.querySelector(".sample-quick-nav-link.sample-quick-nav-arrow:first-of-type");
    if (prev && prev.tagName === "A") {
      window.location.assign(prev.href);
    }
  };

  const clickNextArrow = () => {
    const links = document.querySelectorAll(".sample-quick-nav-link.sample-quick-nav-arrow");
    if (links.length >= 2) {
      const next = links[links.length - 1];
      if (next && next.tagName === "A") {
        window.location.assign(next.href);
      }
    }
  };

  const toggleEditMode = () => {
    const scope = editScope();
    if (!scope) return;
    const editButton = scope.querySelector(
      "[data-detail-edit-button-mode='edit'], [data-detail-edit-button], .detail-edit-toggle, button[data-edit-action]"
    );
    if (editButton) {
      editButton.click();
      return;
    }
    // Fallback: toggle the data-edit-mode attribute directly so detail-edit-mode.js
    // can pick it up. Most pages render the Edit button as a generic button
    // labelled "Edit" inside the panel head.
    const buttons = scope.querySelectorAll("button");
    for (const btn of buttons) {
      const label = (btn.textContent || "").trim().toLowerCase();
      if (label === "edit" || label === "cancel" || label === "save" || label === "save changes") {
        btn.click();
        return;
      }
    }
  };

  const cancelEditMode = () => {
    const scope = editScope();
    if (!scope) return;
    if (scope.getAttribute("data-edit-initial-mode") !== "editing"
        && scope.getAttribute("data-edit-mode") !== "editing") {
      return;
    }
    const buttons = scope.querySelectorAll("button");
    for (const btn of buttons) {
      const label = (btn.textContent || "").trim().toLowerCase();
      if (label === "cancel") {
        btn.click();
        return;
      }
    }
  };

  const saveEditForm = () => {
    const scope = editScope();
    if (!scope) return;
    const formId = scope.querySelector("form[data-detail-edit-form]")?.id;
    if (!formId) return;
    const form = document.getElementById(formId);
    if (!form) return;
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      form.submit();
    }
  };

  let cheatSheet = null;

  const closeCheatSheet = () => {
    if (cheatSheet) {
      cheatSheet.remove();
      cheatSheet = null;
    }
  };

  const openCheatSheet = () => {
    if (cheatSheet) return;
    cheatSheet = document.createElement("div");
    cheatSheet.className = "shortcut-cheatsheet";
    cheatSheet.setAttribute("role", "dialog");
    cheatSheet.setAttribute("aria-modal", "true");
    cheatSheet.innerHTML = [
      '<div class="shortcut-cheatsheet-backdrop"></div>',
      '<div class="shortcut-cheatsheet-panel">',
      '<header class="shortcut-cheatsheet-head"><h3>Keyboard Shortcuts</h3>',
      '<button type="button" class="shortcut-cheatsheet-close" aria-label="Close">×</button></header>',
      '<dl class="shortcut-cheatsheet-list">',
      ...SHORTCUTS.map(
        ({ keys, description }) =>
          `<dt><kbd>${keys}</kbd></dt><dd>${description}</dd>`,
      ),
      '</dl>',
      '<p class="shortcut-cheatsheet-hint">Press <kbd>?</kbd> any time to show this list. Shortcuts are suppressed while typing in form fields (except Save).</p>',
      '</div>',
    ].join("");
    document.body.appendChild(cheatSheet);
    cheatSheet.querySelector(".shortcut-cheatsheet-close").addEventListener("click", closeCheatSheet);
    cheatSheet.querySelector(".shortcut-cheatsheet-backdrop").addEventListener("click", closeCheatSheet);
  };

  document.addEventListener("keydown", (event) => {
    // Save (Ctrl/Cmd+S) — always intercept, even when typing in a field.
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      if (!editScope()) return;
      event.preventDefault();
      saveEditForm();
      return;
    }

    if (cheatSheet && event.key === "Escape") {
      event.preventDefault();
      closeCheatSheet();
      return;
    }

    if (isTyping(event.target)) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }

    const key = event.key;
    if (key === "?" || (event.shiftKey && key === "/")) {
      event.preventDefault();
      openCheatSheet();
      return;
    }
    if (!editScope()) return;

    if (key === "e" || key === "E") {
      event.preventDefault();
      toggleEditMode();
      return;
    }
    if (key === "Escape") {
      event.preventDefault();
      cancelEditMode();
      return;
    }
    if (key === "[" || key === "j") {
      event.preventDefault();
      clickPrevArrow();
      return;
    }
    if (key === "]" || key === "k") {
      event.preventDefault();
      clickNextArrow();
      return;
    }
  });
})();
