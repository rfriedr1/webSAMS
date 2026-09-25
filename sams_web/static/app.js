(() => {
  // `interactive` does NOT mean we may run yet. Deferred scripts execute
  // after parsing but *before* DOMContentLoaded, and bundle.js (which
  // carries this file) is the first of them — so running here fired the
  // installer list before the page-specific bench modules had registered
  // theirs, and `installers.installGraphitizationBench?.()` silently
  // no-opped. Only `complete` is safe to run against immediately.
  const ready = (fn) => {
    if (document.readyState === "complete") {
      fn();
      return;
    }
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  };

  ready(() => {
    const installers = window.SAMSAppInstallers || {};
    installers.installHistoryBackLinks?.();
    installers.renderBreadcrumbs?.();
    installers.installQuickAccess?.();
    installers.installCommandPalette?.();
    installers.installTableWrapping?.();
    installers.installTableEnhancer?.();
    installers.installMagicIdentifierPatch?.();
    installers.installMagicIdentifierHelp?.();
    installers.installDetailEditMode?.();
    installers.installDetailEmptyFields?.();
    installers.installFieldErrorSummary?.();
    installers.installPreparationBench?.();
    installers.installGraphitizationBench?.();
  });
})();
