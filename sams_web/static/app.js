(() => {
  const ready = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
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
    installers.installFieldErrorSummary?.();
    installers.installPreparationBench?.();
    installers.installGraphitizationBench?.();
  });
})();
