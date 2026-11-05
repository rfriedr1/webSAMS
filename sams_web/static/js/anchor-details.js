// In-page links into collapsed content: when a `#hash` link points at a
// closed <details> — the target itself, a <details> that is its direct
// child, or one it sits inside — open it before the browser scrolls, so the
// content is visible at once. Used by the dashboard's Queue Tables pills
// (`#tbl-<queue>` → the panel wrapping that queue's collapsible table).
// Also applied on load and on `hashchange`, so a shared `/#tbl-planned`
// link lands on an open table.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const detailsFor = (target) => {
    const found = [];
    const own = target.matches("details") ? target : target.querySelector(":scope > details");
    if (own) {
      found.push(own);
    }
    let parent = target.parentElement?.closest("details");
    while (parent) {
      found.push(parent);
      parent = parent.parentElement?.closest("details");
    }
    return found;
  };

  const openForHash = (hash) => {
    if (!hash || hash.length < 2) {
      return;
    }
    let target = null;
    try {
      target = document.getElementById(decodeURIComponent(hash.slice(1)));
    } catch (_error) {
      return;
    }
    if (!target) {
      return;
    }
    detailsFor(target).forEach((details) => {
      if (!details.open) {
        details.open = true;
      }
    });
  };

  installers.installAnchorDetails = () => {
    document.addEventListener("click", (event) => {
      const link = event.target instanceof Element ? event.target.closest("a[href^='#']") : null;
      if (!link) {
        return;
      }
      // Runs before the default navigation, so the scroll lands on the
      // already-expanded content.
      openForHash(link.getAttribute("href"));
    });
    window.addEventListener("hashchange", () => openForHash(window.location.hash));
    openForHash(window.location.hash);
  };
})();
