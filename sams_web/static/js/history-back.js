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

    const samePath = (a, b) => {
      if (!a || !b) return false;
      try {
        const ua = new URL(a, window.location.origin);
        const ub = new URL(b, window.location.origin);
        return ua.pathname.replace(/\/+$/, "") === ub.pathname.replace(/\/+$/, "");
      } catch (_) {
        return false;
      }
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
      // Only use history.back() when the previous page actually matches the
      // labelled destination. Otherwise honor the explicit fallback so a link
      // like "Back to preparation" always lands on the preparation page,
      // regardless of how the user arrived here.
      const referrer = document.referrer || "";
      if (window.history.length > 1 && samePath(referrer, fallback)) {
        event.preventDefault();
        window.history.back();
        return;
      }
      trigger.setAttribute("href", fallback);
    });
  };
})();
