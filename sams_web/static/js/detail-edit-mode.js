// Click-to-edit for detail pages (sample, preparation, target, project,
// submitter). There is no edit mode: an editable value opens in place when
// it is clicked (or reached with Tab), changes pile up across as many
// fields as the user likes, and the pending-changes bar at the foot of the
// record saves or drops them all together.
//
//   - A row is editable when the server rendered an editor for it
//     (`[data-field-editor]`), i.e. the field is not read-only and the user
//     may edit records (sams_web/access.py → `can_edit`).
//   - An unchanged field closes again when focus leaves it; a changed one
//     stays open with its dirty dot, so every pending edit stays in view.
//   - Esc inside an open field reverts that field.
//   - Save posts only the changed fields: every unchanged control is
//     disabled just before submit, and `apply_detail_update` leaves fields
//     it did not receive untouched.
//   - After a rejected save (422) the server renders the submitted values
//     with `data-initial-value` = the stored value, so the edits come back
//     still dirty and still open.
//
// `window.SAMSDetailEdit` lets detail-shortcuts.js ask before navigating
// away from unsaved edits and save with Ctrl/Cmd+S.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  // -------- Form-error summary: scroll first error into view ----------
  //
  // After a failed save the server re-renders the page with field errors
  // in red AND a banner at the top listing each one. On a long detail
  // page the failing field may be below the fold, so we both (a) open
  // any collapsibles that contain a failing field and (b) scroll the
  // first one into view. Clicking an entry in the summary also opens
  // the collapsible and scrolls.
  installers.installFieldErrorSummary = () => {
    const summary = document.querySelector("[data-field-error-summary]");
    if (!summary) return;

    const expandAncestors = (el) => {
      let parent = el?.parentElement;
      while (parent) {
        if (parent.tagName === "DETAILS" && !parent.open) {
          parent.open = true;
        }
        parent = parent.parentElement;
      }
    };

    const scrollToField = (fieldId) => {
      const target = document.getElementById(fieldId);
      if (!target) return;
      expandAncestors(target);
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      // Brief outline pulse so it's obvious where we landed.
      target.classList.add("is-error-flash");
      setTimeout(() => target.classList.remove("is-error-flash"), 1400);
    };

    const firstLink = summary.querySelector("a[data-field-error-jump]");
    if (firstLink) {
      const entity = firstLink.dataset.entity || "";
      const fieldKey = firstLink.dataset.fieldErrorJump || "";
      window.setTimeout(() => scrollToField(`field-${entity}-${fieldKey}`), 80);
    }

    summary.querySelectorAll("a[data-field-error-jump]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const entity = a.dataset.entity || "";
        const fieldKey = a.dataset.fieldErrorJump || "";
        scrollToField(`field-${entity}-${fieldKey}`);
      });
    });
  };

  // -------- In-app "discard / save / keep editing" modal --------------
  //
  // Resolves to "discard" | "save" | "keep". Asked before leaving the
  // record with unsaved edits, and by Cancel when several fields changed.
  let modalOpen = false;
  const openDirtyChoiceModal = ({ body, discardLabel } = {}) =>
    new Promise((resolve) => {
      modalOpen = true;
      const overlay = document.createElement("section");
      overlay.className = "shortcut-cheatsheet dirty-confirm-overlay";
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-label", "Unsaved changes");
      overlay.innerHTML = `
        <button type="button" class="shortcut-cheatsheet-backdrop" data-dirty-choice="keep" aria-label="Keep editing"></button>
        <div class="shortcut-cheatsheet-panel dirty-confirm-panel">
          <div class="shortcut-cheatsheet-head">
            <h3>Unsaved changes</h3>
            <button type="button" class="shortcut-cheatsheet-close" data-dirty-choice="keep" aria-label="Keep editing">×</button>
          </div>
          <p class="dirty-confirm-body"></p>
          <div class="dirty-confirm-actions">
            <button type="button" class="dirty-confirm-discard" data-dirty-choice="discard"></button>
            <button type="button" class="dirty-confirm-save" data-dirty-choice="save">Save changes</button>
            <button type="button" class="dirty-confirm-keep" data-dirty-choice="keep">Keep editing</button>
          </div>
          <p class="shortcut-cheatsheet-hint">Esc keeps editing. Enter saves.</p>
        </div>`;
      overlay.querySelector(".dirty-confirm-body").textContent =
        body || "You have unsaved edits. What would you like to do?";
      overlay.querySelector(".dirty-confirm-discard").textContent = discardLabel || "Discard changes";
      document.body.appendChild(overlay);
      const cleanup = (choice) => {
        document.removeEventListener("keydown", onKey, true);
        overlay.remove();
        modalOpen = false;
        resolve(choice);
      };
      // Capture phase + stopPropagation: no other shortcut may fire (or
      // open a second modal) while this one is up.
      const onKey = (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          ev.stopPropagation();
          cleanup("keep");
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          ev.stopPropagation();
          cleanup("save");
        } else if (ev.key !== "Tab") {
          ev.stopPropagation();
        }
      };
      document.addEventListener("keydown", onKey, true);
      overlay.querySelectorAll("[data-dirty-choice]").forEach((btn) => {
        btn.addEventListener("click", () => cleanup(btn.dataset.dirtyChoice));
      });
      overlay.querySelector(".dirty-confirm-keep")?.focus();
    });

  // -------- Relative-time formatter for the saved-hint ----------------
  const formatSavedAge = (savedAtMs) => {
    const diffSec = Math.max(0, Math.round((Date.now() - savedAtMs) / 1000));
    if (diffSec < 5) return "Saved · just now";
    if (diffSec < 60) return `Saved · ${diffSec} s ago`;
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `Saved · ${diffMin} min ago`;
    const diffHr = Math.round(diffMin / 60);
    return `Saved · ${diffHr} h ago`;
  };

  const isToggle = (control) =>
    control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio");

  const controlsOf = (editor) => Array.from(editor.querySelectorAll("input, select, textarea"));
  // The controls that are posted. Change tracking looks only at these: the
  // searchable-select combobox has no name, and its filter text is not a
  // change until an option is picked into the native <select>.
  const valueControlsOf = (editor) => controlsOf(editor).filter((control) => control.name);

  // The control a user types into: the searchable-select combobox when the
  // native <select> was enhanced (the native one is visually hidden).
  const visibleControl = (editor) =>
    controlsOf(editor).find(
      (control) => !control.classList.contains("searchable-select-native") && control.getClientRects().length > 0,
    ) || controlsOf(editor)[0];

  installers.installDetailEditMode = () => {
    const scope = document.querySelector("[data-edit-scope]");
    if (!scope || scope.dataset.editModeInstalled === "true") return;
    scope.dataset.editModeInstalled = "true";

    const statusHost = scope.querySelector("[data-edit-status]");
    const bar = scope.querySelector("[data-pending-bar]");
    const barCount = bar?.querySelector("[data-pending-count]");
    const saveButton = bar?.querySelector("[data-edit-save]");
    const cancelButton = bar?.querySelector("[data-edit-cancel]");
    const saveFormId = saveButton?.getAttribute("form");
    const saveForm =
      (saveFormId ? document.getElementById(saveFormId) : null) ||
      scope.querySelector("form[data-detail-edit-form]");

    const items = Array.from(scope.querySelectorAll("[data-field-key]"))
      .map((row) => ({
        row,
        display: row.querySelector("[data-field-display]"),
        editor: row.querySelector("[data-field-editor]"),
      }))
      .filter((item) => item.display && item.editor);

    // -------- Saved-hint (header pill) --------------------------------
    // The server redirects to `?saved=true` after a successful save; the
    // toast module strips that param after promoting it to a toast. Read
    // it here first (both run on DOMContentLoaded).
    let savedAt = null;
    let savedTickId = null;
    const renderSavedHint = () => {
      if (!statusHost) return;
      const show = savedAt !== null && !scope.classList.contains("has-unsaved-changes");
      statusHost.hidden = !show;
      statusHost.classList.toggle("is-saved", show);
      statusHost.textContent = show ? formatSavedAge(savedAt) : "";
    };
    const savedKeys = ["saved", "bench_saved", "graph_saved", "graph_batch_saved"];
    const url = new URL(window.location.href);
    if (savedKeys.some((k) => url.searchParams.get(k) === "true")) {
      savedAt = Date.now();
      savedTickId = window.setInterval(renderSavedHint, 30000);
    }

    if (items.length === 0) {
      // View-only user, or a record without editable fields.
      renderSavedHint();
      return;
    }
    items.forEach((item) => item.row.classList.add("is-editable-field"));

    // The value each control is measured against. The server renders
    // `data-initial-value` (the stored value) on every named control, so
    // after a rejected save the submitted values still count as changes.
    // Controls without it (the searchable-select combobox) take their
    // current state.
    items.forEach((item) => {
      valueControlsOf(item.editor).forEach((control) => {
        if (isToggle(control)) {
          if (control.dataset.initialChecked === undefined) {
            control.dataset.initialChecked = control.checked ? "1" : "0";
          }
        } else if (control.dataset.initialValue === undefined) {
          control.dataset.initialValue = control.value;
        }
      });
    });

    const isControlDirty = (control) => {
      if (isToggle(control)) {
        return (control.dataset.initialChecked === "1") !== control.checked;
      }
      return (control.dataset.initialValue || "") !== control.value;
    };
    const isItemDirty = (item) => valueControlsOf(item.editor).some(isControlDirty);
    const dirtyItems = () => items.filter(isItemDirty);
    const hasUnsavedChanges = () => items.some(isItemDirty);

    const renderBar = () => {
      const n = dirtyItems().length;
      scope.classList.toggle("has-unsaved-changes", n > 0);
      if (bar) {
        bar.hidden = n === 0;
        if (barCount) {
          barCount.textContent = `${n} unsaved change${n === 1 ? "" : "s"}`;
        }
      }
      renderSavedHint();
    };

    const updateDirtyMarkers = () => {
      items.forEach((item) => item.row.classList.toggle("is-dirty", isItemDirty(item)));
      renderBar();
    };

    // -------- Opening and closing one field ---------------------------
    const isOpen = (item) => item.row.classList.contains("is-open");

    const openItem = (item, { focus = true } = {}) => {
      if (scope.classList.contains("is-saving")) return;
      if (!isOpen(item)) {
        item.row.classList.add("is-open");
        item.display.hidden = true;
        item.display.setAttribute("aria-hidden", "true");
        item.editor.hidden = false;
        item.editor.setAttribute("aria-hidden", "false");
        controlsOf(item.editor).forEach((control) => {
          control.disabled = false;
        });
      }
      if (!focus) return;
      const control = visibleControl(item.editor);
      if (!control) return;
      control.focus();
      if (control instanceof HTMLInputElement && !isToggle(control) && control.type !== "date") {
        control.select?.();
      } else if (control instanceof HTMLTextAreaElement) {
        // Comments are added to more often than replaced: caret at the end.
        control.setSelectionRange(control.value.length, control.value.length);
      }
    };

    const closeItem = (item) => {
      if (!isOpen(item)) return;
      // Drop filter text typed into a searchable-select combobox without
      // picking an option: it re-reads its native <select> on "change".
      item.editor.querySelectorAll("select").forEach((select) => {
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      item.row.classList.remove("is-open");
      item.display.hidden = false;
      item.display.setAttribute("aria-hidden", "false");
      item.editor.hidden = true;
      item.editor.setAttribute("aria-hidden", "true");
      controlsOf(item.editor).forEach((control) => {
        control.disabled = true;
      });
    };

    // A field stays open while it holds a change or an error: closing it
    // would show the old display value next to a pending edit.
    const mayClose = (item) => !isItemDirty(item) && !item.row.querySelector(".has-error");

    const revertItem = (item) => {
      valueControlsOf(item.editor).forEach((control) => {
        if (isToggle(control)) {
          control.checked = control.dataset.initialChecked === "1";
        } else {
          control.value = control.dataset.initialValue || "";
          // Let a searchable-select combobox re-read its native select.
          if (control instanceof HTMLSelectElement) {
            control.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
      });
    };

    const discardAll = () => {
      items.forEach((item) => {
        revertItem(item);
        closeItem(item);
      });
      updateDirtyMarkers();
    };

    let refocusing = false;
    items.forEach((item) => {
      const { row, display, editor } = item;
      // Focusable so Tab walks the fields. No role="button": a display may
      // hold a link (e-mail, website, related record).
      display.tabIndex = 0;

      display.addEventListener("click", (ev) => {
        // A link inside the value (e-mail, website, related record) keeps
        // working; dragging to select text copies without opening.
        if (ev.target.closest("a")) return;
        const selection = window.getSelection?.();
        if (selection && !selection.isCollapsed && display.contains(selection.anchorNode)) return;
        openItem(item);
      });
      // Tab walks the fields: a display reached by keyboard opens. A mouse
      // press focuses it too, but must not open before the click (that
      // would make selecting text impossible), hence :focus-visible.
      display.addEventListener("focus", () => {
        if (refocusing) return;
        if (display.matches(":focus-visible")) openItem(item);
      });
      display.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openItem(item);
        }
      });

      row.addEventListener("focusout", () => {
        window.setTimeout(() => {
          if (row.contains(document.activeElement)) return;
          if (mayClose(item)) closeItem(item);
        }, 120);
      });

      editor.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          ev.stopPropagation();
          revertItem(item);
          updateDirtyMarkers();
          closeItem(item);
          // Keep the keyboard user in place without re-opening the field.
          refocusing = true;
          display.focus({ preventScroll: true });
          refocusing = false;
          return;
        }
        if (ev.key === "Enter") {
          const target = ev.target;
          if (target instanceof HTMLTextAreaElement) {
            if (ev.ctrlKey || ev.metaKey) {
              ev.preventDefault();
              save();
            }
            return;
          }
          if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement) {
            // Enter confirms the field, it does not submit the record:
            // the edits are saved together from the bar.
            if (target.classList.contains("searchable-select-input")) return;
            ev.preventDefault();
            target.blur();
          }
        }
      });

      controlsOf(editor).forEach((control) => {
        control.addEventListener("input", updateDirtyMarkers);
        control.addEventListener("change", updateDirtyMarkers);
      });
    });

    // -------- Save / Cancel -------------------------------------------
    let submitting = false;

    const save = () => {
      if (!saveForm || !hasUnsavedChanges() || submitting) return;
      saveForm.requestSubmit ? saveForm.requestSubmit(saveButton || undefined) : saveForm.submit();
    };

    if (saveForm) {
      saveForm.addEventListener("submit", (ev) => {
        if (!hasUnsavedChanges()) {
          ev.preventDefault();
          return;
        }
        submitting = true;
        // Only the changed fields travel: a disabled control is not posted.
        items.forEach((item) => {
          const dirty = isItemDirty(item);
          valueControlsOf(item.editor).forEach((control) => {
            control.disabled = !(dirty && isControlDirty(control));
          });
        });
        scope.classList.add("is-saving");
        if (cancelButton) cancelButton.disabled = true;
        if (saveButton) {
          saveButton.disabled = true;
          saveButton.classList.add("is-saving");
          saveButton.textContent = "Saving";
        }
      });
    }

    cancelButton?.addEventListener("click", async () => {
      if (dirtyItems().length > 1) {
        const choice = await openDirtyChoiceModal({
          body: `Discard all ${dirtyItems().length} unsaved changes on this record?`,
          discardLabel: "Discard all",
        });
        if (choice === "keep") return;
        if (choice === "save") {
          save();
          return;
        }
      }
      discardAll();
    });

    // -------- Leaving the record with unsaved edits -------------------
    window.addEventListener("beforeunload", (event) => {
      if (submitting || !hasUnsavedChanges()) return;
      event.preventDefault();
      event.returnValue = "";
    });

    let leaving = false;
    const leaveTo = async (href) => {
      if (!hasUnsavedChanges()) {
        window.location.assign(href);
        return;
      }
      if (modalOpen) return;
      const choice = await openDirtyChoiceModal({
        body: "This record has unsaved changes. Save them before you leave?",
      });
      if (choice === "save") {
        save();
      } else if (choice === "discard") {
        leaving = true;
        discardAll();
        window.location.assign(href);
      }
    };

    // Same-tab links anywhere on the page ask through the in-app modal
    // instead of the browser's bare "Leave site?" prompt.
    document.addEventListener("click", (ev) => {
      if (leaving || !hasUnsavedChanges()) return;
      if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      const link = ev.target.closest?.("a[href]");
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      if (link.closest("[data-field-display]")) return; // mailto / website inside a value
      const href = link.getAttribute("href") || "";
      if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("javascript:")) return;
      ev.preventDefault();
      leaveTo(link.href);
    });

    // Rows that come back dirty or with an error (rejected save) start open.
    items.forEach((item) => {
      if (!mayClose(item)) openItem(item, { focus: false });
    });
    updateDirtyMarkers();

    window.SAMSDetailEdit = {
      hasUnsavedChanges,
      isModalOpen: () => modalOpen,
      save,
      leaveTo,
    };
  };
})();
