(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  installers.installHistoryBackLinks = () => {
    const isBackLink = (anchor) => {
      if (!anchor || anchor.tagName !== "A") {
        return false;
      }
      if (anchor.hasAttribute("data-history-back") || anchor.classList.contains("nav-back")) {
        return true;
      }
      if (!anchor.closest(".page-actions")) {
        return false;
      }
      const label = (anchor.textContent || "").trim().toLowerCase();
      return label === "back" || label.startsWith("back ");
    };

    document.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const trigger = event.target.closest("a[href]");
      if (!isBackLink(trigger)) {
        return;
      }

      const fallback = trigger.getAttribute("data-fallback") || trigger.getAttribute("href") || "/";
      if (window.history.length > 1) {
        event.preventDefault();
        window.history.back();
        return;
      }
      trigger.setAttribute("href", fallback);
    });
  };
})();
