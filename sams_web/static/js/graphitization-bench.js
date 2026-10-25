(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});
  const STORAGE_KEY = "sams_graph_batch_staging";
  // Loading the next target is a GET navigation, so the batch header
  // (system + name) has to survive the reload the same way the staged
  // target list does — otherwise the operator retypes it per target.
  const BATCH_META_KEY = "sams_graph_batch_meta";
  const LAST_PREP_STORAGE_LOCATION_KEY = "sams_graph_bench_last_prep_storage_location";

  const parseJson = (raw, fallback) => {
    try {
      const parsed = JSON.parse(raw);
      return parsed ?? fallback;
    } catch {
      return fallback;
    }
  };

  const getTodayYyMmDd = () => {
    const now = new Date();
    const yy = String(now.getFullYear()).slice(-2);
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    return `${yy}${mm}${dd}`;
  };

  installers.installGraphitizationBench = () => {
    const benches = document.querySelectorAll("[data-graph-bench]");
    benches.forEach((bench) => {
      if (bench.dataset.graphBenchInstalled === "true") {
        return;
      }

      window.SAMSBench.installLookupForm({
        bench,
        form: bench.querySelector("[data-graph-bench-lookup-form]"),
        sampleInput: bench.querySelector("[data-graph-bench-sample-input]"),
        sampleStepAttr: "data-graph-bench-sample-step",
        currentSample: () => bench.dataset.graphBenchCurrentSample || "",
        dependents: [
          { input: bench.querySelector("[data-graph-bench-prep-input]"), label: "Prep #" },
          { input: bench.querySelector("[data-graph-bench-target-input]"), label: "Target #" },
        ],
      });

      const targetForm = bench.querySelector("[data-graph-bench-target-form]");
      if (targetForm instanceof HTMLFormElement) {
        const dirtyMarkers = window.SAMSBench.installDirtyMarkers(targetForm);
        const prepStorage = targetForm.querySelector("[data-graph-bench-prep-storage]");
        const prepArchived = targetForm.querySelector("[data-graph-bench-prep-archived]");
        const noLeftoverCheckbox = targetForm.querySelector("[data-graph-bench-no-leftover]");
        const returnToSenderCheckbox = targetForm.querySelector("[data-graph-bench-return-to-sender]");
        const storageWarning = targetForm.querySelector("[data-graph-bench-storage-warning]");

        const syncPrepArchived = () => {
          if (!(prepStorage instanceof HTMLInputElement) || !(prepArchived instanceof HTMLInputElement)) {
            return;
          }
          prepArchived.checked = prepStorage.value.trim() !== "";
        };

        const getStorageConflictMessages = () => {
          const messages = [];
          const hasStorageValue =
            prepStorage instanceof HTMLInputElement && prepStorage.value.trim() !== "";
          if (!hasStorageValue) {
            return messages;
          }
          if (noLeftoverCheckbox instanceof HTMLInputElement && noLeftoverCheckbox.checked) {
            messages.push("No Leftover (Prep'd Material) is checked, so there is nothing to archive.");
          }
          if (returnToSenderCheckbox instanceof HTMLInputElement && returnToSenderCheckbox.checked) {
            messages.push("Prep Return to Sender (project) is checked, so the material should be returned instead of archived.");
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

        const rememberPrepStorageLocation = () => {
          if (!(prepStorage instanceof HTMLInputElement)) {
            return;
          }
          const value = prepStorage.value.trim();
          if (value === "") {
            return;
          }
          window.sessionStorage.setItem(LAST_PREP_STORAGE_LOCATION_KEY, value);
        };

        const prefillRememberedPrepStorageLocation = () => {
          if (!(prepStorage instanceof HTMLInputElement)) {
            return;
          }
          if (prepStorage.value.trim() !== "") {
            return;
          }
          const remembered = (window.sessionStorage.getItem(LAST_PREP_STORAGE_LOCATION_KEY) || "").trim();
          if (remembered === "") {
            return;
          }
          prepStorage.value = remembered;
        };

        if (prepStorage instanceof HTMLInputElement) {
          prepStorage.addEventListener("focus", () => {
            const beforeValue = prepStorage.value;
            prefillRememberedPrepStorageLocation();
            if (prepStorage.value !== beforeValue) {
              syncPrepArchived();
              renderStorageWarning();
              dirtyMarkers.refresh();
            }
          });
          prepStorage.addEventListener("input", () => {
            syncPrepArchived();
            renderStorageWarning();
            rememberPrepStorageLocation();
            dirtyMarkers.refresh();
          });
          prepStorage.addEventListener("change", () => {
            syncPrepArchived();
            renderStorageWarning();
            rememberPrepStorageLocation();
            dirtyMarkers.refresh();
          });
        }

        if (noLeftoverCheckbox instanceof HTMLInputElement) {
          noLeftoverCheckbox.addEventListener("change", renderStorageWarning);
        }
        if (returnToSenderCheckbox instanceof HTMLInputElement) {
          returnToSenderCheckbox.addEventListener("change", renderStorageWarning);
        }

        targetForm.addEventListener("keydown", (event) => {
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
          targetForm.querySelectorAll('button[name="graphbench__action"]'),
        );
        targetForm.addEventListener("submit", () => {
          targetForm.classList.add("is-saving");
          actionButtons.forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) {
              return;
            }
            if (button === document.activeElement) {
              button.classList.add("is-saving");
              button.textContent =
                button.value === "save_next" ? "Saving & Loading..." : "Saving...";
            }
            button.disabled = true;
          });
        });

        targetForm.addEventListener("reset", () => {
          window.setTimeout(() => {
            syncPrepArchived();
            renderStorageWarning();
            dirtyMarkers.refresh();
          }, 0);
        });

        syncPrepArchived();
        renderStorageWarning();
        dirtyMarkers.refresh();
      }

      const batchForm = bench.querySelector("[data-graph-bench-batch-form]");
      if (!(batchForm instanceof HTMLFormElement)) {
        bench.dataset.graphBenchInstalled = "true";
        return;
      }

      const systemField = batchForm.querySelector("[data-graph-batch-system]");
      const systemPillButtons = Array.from(batchForm.querySelectorAll("[data-graph-batch-system-pill]"));
      const batchNameInput = batchForm.querySelector("[data-graph-batch-name]");
      const addCurrentButton = batchForm.querySelector("[data-graph-batch-add-current]");
      const clearButton = batchForm.querySelector("[data-graph-batch-clear]");
      const countBadge = batchForm.querySelector("[data-graph-batch-count]");
      const tbody = batchForm.querySelector("[data-graph-batch-staged-body]");
      const emptyRow = batchForm.querySelector("[data-graph-batch-empty-row]");
      const targetsJsonField = batchForm.querySelector("[data-graph-batch-targets-json]");
      const clientError = batchForm.querySelector("[data-graph-batch-client-error]");
      const batchTargetsCard = batchForm.querySelector("[data-graph-batch-targets-card]");
      const batchDirtyMarkers = window.SAMSBench.installDirtyMarkers(batchForm);

      let stagedTargets = [];
      let batchNameDirty = false;
      let lastGeneratedName = "";

      const clearClientError = () => {
        if (!(clientError instanceof HTMLElement)) {
          return;
        }
        clientError.hidden = true;
        clientError.textContent = "";
      };

      const setClientError = (message) => {
        if (!(clientError instanceof HTMLElement)) {
          return;
        }
        clientError.hidden = false;
        clientError.textContent = message;
      };

      const saveBatchMeta = () => {
        if (!(systemField instanceof HTMLInputElement)) {
          return;
        }
        const meta = {
          system: systemField.value.trim(),
          batch_name:
            batchNameInput instanceof HTMLInputElement ? batchNameInput.value.trim() : "",
          dirty: batchNameDirty,
          generated: lastGeneratedName,
        };
        window.sessionStorage.setItem(BATCH_META_KEY, JSON.stringify(meta));
      };

      const saveStagedTargets = () => {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stagedTargets));
        if (targetsJsonField instanceof HTMLInputElement) {
          targetsJsonField.value = JSON.stringify(stagedTargets);
        }
        if (countBadge instanceof HTMLElement) {
          countBadge.textContent = String(stagedTargets.length);
        }
        if (batchTargetsCard instanceof HTMLElement) {
          batchTargetsCard.classList.toggle("is-dirty", stagedTargets.length > 0);
        }
      };

      const renderStagedTargets = () => {
        if (!(tbody instanceof HTMLTableSectionElement)) {
          return;
        }
        const existingRows = Array.from(tbody.querySelectorAll("tr[data-graph-batch-row]"));
        existingRows.forEach((row) => row.remove());
        stagedTargets.forEach((item, index) => {
          const row = document.createElement("tr");
          row.dataset.graphBatchRow = "1";
          // textContent, never innerHTML: user_label is the customer's own
          // sample name (imported from their Excel sheet) and comes back
          // through sessionStorage, so it must not be parsed as markup.
          [item.sample_nr, item.prep_nr, item.target_nr, item.user_label || ""].forEach((value) => {
            const cell = document.createElement("td");
            cell.textContent = String(value);
            row.appendChild(cell);
          });
          const actionCell = document.createElement("td");
          const removeButton = document.createElement("button");
          removeButton.type = "button";
          removeButton.className = "graph-batch-remove-btn";
          removeButton.dataset.removeIndex = String(index);
          removeButton.setAttribute("aria-label", "Remove target");
          removeButton.textContent = "\u2715";
          actionCell.appendChild(removeButton);
          row.appendChild(actionCell);
          tbody.appendChild(row);
        });
        if (emptyRow instanceof HTMLElement) {
          emptyRow.hidden = stagedTargets.length > 0;
        }
        saveStagedTargets();
      };

      const buildGeneratedBatchName = () => {
        if (!(systemField instanceof HTMLInputElement)) {
          return "";
        }
        const system = systemField.value.trim();
        if (system === "") {
          return "";
        }
        return `graph_${getTodayYyMmDd()}_${system}`;
      };

      const maybeGenerateBatchName = () => {
        if (!(batchNameInput instanceof HTMLInputElement)) {
          return;
        }
        const generated = buildGeneratedBatchName();
        if (!generated) {
          return;
        }
        const current = batchNameInput.value.trim();
        if (!batchNameDirty || current === "" || current === lastGeneratedName) {
          batchNameInput.value = generated;
          lastGeneratedName = generated;
          batchNameDirty = false;
        }
      };

      if (batchNameInput instanceof HTMLInputElement) {
        batchNameInput.addEventListener("input", () => {
          const current = batchNameInput.value.trim();
          batchNameDirty = current !== "" && current !== lastGeneratedName;
          clearClientError();
          saveBatchMeta();
        });
      }

      const syncSystemPills = () => {
        if (!(systemField instanceof HTMLInputElement)) {
          return;
        }
        const selected = systemField.value.trim();
        systemPillButtons.forEach((button) => {
          if (!(button instanceof HTMLButtonElement)) {
            return;
          }
          const isActive = (button.dataset.systemValue || "") === selected && selected !== "";
          button.classList.toggle("is-active", isActive);
          button.setAttribute("aria-pressed", isActive ? "true" : "false");
        });
      };

      // Restore the batch header before the pills are wired, so the initial
      // syncSystemPills() below lights up the remembered system.
      if (bench.dataset.graphBatchSaved !== "true") {
        const meta = parseJson(window.sessionStorage.getItem(BATCH_META_KEY) || "null", null);
        if (meta && typeof meta === "object") {
          if (systemField instanceof HTMLInputElement && typeof meta.system === "string") {
            systemField.value = meta.system;
          }
          if (batchNameInput instanceof HTMLInputElement && typeof meta.batch_name === "string") {
            batchNameInput.value = meta.batch_name;
          }
          lastGeneratedName = typeof meta.generated === "string" ? meta.generated : "";
          batchNameDirty = meta.dirty === true;
        }
      }

      if (systemField instanceof HTMLInputElement && systemPillButtons.length > 0) {
        systemPillButtons.forEach((button) => {
          if (!(button instanceof HTMLButtonElement)) {
            return;
          }
          button.addEventListener("click", () => {
            const nextValue = (button.dataset.systemValue || "").trim();
            if (systemField.value.trim() === nextValue) {
              return;
            }
            systemField.value = nextValue;
            syncSystemPills();
            clearClientError();
            maybeGenerateBatchName();
            saveBatchMeta();
          });
        });
        syncSystemPills();
      }

      const currentTarget = {
        sample_nr: Number.parseInt(batchForm.dataset.currentTargetSample || "", 10),
        prep_nr: Number.parseInt(batchForm.dataset.currentTargetPrep || "", 10),
        target_nr: Number.parseInt(batchForm.dataset.currentTargetTarget || "", 10),
        user_label: batchForm.dataset.currentTargetUserLabel || "",
        has_graph_batch: batchForm.dataset.currentTargetHasGraphBatch === "1",
        graph_batch: batchForm.dataset.currentTargetGraphBatch || "",
      };

      const addCurrentTarget = () => {
        clearClientError();
        if (!Number.isFinite(currentTarget.sample_nr) || !Number.isFinite(currentTarget.prep_nr) || !Number.isFinite(currentTarget.target_nr)) {
          setClientError("Current target is not fully loaded.");
          return;
        }
        if (currentTarget.has_graph_batch) {
          setClientError(`Target is already assigned to graph batch '${currentTarget.graph_batch}'.`);
          return;
        }
        const exists = stagedTargets.some(
          (item) =>
            item.sample_nr === currentTarget.sample_nr &&
            item.prep_nr === currentTarget.prep_nr &&
            item.target_nr === currentTarget.target_nr,
        );
        if (exists) {
          setClientError("Target is already in the staged batch list.");
          return;
        }
        stagedTargets.push({
          sample_nr: currentTarget.sample_nr,
          prep_nr: currentTarget.prep_nr,
          target_nr: currentTarget.target_nr,
          user_label: currentTarget.user_label,
        });
        renderStagedTargets();
      };

      if (addCurrentButton instanceof HTMLButtonElement) {
        addCurrentButton.addEventListener("click", addCurrentTarget);
      }

      if (clearButton instanceof HTMLButtonElement) {
        clearButton.addEventListener("click", () => {
          clearClientError();
          stagedTargets = [];
          renderStagedTargets();
        });
      }

      if (tbody instanceof HTMLTableSectionElement) {
        tbody.addEventListener("click", (event) => {
          const target = event.target;
          if (!(target instanceof HTMLElement)) {
            return;
          }
          const removeButton = target.closest("[data-remove-index]");
          if (!(removeButton instanceof HTMLElement)) {
            return;
          }
          const index = Number.parseInt(removeButton.dataset.removeIndex || "", 10);
          if (!Number.isInteger(index) || index < 0 || index >= stagedTargets.length) {
            return;
          }
          stagedTargets.splice(index, 1);
          clearClientError();
          renderStagedTargets();
        });
      }

      batchForm.addEventListener("submit", (event) => {
        clearClientError();
        if (stagedTargets.length === 0) {
          event.preventDefault();
          setClientError("Add at least one target to the batch before saving.");
          return;
        }
        if (!(batchNameInput instanceof HTMLInputElement) || batchNameInput.value.trim() === "") {
          event.preventDefault();
          setClientError("Batch name is required.");
          return;
        }
        saveStagedTargets();
      });

      if (bench.dataset.graphBatchSaved === "true") {
        window.sessionStorage.removeItem(STORAGE_KEY);
        window.sessionStorage.removeItem(BATCH_META_KEY);
      }

      const storedTargets = parseJson(window.sessionStorage.getItem(STORAGE_KEY) || "[]", []);
      if (Array.isArray(storedTargets)) {
        stagedTargets = storedTargets
          .filter((item) => item && typeof item === "object")
          .map((item) => ({
            sample_nr: Number.parseInt(String(item.sample_nr ?? ""), 10),
            prep_nr: Number.parseInt(String(item.prep_nr ?? ""), 10),
            target_nr: Number.parseInt(String(item.target_nr ?? ""), 10),
            user_label: String(item.user_label ?? ""),
          }))
          .filter(
            (item) =>
              Number.isFinite(item.sample_nr) &&
              Number.isFinite(item.prep_nr) &&
              Number.isFinite(item.target_nr),
          );
      }
      renderStagedTargets();
      batchDirtyMarkers.refresh();

      bench.dataset.graphBenchInstalled = "true";
    });
  };
})();
