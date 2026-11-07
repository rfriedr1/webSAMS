// Tab panels: one visible panel at a time, the rest `hidden`.
//
//   <div data-tabs data-tabs-key="dashboard-queues">
//     <div role="tablist">
//       <button role="tab" id="tab-x" aria-controls="tbl-x" aria-selected="true">…</button>
//       …
//     </div>
//     <section role="tabpanel" id="tbl-x" aria-labelledby="tab-x">…</section>
//     <section role="tabpanel" id="tbl-y" aria-labelledby="tab-y" hidden>…</section>
//   </div>
//
// The server renders the first panel visible. Arrow keys / Home / End move
// between tabs (WAI-ARIA tabs pattern, automatic activation). Any in-page
// link to a panel's id (`#tbl-planned`, e.g. the dashboard queue bars) and a
// page URL carrying that hash select the panel and scroll the tab group into
// view. With `data-tabs-key`, the last chosen tab is remembered for the
// session.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const storageKey = (group) => `sams-tabs:${group.dataset.tabsKey}`;

  const remember = (group, panelId) => {
    if (!group.dataset.tabsKey) {
      return;
    }
    try {
      window.sessionStorage.setItem(storageKey(group), panelId);
    } catch (_error) {
      // Private mode or blocked storage: the choice simply isn't kept.
    }
  };

  const recall = (group) => {
    if (!group.dataset.tabsKey) {
      return null;
    }
    try {
      return window.sessionStorage.getItem(storageKey(group));
    } catch (_error) {
      return null;
    }
  };

  const tabsOf = (group) => Array.from(group.querySelectorAll('[role="tab"]'));

  const select = (group, tab, { focus = false } = {}) => {
    tabsOf(group).forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", selected ? "true" : "false");
      candidate.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(candidate.getAttribute("aria-controls") || "");
      if (panel) {
        panel.hidden = !selected;
      }
    });
    if (focus) {
      tab.focus();
    }
    remember(group, tab.getAttribute("aria-controls") || "");
  };

  const findTabForPanel = (panelId) => {
    if (!panelId) {
      return null;
    }
    const tab = document.querySelector(`[role="tab"][aria-controls="${CSS.escape(panelId)}"]`);
    const group = tab?.closest("[data-tabs]");
    return tab && group ? { tab, group } : null;
  };

  const selectForHash = (hash, { scroll = true } = {}) => {
    if (!hash || hash.length < 2) {
      return false;
    }
    let panelId = "";
    try {
      panelId = decodeURIComponent(hash.slice(1));
    } catch (_error) {
      return false;
    }
    const found = findTabForPanel(panelId);
    if (!found) {
      return false;
    }
    select(found.group, found.tab);
    if (scroll) {
      found.group.scrollIntoView({ block: "start" });
    }
    return true;
  };

  installers.installTabPanels = () => {
    const groups = Array.from(document.querySelectorAll("[data-tabs]"));
    if (groups.length === 0) {
      return;
    }

    groups.forEach((group) => {
      const tabs = tabsOf(group);
      tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => select(group, tab));
        tab.addEventListener("keydown", (event) => {
          let next = null;
          if (event.key === "ArrowRight") {
            next = tabs[(index + 1) % tabs.length];
          } else if (event.key === "ArrowLeft") {
            next = tabs[(index - 1 + tabs.length) % tabs.length];
          } else if (event.key === "Home") {
            next = tabs[0];
          } else if (event.key === "End") {
            next = tabs[tabs.length - 1];
          }
          if (next) {
            event.preventDefault();
            select(group, next, { focus: true });
          }
        });
      });

      const remembered = findTabForPanel(recall(group) || "");
      if (remembered && remembered.group === group) {
        select(group, remembered.tab);
      }
    });

    // In-page links to a panel select it instead of jumping to a hidden
    // element. The hash still goes into the URL so the view can be shared.
    document.addEventListener("click", (event) => {
      const link = event.target.closest?.('a[href^="#"]');
      if (!link) {
        return;
      }
      const hash = link.getAttribute("href") || "";
      if (selectForHash(hash)) {
        event.preventDefault();
        history.replaceState(null, "", hash);
      }
    });

    window.addEventListener("hashchange", () => selectForHash(window.location.hash));
    selectForHash(window.location.hash);
  };
})();
