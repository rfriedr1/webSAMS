// Keyboard shortcuts available within a detail page (sample / preparation /
// target / project / submitter). Activates only when the page contains a
// `[data-edit-scope]` panel — so listing pages, the dashboard, and the lab
// benches don't fight for the same keys.
//
// Bindings:
//   Ctrl/Cmd+S → save the pending edits (no edit mode: fields open on
//                click, see detail-edit-mode.js; Esc inside a field
//                reverts it, handled there)
//   [ or j   → previous record (clicks the prev arrow if present)
//   ] or k   → next record
//   ?         → open a shortcuts cheat sheet
//
// All shortcuts are suppressed while typing inside an editable input,
// textarea, or contenteditable element — except Ctrl/Cmd+S, which always
// saves.
(() => {
  const SHORTCUTS = [
    { keys: "Click or Tab", description: "Open a field to change it" },
    { keys: "Esc", description: "Undo the change in the open field" },
    { keys: "Ctrl/Cmd + S", description: "Save all changes" },
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

  // The record header's ‹ › arrows carry `data-quick-nav="prev|next"`
  // (`render_detail_quick_nav` in _detail_chrome.html). A data hook, not a
  // class: the arrows were renamed in the 2026-11 redesign and a class
  // selector here silently stopped matching.
  const followQuickNav = (direction) => {
    const link = document.querySelector(`a[data-quick-nav="${direction}"]`);
    if (!link) return;
    // Unsaved edits: ask first (Discard / Save / Keep editing).
    if (window.SAMSDetailEdit) {
      window.SAMSDetailEdit.leaveTo(link.href);
    } else {
      window.location.assign(link.href);
    }
  };

  const clickPrevArrow = () => followQuickNav("prev");
  const clickNextArrow = () => followQuickNav("next");

  // Ctrl/Cmd+S saves the pending edits (detail-edit-mode.js); without
  // any it does nothing rather than posting an empty form.
  const saveEdits = () => window.SAMSDetailEdit?.save();

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
    // The unsaved-changes modal owns the keyboard while it is open.
    if (window.SAMSDetailEdit?.isModalOpen()) return;
    // Save (Ctrl/Cmd+S) — always intercept, even when typing in a field.
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      if (!editScope()) return;
      event.preventDefault();
      saveEdits();
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
