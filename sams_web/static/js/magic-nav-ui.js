(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const parseMagicPrefixLabels = (raw) => {
    if (!raw) {
      return {};
    }
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return {};
      }
      return Object.fromEntries(
        Object.entries(parsed)
          .filter(([key, value]) => typeof key === "string" && typeof value === "string")
          .map(([key, value]) => [key.toLowerCase(), value]),
      );
    } catch (_error) {
      return {};
    }
  };

  const extractMagicPrefix = (value) => {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) {
      return null;
    }
    const match = normalized.match(/^([a-z]+)(?:[\s:_-]*\d*)?$/);
    if (!match) {
      return null;
    }
    return match[1];
  };

  const resolveMagicPatchLabel = (value, prefixLabels, sampleLabel, preparationLabel, targetLabel) => {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) {
      return "";
    }
    if (Object.prototype.hasOwnProperty.call(prefixLabels, normalized)) {
      return prefixLabels[normalized];
    }
    if (/^\d+\.\d+\.\d+$/.test(normalized)) {
      return targetLabel;
    }
    if (/^\d+\.\d+$/.test(normalized)) {
      return preparationLabel;
    }
    if (/^\d+$/.test(normalized)) {
      return sampleLabel;
    }
    const prefix = extractMagicPrefix(normalized);
    if (prefix) {
      return prefixLabels[prefix] || "unknown ID";
    }
    return "unknown ID";
  };

  installers.installMagicIdentifierPatch = () => {
    document.querySelectorAll(".magic-identifier-form").forEach((form) => {
      const input = form.querySelector("input[name='magic_identifier'], input[name='sample_nr']");
      const patch = form.querySelector("[data-magic-identifier-patch]");
      if (!input || !patch) {
        return;
      }
      const prefixLabels = {
        ...parseMagicPrefixLabels(form.dataset.magicPrefixLabels || ""),
        ...parseMagicPrefixLabels(form.dataset.magicCommandLabels || ""),
      };
      const sampleLabel = String(form.dataset.magicSampleLabel || "sample number");
      const preparationLabel = String(form.dataset.magicPreparationLabel || "preparation");
      const targetLabel = String(form.dataset.magicTargetLabel || "target");
      const initialError = String(form.dataset.magicError || "").trim();

      const renderPatch = (forceErrorLabel = "") => {
        if (forceErrorLabel) {
          patch.hidden = false;
          patch.classList.add("is-error");
          patch.textContent = forceErrorLabel;
          return;
        }
        const label = resolveMagicPatchLabel(
          input.value,
          prefixLabels,
          sampleLabel,
          preparationLabel,
          targetLabel,
        );
        if (!label) {
          patch.hidden = true;
          patch.classList.remove("is-error");
          patch.textContent = "";
          return;
        }
        patch.hidden = false;
        patch.classList.remove("is-error");
        patch.textContent = label;
      };

      const handleInputUpdate = () => {
        form.classList.remove("has-error");
        renderPatch();
      };

      input.addEventListener("input", handleInputUpdate);
      input.addEventListener("change", handleInputUpdate);
      renderPatch(initialError);

      // Rotating placeholder: each page load teaches one Magic Nav
      // syntax example. Stops as soon as the user types or focuses so
      // it never overwrites real input. Plain CSS opacity transition
      // keeps it gentle; the value itself is swapped at the midpoint.
      const rotateRaw = input.dataset.magicPlaceholderRotate;
      if (rotateRaw) {
        try {
          const examples = JSON.parse(rotateRaw);
          if (Array.isArray(examples) && examples.length > 0) {
            let idx = Math.floor(Math.random() * examples.length);
            const swap = () => {
              if (document.activeElement === input || input.value) return;
              idx = (idx + 1) % examples.length;
              input.classList.add("is-placeholder-fading");
              setTimeout(() => {
                input.setAttribute("placeholder", examples[idx]);
                input.classList.remove("is-placeholder-fading");
              }, 220);
            };
            const intervalId = window.setInterval(swap, 3500);
            const stop = () => window.clearInterval(intervalId);
            input.addEventListener("focus", stop, { once: true });
            input.addEventListener("input", stop, { once: true });
            // Seed the first placeholder to a random one so refreshing
            // the page surfaces a different example each time.
            input.setAttribute("placeholder", examples[idx]);
          }
        } catch (_error) {
          /* malformed JSON — fall back to the static placeholder */
        }
      }
    });
  };

  // Lightweight help popover: clicking the "?" next to Magic Nav shows
  // the syntax cheat-sheet inline. Borrows the existing shortcut-cheatsheet
  // overlay UI for visual consistency. Closes on backdrop click or Esc.
  installers.installMagicIdentifierHelp = () => {
    const trigger = document.querySelector("[data-magic-help-trigger]");
    if (!trigger) return;
    const buildOverlay = () => {
      const overlay = document.createElement("section");
      overlay.className = "shortcut-cheatsheet magic-help-overlay";
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.innerHTML = `
        <button type="button" class="shortcut-cheatsheet-backdrop" aria-label="Close"></button>
        <div class="shortcut-cheatsheet-panel">
          <div class="shortcut-cheatsheet-head">
            <h3>Magic Nav syntax</h3>
            <button type="button" class="shortcut-cheatsheet-close" aria-label="Close">×</button>
          </div>
          <dl class="shortcut-cheatsheet-list">
            <dt><kbd>12345</kbd></dt><dd>Open sample 12345</dd>
            <dt><kbd>12345.1</kbd></dt><dd>Open preparation 1 of sample 12345</dd>
            <dt><kbd>12345.1.1</kbd></dt><dd>Open target 1 of that preparation</dd>
            <dt><kbd>pr456</kbd></dt><dd>Open project 456</dd>
            <dt><kbd>sub210</kbd></dt><dd>Open submitter 210</dd>
            <dt><kbd>/prep</kbd></dt><dd>Jump to Lab/Preparation</dd>
            <dt><kbd>/graph</kbd></dt><dd>Jump to Lab/Graphitization</dd>
            <dt><kbd>/ana</kbd></dt><dd>Jump to Lab/Analysis</dd>
          </dl>
          <p class="shortcut-cheatsheet-hint">Or press <kbd>Ctrl/⌘ K</kbd> to open the full command palette.</p>
        </div>`;
      return overlay;
    };
    const open = () => {
      const overlay = buildOverlay();
      document.body.appendChild(overlay);
      const close = () => overlay.remove();
      overlay.querySelector(".shortcut-cheatsheet-backdrop").addEventListener("click", close);
      overlay.querySelector(".shortcut-cheatsheet-close").addEventListener("click", close);
      document.addEventListener("keydown", function escClose(ev) {
        if (ev.key === "Escape") {
          close();
          document.removeEventListener("keydown", escClose);
        }
      });
    };
    trigger.addEventListener("click", open);
  };
})();
