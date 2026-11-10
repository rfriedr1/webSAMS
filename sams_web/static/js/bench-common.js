// Behaviour shared by the preparation and graphitization benches.
//
// Both bench scripts used to carry their own copy of this code (66 identical
// lines), which is how the Sample # steppers once had to be fixed twice.
// Loaded before both bench scripts (lab_queue.html); exposes
// `window.SAMSBench`.
(() => {
  // ---- dirty markers --------------------------------------------------

  // Marks each changed field's wrapper with `.is-dirty`, so the operator
  // can see which values they have touched since the page loaded.
  const installDirtyMarkers = (form) => {
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

    const wrapperFor = (control) => control.closest(".bench-field, .bench-flag");

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

  // ---- lookup form (Sample # → Prep # → Target #) ----------------------

  /**
   * Wires a bench's lookup form.
   *
   * @param {object} options
   * @param {Element} options.bench          bench root (scopes datalist lookups)
   * @param {HTMLFormElement} options.form   the lookup form
   * @param {HTMLInputElement} options.sampleInput
   * @param {string} options.sampleStepAttr  attribute on the Sample # stepper
   *        buttons holding the step (e.g. "data-prep-bench-sample-step")
   * @param {() => string} options.currentSample  sample on the bench, used
   *        when the field is empty
   * @param {{input: HTMLInputElement, label: string}[]} options.dependents
   *        fields that belong to the sample, in order (Prep #, then Target #).
   *        Cleared when the sample changes; each must match its datalist.
   */
  const installLookupForm = ({ bench, form, sampleInput, sampleStepAttr, currentSample, dependents }) => {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const fields = (dependents || []).filter((d) => d.input instanceof HTMLInputElement);
    const initialSampleValue = sampleInput instanceof HTMLInputElement ? sampleInput.value : "";
    const lastValid = new Map(fields.map((d) => [d.input, d.input.value]));

    const allowedValues = (input) => {
      const listId = input.getAttribute("list");
      if (!listId) {
        return null;
      }
      const datalist = bench.querySelector(`#${CSS.escape(listId)}`);
      if (!(datalist instanceof HTMLDataListElement)) {
        return null;
      }
      const values = new Set();
      datalist.querySelectorAll("option").forEach((option) => {
        const value = (option.getAttribute("value") || "").trim();
        if (value !== "") {
          values.add(value);
        }
      });
      return values;
    };

    // A dependent value must be one the loaded sample actually has. On a
    // mismatch the browser shows the message and the last good value comes
    // back, so the form never loads a record that does not exist.
    const validate = ({ input, label }) => {
      const raw = input.value.trim();
      if (raw === "") {
        input.setCustomValidity("");
        return true;
      }
      const allowed = allowedValues(input);
      if (!allowed || allowed.size === 0 || allowed.has(raw)) {
        // No option list available: allow, the server resolves/validates.
        input.setCustomValidity("");
        lastValid.set(input, input.value);
        return true;
      }
      input.setCustomValidity(`${label} must match an existing value.`);
      input.reportValidity();
      input.value = lastValid.get(input) || "";
      input.setCustomValidity("");
      return false;
    };
    const validateAll = () => fields.every(validate);

    if (sampleInput instanceof HTMLInputElement) {
      const clearDependentsIfSampleChanged = () => {
        if (sampleInput.value === initialSampleValue) {
          return;
        }
        fields.forEach(({ input }) => {
          input.value = "";
          lastValid.set(input, "");
        });
      };
      sampleInput.addEventListener("input", clearDependentsIfSampleChanged);
      sampleInput.addEventListener("change", clearDependentsIfSampleChanged);

      // Sample # steppers: step the number, drop the now-stale dependents,
      // and load the new sample straight away.
      bench.querySelectorAll(`[${sampleStepAttr}]`).forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) {
          return;
        }
        button.addEventListener("click", () => {
          const delta = Number.parseInt(button.getAttribute(sampleStepAttr) || "0", 10);
          if (!Number.isFinite(delta) || delta === 0) {
            return;
          }
          const raw = sampleInput.value.trim();
          // Empty field: start from whichever sample is on the bench.
          const base = Number.parseInt(raw !== "" ? raw : currentSample() || "", 10);
          if (!Number.isFinite(base)) {
            sampleInput.focus();
            return;
          }
          const next = Math.max(1, base + delta);
          if (String(next) === raw) {
            return;
          }
          sampleInput.value = String(next);
          clearDependentsIfSampleChanged();
          form.requestSubmit();
        });
      });
    }

    fields.forEach((field) => {
      field.input.addEventListener("change", () => {
        if (validate(field)) {
          form.requestSubmit();
        }
      });
    });

    [sampleInput, ...fields.map((d) => d.input)].forEach((control) => {
      if (!(control instanceof HTMLInputElement)) {
        return;
      }
      control.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
          return;
        }
        event.preventDefault();
        const field = fields.find((d) => d.input === control);
        if (field && !validate(field)) {
          return;
        }
        form.requestSubmit();
      });
    });

    form.addEventListener("submit", (event) => {
      if (!validateAll()) {
        event.preventDefault();
      }
    });
  };

  // ---- balance in grams: g → mg on Enter --------------------------------

  // Some balances send their reading in grams, the database stores mg. The
  // balance types the number into the focused field and ends with Enter
  // (the bench's own Enter handler then leaves the field). With the
  // "Balance g → mg" switch on, Enter in a `[data-bench-weight]` field first
  // multiplies the value by 1000 — as the legacy "auto g -> mg" box did.
  //
  // Only a value typed or sent since the last conversion is converted, so a
  // second Enter, or Enter on a weight loaded from the database, never
  // multiplies again. The switch is remembered per bench in this browser
  // (i.e. per lab PC, where the balance is plugged in), like the legacy
  // Persistent.ini, and is never posted.
  const gToMgKey = (bench) => `sams_bench_g_to_mg_${bench}`;

  const installGramToMilligram = (form) => {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const toggle = form.querySelector("[data-bench-g-to-mg]");
    if (!(toggle instanceof HTMLInputElement)) {
      return;
    }
    const key = gToMgKey(toggle.dataset.benchGToMg || "bench");
    const restore = () => {
      try {
        toggle.checked = window.localStorage.getItem(key) === "1";
      } catch (_error) {
        toggle.checked = false;
      }
    };
    restore();
    toggle.addEventListener("change", () => {
      try {
        window.localStorage.setItem(key, toggle.checked ? "1" : "0");
      } catch (_error) {
        // Storage blocked: the switch still works until the page reloads.
      }
    });
    // Cancel (a form reset) must not switch it off.
    form.addEventListener("reset", () => window.setTimeout(restore, 0));

    form.querySelectorAll("[data-bench-weight]").forEach((input) => {
      if (!(input instanceof HTMLInputElement)) {
        return;
      }
      let typedSinceConversion = false;
      input.addEventListener("input", (event) => {
        if (event.isTrusted) {
          typedSinceConversion = true;
        }
      });
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || !toggle.checked || !typedSinceConversion) {
          return;
        }
        const raw = input.value.trim();
        const grams = Number.parseFloat(raw.replace(",", "."));
        if (raw === "" || !Number.isFinite(grams)) {
          return;
        }
        typedSinceConversion = false;
        // 3 decimals in mg = 1 µg, finer than any balance here; also drops
        // float noise (0.0123 * 1000 = 12.299999999999999).
        input.value = String(Number((grams * 1000).toFixed(3)));
        input.title = `${raw} g → ${input.value} mg`;
        const field = input.closest(".bench-field");
        if (field) {
          field.classList.remove("is-converted");
          void field.offsetWidth; // restart the highlight
          field.classList.add("is-converted");
          window.setTimeout(() => field.classList.remove("is-converted"), 1600);
        }
        // Yield, Weight End prefill, dates and dirty dots follow the value.
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
  };

  window.SAMSBench = { installDirtyMarkers, installLookupForm, installGramToMilligram };
})();
