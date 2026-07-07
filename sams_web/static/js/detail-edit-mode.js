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

    // Auto-scroll once when the page first lands with errors.
    const firstLink = summary.querySelector("a[data-field-error-jump]");
    if (firstLink) {
      const entity = firstLink.dataset.entity || "";
      const fieldKey = firstLink.dataset.fieldErrorJump || "";
      // Defer slightly so layout settles after the page paints.
      window.setTimeout(() => scrollToField(`field-${entity}-${fieldKey}`), 80);
    }

    // Click handlers on each summary link.
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
  // Replaces the native `window.confirm("…")` that used to prompt when
  // the user clicked Cancel / Esc / Edit-again on a dirty record. The
  // native dialog was visually jarring and offered only OK / Cancel —
  // no way to "save first". This builds a Promise-based modal that
  // resolves to "discard" | "save" | "keep" so callers can choose.
  const openDirtyChoiceModal = () =>
    new Promise((resolve) => {
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
          <p class="dirty-confirm-body">You have unsaved edits. What would you like to do?</p>
          <div class="dirty-confirm-actions">
            <button type="button" class="dirty-confirm-discard" data-dirty-choice="discard">Discard changes</button>
            <button type="button" class="dirty-confirm-save" data-dirty-choice="save">Save changes</button>
            <button type="button" class="dirty-confirm-keep" data-dirty-choice="keep">Keep editing</button>
          </div>
          <p class="shortcut-cheatsheet-hint">Esc keeps editing. Enter saves.</p>
        </div>`;
      document.body.appendChild(overlay);
      const cleanup = (choice) => {
        document.removeEventListener("keydown", onKey);
        overlay.remove();
        resolve(choice);
      };
      const onKey = (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          cleanup("keep");
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          cleanup("save");
        }
      };
      document.addEventListener("keydown", onKey);
      overlay.querySelectorAll("[data-dirty-choice]").forEach((btn) => {
        btn.addEventListener("click", () => cleanup(btn.dataset.dirtyChoice));
      });
      // Focus the safe default (Keep editing) so Enter via screen reader
      // doesn't immediately discard.
      overlay.querySelector(".dirty-confirm-keep")?.focus();
    });

  // -------- Relative-time formatter for the saved-hint ----------------
  //
  // Used to render "Saved · just now" → "Saved · 12 s ago" → "Saved · 2
  // min ago" etc. without a date library. Crude but adequate for the
  // sub-hour window where this hint is meaningful.
  const formatSavedAge = (savedAtMs) => {
    const diffSec = Math.max(0, Math.round((Date.now() - savedAtMs) / 1000));
    if (diffSec < 5) return "Saved · just now";
    if (diffSec < 60) return `Saved · ${diffSec} s ago`;
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `Saved · ${diffMin} min ago`;
    const diffHr = Math.round(diffMin / 60);
    return `Saved · ${diffHr} h ago`;
  };

  installers.installDetailEditMode = () => {
    const scopes = document.querySelectorAll("[data-edit-scope]");
    scopes.forEach((scope) => {
      if (scope.dataset.editModeInstalled === "true") {
        return;
      }

      const toggleButton = scope.querySelector("[data-edit-toggle]");
      const cancelButton = scope.querySelector("[data-edit-cancel]");
      const saveButton = scope.querySelector("[data-edit-save]");
      const statusHost = scope.querySelector("[data-edit-status]");
      const saveFormId = saveButton?.getAttribute("form");
      const saveForm =
        (saveFormId ? document.getElementById(saveFormId) : null) ||
        scope.querySelector("form[data-detail-edit-form]");
      if (!toggleButton || !cancelButton) {
        return;
      }

      const rows = Array.from(scope.querySelectorAll("[data-field-key]")).map((row) => ({
        row,
        display: row.querySelector("[data-field-display]"),
        editor: row.querySelector("[data-field-editor]"),
      }));
      const validRows = rows.filter((item) => item.display && item.editor);
      if (validRows.length === 0) {
        return;
      }
      validRows.forEach((item) => {
        item.row.classList.add("is-editable-field");
      });

      const allControls = validRows.flatMap((item) =>
        Array.from(item.editor.querySelectorAll("input, select, textarea")),
      );

      const rememberInitialControlState = (control) => {
        if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
          control.dataset.initialChecked = control.checked ? "1" : "0";
          return;
        }
        if ("value" in control) {
          control.dataset.initialValue = control.value;
        }
      };

      validRows.forEach((item) => {
        const controls = item.editor.querySelectorAll("input, select, textarea");
        controls.forEach((control) => rememberInitialControlState(control));
      });

      let editing = false;
      let suppressBeforeUnload = false;
      let savedAt = null; // ms timestamp set when the page loads after a save
      let savedTickId = null;
      const defaultLabel = toggleButton.dataset.editLabelDefault || "Edit";
      const activeLabel = toggleButton.dataset.editLabelActive || "View";
      // Tooltip strings (see _detail_chrome.html). Kept in sync with the
      // button's label so a hover always describes the *next* action,
      // not the past one.
      const defaultTitle =
        toggleButton.dataset.editTitleDefault ||
        toggleButton.getAttribute("title") ||
        "Edit this record";
      const activeTitle =
        toggleButton.dataset.editTitleActive ||
        "Leave edit mode";

      const isControlDirty = (control) => {
        if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
          return (control.dataset.initialChecked === "1") !== control.checked;
        }
        if ("value" in control) {
          return (control.dataset.initialValue || "") !== control.value;
        }
        return false;
      };

      const countDirtyRows = () =>
        validRows.reduce((acc, item) => {
          const controls = Array.from(item.editor.querySelectorAll("input, select, textarea"));
          return acc + (controls.some(isControlDirty) ? 1 : 0);
        }, 0);

      const hasUnsavedChanges = () => allControls.some(isControlDirty);

      // -------- Status host: dirty count OR saved-hint ----------------
      // The same DOM node alternates between two messages depending on
      // state: in edit mode with dirty fields it shows "N field(s)
      // changed"; outside edit mode after a save it shows "Saved · …".
      // Either mode beats silence; together they replace save anxiety
      // with calm confidence.
      const renderStatus = () => {
        if (!statusHost) return;
        if (editing) {
          const n = countDirtyRows();
          if (n === 0) {
            statusHost.hidden = true;
            statusHost.textContent = "";
            statusHost.classList.remove("is-dirty", "is-saved");
            return;
          }
          statusHost.hidden = false;
          statusHost.classList.add("is-dirty");
          statusHost.classList.remove("is-saved");
          statusHost.textContent = `${n} field${n === 1 ? "" : "s"} changed`;
          return;
        }
        if (savedAt !== null) {
          statusHost.hidden = false;
          statusHost.classList.add("is-saved");
          statusHost.classList.remove("is-dirty");
          statusHost.textContent = formatSavedAge(savedAt);
          return;
        }
        statusHost.hidden = true;
        statusHost.textContent = "";
        statusHost.classList.remove("is-dirty", "is-saved");
      };

      const updateDirtyMarkers = () => {
        validRows.forEach((item) => {
          const controls = Array.from(item.editor.querySelectorAll("input, select, textarea"));
          const rowDirty = controls.some(isControlDirty);
          item.row.classList.toggle("is-dirty", rowDirty);
        });
        scope.classList.toggle("has-unsaved-changes", hasUnsavedChanges());
        renderStatus();
      };

      // -------- Dirty-cancel confirmation via in-app modal ------------
      const confirmDiscardChanges = async () => {
        if (!hasUnsavedChanges()) return "discard";
        const choice = await openDirtyChoiceModal();
        if (choice === "save") {
          // Trigger the form's submit handler so we run the same
          // saving/disabling code path as a Save click.
          if (saveForm) {
            saveForm.requestSubmit ? saveForm.requestSubmit(saveButton) : saveForm.submit();
          }
        }
        return choice; // "discard" | "save" | "keep"
      };

      const applyState = (isEditing) => {
        editing = isEditing;
        scope.classList.toggle("is-editing", editing);
        toggleButton.textContent = editing ? activeLabel : defaultLabel;
        toggleButton.setAttribute("title", editing ? activeTitle : defaultTitle);
        toggleButton.setAttribute("aria-label", editing ? activeLabel : defaultLabel);
        toggleButton.setAttribute("aria-pressed", editing ? "true" : "false");
        cancelButton.hidden = !editing;
        if (saveButton) {
          saveButton.hidden = !editing;
        }

        validRows.forEach((item) => {
          item.display.hidden = editing;
          item.display.setAttribute("aria-hidden", editing ? "true" : "false");
          item.editor.hidden = !editing;
          item.editor.setAttribute("aria-hidden", editing ? "false" : "true");
          const controls = item.editor.querySelectorAll("input, select, textarea");
          controls.forEach((control) => {
            if (control.dataset.readonly === "1") {
              control.disabled = true;
              return;
            }
            control.disabled = !editing;
          });
        });
        if (!editing) {
          validRows.forEach((item) => item.row.classList.remove("is-dirty"));
          scope.classList.remove("has-unsaved-changes");
        }
        renderStatus();
        if (editing) updateDirtyMarkers();
      };

      const resetEditors = () => {
        validRows.forEach((item) => {
          const controls = item.editor.querySelectorAll("input, select, textarea");
          controls.forEach((control) => {
            if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
              control.checked = control.dataset.initialChecked === "1";
              return;
            }
            if ("value" in control) {
              control.value = control.dataset.initialValue || "";
            }
          });
        });
        updateDirtyMarkers();
      };

      allControls.forEach((control) => {
        const syncDirty = () => updateDirtyMarkers();
        control.addEventListener("input", syncDirty);
        control.addEventListener("change", syncDirty);
      });

      toggleButton.addEventListener("click", async () => {
        if (editing) {
          const choice = await confirmDiscardChanges();
          if (choice === "keep") return;
          if (choice === "save") return; // form submit handles the rest
          resetEditors();
          applyState(false);
          return;
        }
        applyState(true);
      });

      cancelButton.addEventListener("click", async () => {
        const choice = await confirmDiscardChanges();
        if (choice === "keep") return;
        if (choice === "save") return;
        resetEditors();
        applyState(false);
      });

      if (saveForm) {
        saveForm.addEventListener("submit", () => {
          suppressBeforeUnload = true;
          scope.classList.add("is-saving");
          toggleButton.disabled = true;
          cancelButton.disabled = true;
          if (saveButton) {
            saveButton.disabled = true;
            saveButton.classList.add("is-saving");
            if (!saveButton.dataset.defaultLabel) {
              saveButton.dataset.defaultLabel = saveButton.textContent || "Save";
            }
            saveButton.textContent = "Saving";
          }
        });
      }

      window.addEventListener("beforeunload", (event) => {
        if (!editing || suppressBeforeUnload || !hasUnsavedChanges()) {
          return;
        }
        event.preventDefault();
        event.returnValue = "";
      });

      scope.addEventListener("keydown", async (event) => {
        if (!editing) {
          return;
        }
        if (event.key === "Enter") {
          const target = event.target;
          if (
            target instanceof HTMLInputElement ||
            target instanceof HTMLSelectElement
          ) {
            event.preventDefault();
            target.blur();
            return;
          }
        }
        if (event.key === "Escape") {
          event.preventDefault();
          const choice = await confirmDiscardChanges();
          if (choice === "keep") return;
          if (choice === "save") return;
          resetEditors();
          applyState(false);
        }
      });

      // -------- Saved-hint bootstrap ---------------------------------
      // The server redirects to `?saved=true` after a successful save;
      // the toast module strips that param after promoting it to a
      // toast. Here we read it before the strip happens (the toast
      // module fires on DOMContentLoaded too — we both run then) and
      // record the timestamp so the relative-time hint can persist.
      const url = new URL(window.location.href);
      const savedKeys = ["saved", "bench_saved", "graph_saved", "graph_batch_saved"];
      const savedHit = savedKeys.some((k) => url.searchParams.get(k) === "true");
      if (savedHit) {
        savedAt = Date.now();
      }
      renderStatus();
      // Re-render the relative time every 30 s so "just now" → "30 s"
      // → "1 min" ages in place without a page reload.
      if (savedAt !== null) {
        savedTickId = window.setInterval(() => {
          if (editing) return; // dirty status takes priority
          renderStatus();
        }, 30000);
      }
      // Editing voids the saved-hint — once the user starts changing
      // values again, "Saved" stops being the relevant message.
      allControls.forEach((control) => {
        control.addEventListener("input", () => {
          savedAt = null;
          if (savedTickId !== null) {
            window.clearInterval(savedTickId);
            savedTickId = null;
          }
        });
      });

      // -------- Per-field double-click "quick edit" -------------------
      //
      // Double-clicking a field's display value swaps just that field
      // into its editor, while the rest of the page stays in view mode.
      // Commits on Enter / blur (or Ctrl+Enter for textareas), reverts
      // on Esc. Cheap for the common case "I just want to fix this one
      // date" — no need to enter full edit mode, change the field, then
      // hunt for Save / Cancel. The full Edit button stays for batch
      // edits across many fields in one pass.
      //
      // When the scope is already in full edit mode this gesture is
      // disabled (the field is already an editor — double-clicking text
      // inside an input is the standard "select word" gesture and we
      // shouldn't hijack it).
      let activeQuickEdit = null;

      const exitQuickEdit = (commit) => {
        if (!activeQuickEdit) return;
        const { item, control, initialValue, initialChecked } = activeQuickEdit;
        if (!commit) {
          // Revert and tear down.
          if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
            control.checked = initialChecked;
          } else if ("value" in control) {
            control.value = initialValue;
          }
        }
        item.display.hidden = false;
        item.display.setAttribute("aria-hidden", "false");
        item.editor.hidden = true;
        item.editor.setAttribute("aria-hidden", "true");
        control.disabled = true;
        item.row.classList.remove("is-quick-editing");
        activeQuickEdit = null;
      };

      const commitQuickEdit = () => {
        if (!activeQuickEdit) return;
        const { control, initialValue, initialChecked } = activeQuickEdit;
        const changed =
          control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")
            ? control.checked !== initialChecked
            : ("value" in control && control.value !== initialValue);
        if (!changed) {
          exitQuickEdit(false);
          return;
        }
        // Submit the form — the disabled inputs of every OTHER field stay
        // out of the form submission, so the server receives just the
        // single edited field, plus any related-rule required fields.
        suppressBeforeUnload = true;
        if (saveForm) {
          saveForm.requestSubmit ? saveForm.requestSubmit() : saveForm.submit();
        }
      };

      validRows.forEach((item) => {
        // Only headline cards and section rows that are editable should
        // listen. `data-readonly="1"` on the input means the field is
        // server-side read-only — no quick-edit there either.
        const controls = item.editor.querySelectorAll("input, select, textarea");
        const editableControl = Array.from(controls).find(
          (c) => c.dataset.readonly !== "1",
        );
        if (!editableControl) return;
        item.display.addEventListener("dblclick", (ev) => {
          if (editing) return; // full edit mode owns interaction
          if (activeQuickEdit) exitQuickEdit(false);
          ev.preventDefault();
          item.row.classList.add("is-quick-editing");
          item.display.hidden = true;
          item.display.setAttribute("aria-hidden", "true");
          item.editor.hidden = false;
          item.editor.setAttribute("aria-hidden", "false");
          editableControl.disabled = false;
          activeQuickEdit = {
            item,
            control: editableControl,
            initialValue: "value" in editableControl ? editableControl.value : "",
            initialChecked:
              editableControl instanceof HTMLInputElement && (editableControl.type === "checkbox" || editableControl.type === "radio")
                ? editableControl.checked
                : false,
          };
          // Focus the control. For text inputs, select all so the user
          // can overwrite immediately; for textareas, just place the
          // caret at the end.
          editableControl.focus();
          if (editableControl instanceof HTMLInputElement && editableControl.type !== "checkbox") {
            editableControl.select?.();
          }
        });

        editableControl.addEventListener("keydown", (ev) => {
          if (!activeQuickEdit || activeQuickEdit.control !== editableControl) return;
          if (ev.key === "Escape") {
            ev.preventDefault();
            exitQuickEdit(false);
            return;
          }
          // Textareas use Ctrl/Cmd+Enter to commit (plain Enter inserts a newline).
          const isTextarea = editableControl.tagName === "TEXTAREA";
          if (ev.key === "Enter") {
            if (isTextarea && !(ev.ctrlKey || ev.metaKey)) return;
            ev.preventDefault();
            commitQuickEdit();
          }
        });

        editableControl.addEventListener("blur", () => {
          // Defer slightly so a click on a related label/dropdown option
          // doesn't trigger immediate teardown.
          window.setTimeout(() => {
            if (activeQuickEdit && activeQuickEdit.control === editableControl) {
              commitQuickEdit();
            }
          }, 120);
        });
      });

      const initialMode = (scope.dataset.editInitialMode || "view").toLowerCase();
      applyState(initialMode === "editing");
      scope.dataset.editModeInstalled = "true";
    });
  };
})();
