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

  const resolveMagicPatchLabel = (value, prefixLabels, sampleLabel) => {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) {
      return "";
    }
    if (Object.prototype.hasOwnProperty.call(prefixLabels, normalized)) {
      return prefixLabels[normalized];
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
      const initialError = String(form.dataset.magicError || "").trim();

      const renderPatch = (forceErrorLabel = "") => {
        if (forceErrorLabel) {
          patch.hidden = false;
          patch.classList.add("is-error");
          patch.textContent = forceErrorLabel;
          return;
        }
        const label = resolveMagicPatchLabel(input.value, prefixLabels, sampleLabel);
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
    });
  };
})();
