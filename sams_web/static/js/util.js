// Small helpers shared by the bundled modules. First file in the JS bundle
// (main._JS_BUNDLE_FILES), so every later module can use window.SAMSUtil.
(() => {
  // Collapse runs of whitespace (incl. newlines from cell markup) and trim.
  const normalizeWhitespace = (value) => String(value || "").replace(/\s+/g, " ").trim();

  // Lower-case and strip accents for search: "Häck" and "hack" compare equal,
  // matching the server's accent-folding lookups (Magic Nav `sub:<name>`).
  const foldForSearch = (value) =>
    String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();

  window.SAMSUtil = Object.freeze({ normalizeWhitespace, foldForSearch });
})();
