// Small helpers shared by the bundled modules. First file in the JS bundle
// (main._JS_BUNDLE_FILES), so every later module can use window.SAMSUtil.
(() => {
  // Collapse runs of whitespace (incl. newlines from cell markup) and trim.
  const normalizeWhitespace = (value) => String(value || "").replace(/\s+/g, " ").trim();

  window.SAMSUtil = Object.freeze({ normalizeWhitespace });
})();
