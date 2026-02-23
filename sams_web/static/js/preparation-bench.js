(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});
  const LAST_SAMPLE_STORAGE_LOCATION_KEY = "sams_prep_bench_last_sample_storage_location";

  const asNumber = (value) => {
    if (typeof value !== "string") {
      return Number.NaN;
    }
    const normalized = value.trim().replace(",", ".");
    if (normalized === "") {
      return Number.NaN;
    }
    return Number.parseFloat(normalized);
  };

  const formatNumber = (value, digits = 2) => {
    if (!Number.isFinite(value)) {
      return "";
    }
    return value.toFixed(digits);
  };

  const formatToday = () => {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const installBenchDirtyMarkers = (form) => {
    if (!(form instanceof HTMLFormElement)) {
      return { refresh: () => {} };
    }
    const controls = Array.from(form.querySelectorAll("input, select, textarea")).filter((control) => {
      if (!(control instanceof HTMLElement)) {
        return false;
      }
      if (control instanceof HTMLInputElement && control.type === "hidden") {
        return false;
      }
      if ("disabled" in control && control.disabled) {
        return false;
      }
      return true;
    });

    const readCurrent = (control) => {
      if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio")) {
        return control.checked ? "1" : "0";
      }
      return "value" in control ? String(control.value ?? "") : "";
    };

    const wrapperFor = (control) =>
      control.closest(".prep-bench-field, .prep-bench-checkbox-row");

    controls.forEach((control) => {
      control.dataset.benchInitialValue = readCurrent(control);
    });

    const refresh = () => {
      controls.forEach((control) => {
        const wrapper = wrapperFor(control);
        if (!(wrapper instanceof HTMLElement)) {
          return;
        }
        const dirty = (control.dataset.benchInitialValue || "") !== readCurrent(control);
        wrapper.classList.toggle("is-dirty", dirty);
      });
    };

    controls.forEach((control) => {
      const handler = () => refresh();
      control.addEventListener("input", handler);
      control.addEventListener("change", handler);
    });

    return { refresh };
  };

  installers.installPreparationBench = () => {
    const benches = document.querySelectorAll("[data-prep-bench]");
    benches.forEach((bench) => {
      if (bench.dataset.prepBenchInstalled === "true") {
        return;
      }

      const lookupForm = bench.querySelector("[data-prep-bench-lookup-form]");
      const scanInput = bench.querySelector("[data-prep-bench-scan-input]");
      const prepInput = bench.querySelector("[data-prep-bench-prep-input]");
      const saveForm = bench.querySelector("[data-prep-bench-save-form]");

      if (lookupForm) {
        [scanInput, prepInput].forEach((control) => {
          if (!(control instanceof HTMLInputElement)) {
            return;
          }
          control.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") {
              return;
            }
            event.preventDefault();
            lookupForm.requestSubmit();
          });
        });
      }

      if (saveForm) {
        const dirtyMarkers = installBenchDirtyMarkers(saveForm);
        const weightStart = saveForm.querySelector("[data-prep-bench-weight-start]");
        const weightMid = saveForm.querySelector("[data-prep-bench-weight-medium]");
        const weightMid2 = saveForm.querySelector("[data-prep-bench-weight-medium-2]");
        const weightEnd = saveForm.querySelector("[data-prep-bench-weight-end]");
        const prepStart = saveForm.querySelector("[data-prep-bench-prep-start]");
        const prepEnd = saveForm.querySelector("[data-prep-bench-prep-end]");
        const yieldDisplay = saveForm.querySelector("[data-prep-bench-yield]");
        const yieldHidden = saveForm.querySelector("[data-prep-bench-yield-hidden]");
        const storageInput = saveForm.querySelector("[data-prep-bench-storage-location]");
        const sampleArchivedCheckbox = saveForm.querySelector("[data-prep-bench-sample-archived]");
        const noLeftoverCheckbox = saveForm.querySelector("[data-prep-bench-no-leftover]");
        const returnToSenderCheckbox = saveForm.querySelector("[data-prep-bench-return-to-sender]");
        const storageWarning = saveForm.querySelector("[data-prep-bench-storage-warning]");

        let weightEndTouched = Boolean(weightEnd && weightEnd.value.trim() !== "");

        if (weightEnd) {
          weightEnd.addEventListener("input", () => {
            weightEndTouched = true;
          });
        }

        const updateYield = () => {
          if (!weightStart || !weightEnd || !yieldDisplay) {
            return;
          }
          const start = asNumber(weightStart.value);
          const end = asNumber(weightEnd.value);
          if (!Number.isFinite(start) || !Number.isFinite(end) || start === 0) {
            yieldDisplay.textContent = "Not set";
            if (yieldHidden) {
              yieldHidden.value = "";
            }
            return;
          }
          const yieldPercent = (end / start) * 100;
          const formatted = formatNumber(yieldPercent, 2);
          yieldDisplay.textContent = formatted;
          if (yieldHidden) {
            yieldHidden.value = formatted;
          }
        };

        const maybePrefillWeightEnd = () => {
          if (!weightMid || !weightMid2 || !weightEnd) {
            return;
          }
          if (weightEndTouched && weightEnd.value.trim() !== "") {
            return;
          }
          const mid = asNumber(weightMid.value);
          const mid2 = asNumber(weightMid2.value);
          if (!Number.isFinite(mid) || !Number.isFinite(mid2)) {
            return;
          }
          weightEnd.value = formatNumber(mid - mid2, 4);
          updateYield();
        };

        const maybeAutofillDate = (weightControl, dateControl) => {
          if (!(weightControl instanceof HTMLInputElement) || !(dateControl instanceof HTMLInputElement)) {
            return;
          }
          const weightValue = asNumber(weightControl.value);
          if (!Number.isFinite(weightValue)) {
            return;
          }
          if (dateControl.value.trim() !== "") {
            return;
          }
          dateControl.value = formatToday();
        };

        [weightMid, weightMid2].forEach((control) => {
          if (!(control instanceof HTMLInputElement)) {
            return;
          }
          control.addEventListener("input", maybePrefillWeightEnd);
        });

        if (weightStart instanceof HTMLInputElement) {
          weightStart.addEventListener("input", () => {
            maybeAutofillDate(weightStart, prepStart);
            updateYield();
          });
        }

        if (weightEnd instanceof HTMLInputElement) {
          weightEnd.addEventListener("input", () => {
            maybeAutofillDate(weightEnd, prepEnd);
            updateYield();
          });
        }

        const syncSampleArchived = () => {
          if (!(storageInput instanceof HTMLInputElement) || !(sampleArchivedCheckbox instanceof HTMLInputElement)) {
            return;
          }
          sampleArchivedCheckbox.checked = storageInput.value.trim() !== "";
        };

        const getStorageConflictMessages = () => {
          const messages = [];
          const hasStorageValue =
            storageInput instanceof HTMLInputElement && storageInput.value.trim() !== "";
          if (!hasStorageValue) {
            return messages;
          }
          if (noLeftoverCheckbox instanceof HTMLInputElement && noLeftoverCheckbox.checked) {
            messages.push("No Leftover is checked, so there is nothing to archive.");
          }
          if (returnToSenderCheckbox instanceof HTMLInputElement && returnToSenderCheckbox.checked) {
            messages.push("Return to Sender (project) is checked, so the sample material should be returned instead of archived.");
          }
          return messages;
        };

        const renderStorageWarning = () => {
          if (!(storageWarning instanceof HTMLElement)) {
            return;
          }
          const messages = getStorageConflictMessages();
          if (messages.length === 0) {
            storageWarning.hidden = true;
            storageWarning.textContent = "";
            return;
          }
          storageWarning.hidden = false;
          storageWarning.textContent = messages.join(" ");
        };

        const rememberSampleStorageLocation = () => {
          if (!(storageInput instanceof HTMLInputElement)) {
            return;
          }
          const value = storageInput.value.trim();
          if (value === "") {
            return;
          }
          window.sessionStorage.setItem(LAST_SAMPLE_STORAGE_LOCATION_KEY, value);
        };

        const prefillRememberedSampleStorageLocation = () => {
          if (!(storageInput instanceof HTMLInputElement)) {
            return;
          }
          if (storageInput.value.trim() !== "") {
            return;
          }
          const remembered = (window.sessionStorage.getItem(LAST_SAMPLE_STORAGE_LOCATION_KEY) || "").trim();
          if (remembered === "") {
            return;
          }
          storageInput.value = remembered;
        };

        if (storageInput instanceof HTMLInputElement) {
          storageInput.addEventListener("input", () => {
            syncSampleArchived();
            renderStorageWarning();
            rememberSampleStorageLocation();
            dirtyMarkers.refresh();
          });
          storageInput.addEventListener("change", () => {
            syncSampleArchived();
            renderStorageWarning();
            rememberSampleStorageLocation();
            dirtyMarkers.refresh();
          });
        }

        if (noLeftoverCheckbox instanceof HTMLInputElement) {
          noLeftoverCheckbox.addEventListener("change", renderStorageWarning);
        }
        if (returnToSenderCheckbox instanceof HTMLInputElement) {
          returnToSenderCheckbox.addEventListener("change", renderStorageWarning);
        }

        saveForm.addEventListener("keydown", (event) => {
          if (event.key !== "Enter") {
            return;
          }
          const target = event.target;
          if (target instanceof HTMLTextAreaElement) {
            return;
          }
          if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement) {
            event.preventDefault();
            target.blur();
          }
        });

        const actionButtons = Array.from(
          saveForm.querySelectorAll('button[name="bench__action"]'),
        );
        saveForm.addEventListener("submit", () => {
          saveForm.classList.add("is-saving");
          actionButtons.forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) {
              return;
            }
            if (button === document.activeElement) {
              button.dataset.defaultLabel = button.dataset.defaultLabel || button.textContent || "";
              button.classList.add("is-saving");
              button.textContent = button.value === "save_next" ? "Saving & Loading..." : "Saving...";
            }
            button.disabled = true;
          });
        });

        saveForm.addEventListener("reset", () => {
          window.setTimeout(() => {
            weightEndTouched = Boolean(weightEnd && weightEnd.value.trim() !== "");
            maybePrefillWeightEnd();
            updateYield();
            syncSampleArchived();
            renderStorageWarning();
            dirtyMarkers.refresh();
          }, 0);
        });

        prefillRememberedSampleStorageLocation();
        maybePrefillWeightEnd();
        updateYield();
        syncSampleArchived();
        renderStorageWarning();
        dirtyMarkers.refresh();
      }

      bench.dataset.prepBenchInstalled = "true";
    });
  };
})();
