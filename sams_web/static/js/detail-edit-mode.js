(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  installers.installDetailEditMode = () => {
    const scopes = document.querySelectorAll("[data-edit-scope]");
    scopes.forEach((scope) => {
      if (scope.dataset.editModeInstalled === "true") {
        return;
      }

      const toggleButton = scope.querySelector("[data-edit-toggle]");
      const cancelButton = scope.querySelector("[data-edit-cancel]");
      const saveButton = scope.querySelector("[data-edit-save]");
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
      const defaultLabel = toggleButton.dataset.editLabelDefault || "Edit";
      const activeLabel = toggleButton.dataset.editLabelActive || "View";

      const isControlDirty = (control) => {
        if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
          return (control.dataset.initialChecked === "1") !== control.checked;
        }
        if ("value" in control) {
          return (control.dataset.initialValue || "") !== control.value;
        }
        return false;
      };

      const hasUnsavedChanges = () => allControls.some((control) => isControlDirty(control));

      const updateDirtyMarkers = () => {
        validRows.forEach((item) => {
          const controls = Array.from(item.editor.querySelectorAll("input, select, textarea"));
          const rowDirty = controls.some((control) => isControlDirty(control));
          item.row.classList.toggle("is-dirty", rowDirty);
        });
        scope.classList.toggle("has-unsaved-changes", hasUnsavedChanges());
      };

      const confirmDiscardChanges = () => {
        if (!hasUnsavedChanges()) {
          return true;
        }
        return window.confirm("You have unsaved changes. Discard them?");
      };

      const applyState = (isEditing) => {
        editing = isEditing;
        scope.classList.toggle("is-editing", editing);
        toggleButton.textContent = editing ? activeLabel : defaultLabel;
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
          return;
        }
        updateDirtyMarkers();
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

      toggleButton.addEventListener("click", () => {
        if (editing) {
          if (!confirmDiscardChanges()) {
            return;
          }
          resetEditors();
          applyState(false);
          return;
        }
        applyState(true);
      });

      cancelButton.addEventListener("click", () => {
        if (!confirmDiscardChanges()) {
          return;
        }
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

      scope.addEventListener("keydown", (event) => {
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
          if (!confirmDiscardChanges()) {
            return;
          }
          resetEditors();
          applyState(false);
        }
      });

      const initialMode = (scope.dataset.editInitialMode || "view").toLowerCase();
      applyState(initialMode === "editing");
      scope.dataset.editModeInstalled = "true";
    });
  };
})();
