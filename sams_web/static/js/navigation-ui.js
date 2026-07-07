(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const RECENT_PAGES_STORAGE_KEY = "sams_recent_pages_v1";
  const PINNED_PAGES_STORAGE_KEY = "sams_pinned_pages_v1";
  const MAX_RECENT_PAGES = 8;
  const MAX_PINNED_PAGES = 12;

  const normalizeWhitespace = (value) => String(value || "").replace(/\s+/g, " ").trim();

  const loadStoredPages = (key) => {
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return [];
      }
      return parsed
        .filter((entry) => entry && typeof entry === "object")
        .map((entry) => ({
          label: normalizeWhitespace(String(entry.label || "")),
          url: normalizeWhitespace(String(entry.url || "")),
        }))
        .filter((entry) => entry.label && entry.url);
    } catch (_error) {
      return [];
    }
  };

  const saveStoredPages = (key, entries) => {
    try {
      window.localStorage.setItem(key, JSON.stringify(entries));
    } catch (_error) {
      // Ignore storage write errors (private mode / quota).
    }
  };

  const normalizeRelativeUrl = (rawUrl) => {
    try {
      const resolved = new URL(rawUrl, window.location.origin);
      return `${resolved.pathname}${resolved.search}`;
    } catch (_error) {
      return window.location.pathname;
    }
  };

  const titleCaseToken = (value) => value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

  const buildBreadcrumbs = () => {
    const path = window.location.pathname;
    const query = new URLSearchParams(window.location.search);
    const segments = path.split("/").filter(Boolean);
    const crumbs = [];

    if (segments.length === 0) {
      crumbs.push({ label: "Dashboard", href: "/" });
      return crumbs;
    }

    const root = segments[0];
    const contextLabels = {
      submitters: "Submitters",
      projects: "Projects",
      samples: "Samples",
      preparations: "Preparations",
      targets: "Targets",
    };

    if (root === "submitters") {
      crumbs.push({ label: "Submitters", href: "/submitters" });
      if (segments[1]) {
        crumbs.push({ label: `Submitter ${segments[1]}`, href: `/submitters/${segments[1]}` });
      }
      return crumbs;
    }

    if (root === "projects") {
      crumbs.push({ label: "Projects", href: "/projects" });
      if (segments[1]) {
        crumbs.push({ label: `Project ${segments[1]}`, href: `/projects/${segments[1]}` });
      }
      return crumbs;
    }

    if (root === "samples") {
      const sampleNr = segments[1];
      if (sampleNr) {
        crumbs.push({ label: `Sample ${sampleNr}`, href: `/samples/${sampleNr}` });
      } else {
        crumbs.push({ label: "Samples", href: "/samples" });
      }
      if (segments[2] === "preparations" && segments[3]) {
        const prepNr = segments[3];
        crumbs.push({
          label: `Prep ${prepNr}`,
          href: `/samples/${sampleNr}/preparations/${prepNr}`,
        });
      }
      if (segments[4] === "targets" && segments[5]) {
        crumbs.push({
          label: `Target ${segments[5]}`,
          href: `/samples/${sampleNr}/preparations/${segments[3]}/targets/${segments[5]}`,
        });
      }
      return crumbs;
    }

    if (root === "setup") {
      crumbs.push({ label: "Settings", href: "/setup" });
      return crumbs;
    }

    if (root === "help") {
      crumbs.push({ label: "Help", href: "/help" });
      return crumbs;
    }

    if (root === "lab") {
      crumbs.push({ label: "Lab Operations", href: "/lab/preparation" });
      const labMode = segments[1] || "preparation";
      if (labMode === "preparation") {
        crumbs.push({ label: "Prep", href: "/lab/preparation" });
      } else if (labMode === "graphitization") {
        crumbs.push({ label: "Graphitization", href: "/lab/graphitization" });
      } else if (labMode === "analysis") {
        crumbs.push({ label: "Analysis", href: "/lab/analysis" });
      } else {
        crumbs.push({ label: titleCaseToken(labMode), href: path });
      }
      return crumbs;
    }

    if (root === "search") {
      const isGlobal = query.get("global") === "1";
      crumbs.push({ label: isGlobal ? "Global Search" : "Search", href: isGlobal ? "/search?global=1" : "/search" });
      const context = normalizeWhitespace(query.get("context") || "");
      if (context && contextLabels[context]) {
        const contextHref = isGlobal ? `/search?global=1&context=${context}` : `/search?context=${context}`;
        crumbs.push({ label: contextLabels[context], href: contextHref });
      }
      const mode = normalizeWhitespace(query.get("mode") || "");
      if (mode === "analysis") {
        crumbs.push({ label: "Analysis", href: window.location.pathname + window.location.search });
      }
      return crumbs;
    }

    if (root === "docs") {
      crumbs.push({ label: "API Docs", href: "/docs" });
      return crumbs;
    }

    crumbs.push({ label: titleCaseToken(root) || "Page", href: path });
    return crumbs;
  };

  installers.renderBreadcrumbs = () => {
    const container = document.querySelector("[data-breadcrumbs]");
    if (!container) {
      return;
    }
    const crumbs = buildBreadcrumbs();
    container.textContent = "";
    // Hide the breadcrumbs nav entirely when there's only the root crumb —
    // the page title already states where you are.
    if (crumbs.length <= 1) {
      container.hidden = true;
      return;
    }
    container.hidden = false;
    crumbs.forEach((crumb, index) => {
      const isLast = index === crumbs.length - 1;
      if (isLast) {
        const current = document.createElement("span");
        current.className = "breadcrumb-current";
        current.textContent = crumb.label;
        container.append(current);
      } else {
        const link = document.createElement("a");
        link.className = "breadcrumb-link";
        link.href = crumb.href;
        link.textContent = crumb.label;
        container.append(link);
        const sep = document.createElement("span");
        sep.className = "breadcrumb-separator";
        sep.setAttribute("aria-hidden", "true");
        sep.textContent = "›";
        container.append(sep);
      }
    });
  };

  const deriveCurrentPageLabel = () => {
    const header = document.querySelector("main.page h2");
    if (header && normalizeWhitespace(header.textContent)) {
      return normalizeWhitespace(header.textContent);
    }
    const activeSecondary = document.querySelector(".sub-nav a.is-active");
    if (activeSecondary && normalizeWhitespace(activeSecondary.textContent)) {
      return normalizeWhitespace(activeSecondary.textContent);
    }
    const activePrimary = document.querySelector(".main-nav a.is-active");
    if (activePrimary && normalizeWhitespace(activePrimary.textContent)) {
      return normalizeWhitespace(activePrimary.textContent);
    }
    return "Current Page";
  };

  installers.installQuickAccess = () => {
    const pinnedHost = document.querySelector("[data-pinned-links]");
    const recentHost = document.querySelector("[data-recent-links]");
    const pinButton = document.querySelector("[data-pin-current]");
    if (!pinnedHost || !recentHost || !pinButton) {
      return;
    }

    const currentUrl = normalizeRelativeUrl(window.location.href);
    const currentPath = window.location.pathname;
    const currentLabel = deriveCurrentPageLabel();
    const hiddenPaths = new Set(["/magic/open", "/samples/open"]);

    const renderLinkGroup = (host, items) => {
      host.textContent = "";
      // Hide the surrounding group (label + list) entirely when empty.
      // Rendering "No pinned pages" / "No recent pages" placeholders adds
      // chrome noise that the user never asked for.
      const group = host.closest(".quick-access-group");
      if (!items.length) {
        if (group) {
          group.hidden = true;
        }
        return;
      }
      if (group) {
        group.hidden = false;
      }
      items.forEach((item) => {
        const anchor = document.createElement("a");
        anchor.className = "quick-access-link";
        anchor.href = item.url;
        anchor.title = item.label;
        anchor.textContent = item.label;
        host.append(anchor);
      });
    };

    const normalizeCollection = (entries, maxItems) => {
      const deduped = [];
      const seen = new Set();
      entries.forEach((entry) => {
        const url = normalizeRelativeUrl(entry.url || "");
        const label = normalizeWhitespace(entry.label || "");
        if (!url || !label) {
          return;
        }
        if (seen.has(url)) {
          return;
        }
        seen.add(url);
        deduped.push({ label, url });
      });
      return deduped.slice(0, maxItems);
    };

    const sync = () => {
      const pinned = normalizeCollection(loadStoredPages(PINNED_PAGES_STORAGE_KEY), MAX_PINNED_PAGES);
      const recent = normalizeCollection(loadStoredPages(RECENT_PAGES_STORAGE_KEY), MAX_RECENT_PAGES);
      renderLinkGroup(pinnedHost, pinned);
      renderLinkGroup(recentHost, recent);
      // Hide the entire context-strip when neither breadcrumbs nor any
      // quick-access content is showing; otherwise hide just the
      // quick-access shell when both groups are empty.
      const quickAccess = document.querySelector(".quick-access");
      if (quickAccess) {
        quickAccess.hidden = pinned.length === 0 && recent.length === 0;
      }
      const breadcrumbs = document.querySelector("[data-breadcrumbs]");
      const strip = document.querySelector("[data-context-strip]");
      if (strip) {
        const breadcrumbsHidden = !breadcrumbs || breadcrumbs.hidden || !breadcrumbs.children.length;
        const quickAccessHidden = !quickAccess || quickAccess.hidden;
        strip.hidden = breadcrumbsHidden && quickAccessHidden;
      }
      const isPinned = pinned.some((item) => item.url === currentUrl);
      pinButton.classList.toggle("is-pinned", isPinned);
      pinButton.title = isPinned ? "Unpin current page (Ctrl/Cmd + Shift + P)" : "Pin current page (Ctrl/Cmd + Shift + P)";
      pinButton.setAttribute("aria-label", isPinned ? "Unpin current page" : "Pin current page");
      const icon = pinButton.querySelector(".quick-pin-toggle-glyph");
      if (icon) {
        icon.textContent = isPinned ? "★" : "☆";
      }
      const label = pinButton.querySelector("[data-pin-label]");
      if (label) {
        label.textContent = isPinned ? "Pinned" : "Pin";
      }
    };

    if (!hiddenPaths.has(currentPath)) {
      const existingRecent = loadStoredPages(RECENT_PAGES_STORAGE_KEY);
      const mergedRecent = normalizeCollection(
        [{ label: currentLabel, url: currentUrl }, ...existingRecent],
        MAX_RECENT_PAGES,
      );
      saveStoredPages(RECENT_PAGES_STORAGE_KEY, mergedRecent);
    }

    // Pinning is silent today; users frequently miss whether the click
    // registered. Toast + briefly highlighting the newly-pinned entry
    // makes the action observable. The animation respects reduced-motion
    // via a `prefers-reduced-motion` CSS guard.
    const togglePin = () => {
      const pinned = loadStoredPages(PINNED_PAGES_STORAGE_KEY);
      const existingIndex = pinned.findIndex((item) => normalizeRelativeUrl(item.url) === currentUrl);
      const wasPinned = existingIndex >= 0;
      if (wasPinned) {
        pinned.splice(existingIndex, 1);
      } else {
        pinned.unshift({ label: currentLabel, url: currentUrl });
      }
      saveStoredPages(
        PINNED_PAGES_STORAGE_KEY,
        normalizeCollection(pinned, MAX_PINNED_PAGES),
      );
      sync();
      // Brief slide-in highlight on the freshly pinned entry.
      if (!wasPinned) {
        const firstLink = pinnedHost.querySelector(".quick-access-link");
        if (firstLink) {
          firstLink.classList.add("is-newly-pinned");
          setTimeout(() => firstLink.classList.remove("is-newly-pinned"), 1200);
        }
      }
      // Toast confirmation. The toast module gracefully no-ops if absent.
      if (window.SAMSToast && typeof window.SAMSToast.show === "function") {
        window.SAMSToast.show(
          wasPinned ? `Unpinned "${currentLabel}"` : `Pinned "${currentLabel}"`,
          "info",
        );
      }
    };
    pinButton.addEventListener("click", togglePin);

    // Keyboard shortcut Ctrl/Cmd+Shift+P toggles pin from anywhere. Skipped
    // while the user is typing in a form control so the shortcut never
    // hijacks a real keystroke.
    document.addEventListener("keydown", (ev) => {
      const target = ev.target;
      const isTyping =
        target instanceof HTMLElement &&
        (target.matches("input, textarea, select, [contenteditable='true']"));
      if (isTyping) return;
      const modPressed = ev.metaKey || ev.ctrlKey;
      if (!modPressed || !ev.shiftKey) return;
      if (ev.key.toLowerCase() !== "p") return;
      ev.preventDefault();
      togglePin();
    });

    sync();
  };

  installers.installCommandPalette = () => {
    const root = document.querySelector("[data-command-palette]");
    const input = root?.querySelector("[data-command-palette-input]");
    const list = root?.querySelector("[data-command-palette-list]");
    if (!root || !input || !list) {
      return;
    }

    // Render Ctrl/Cmd glyphs and shortcut hints based on the user's
    // platform — Mac users see ⌘K, everyone else sees Ctrl K. Falls back
    // gracefully if `navigator.platform` is missing (older browsers).
    const platform = (navigator.userAgentData?.platform || navigator.platform || "").toLowerCase();
    const isMac = platform.includes("mac") || platform.includes("iphone") || platform.includes("ipad");
    const modGlyph = isMac ? "⌘" : "Ctrl";
    const modGlyphSep = isMac ? "" : " ";
    document.querySelectorAll("[data-platform-kbd]").forEach((el) => {
      const trigger = el.closest("[data-platform-shortcut]");
      const key = trigger?.dataset.platformShortcut || "K";
      el.textContent = `${modGlyph}${modGlyphSep}${key}`;
    });
    document.querySelectorAll("[data-platform-shortcut]").forEach((el) => {
      const key = el.dataset.platformShortcut || "K";
      const title = el.getAttribute("title");
      if (title) {
        el.setAttribute("title", title.replace(/Ctrl/, isMac ? "⌘" : "Ctrl"));
      }
      // Re-target the data attribute for any future scripts hooking in.
      el.dataset.modKey = isMac ? "Meta" : "Control";
    });

    const openTriggers = document.querySelectorAll("[data-command-palette-open]");
    const closeTriggers = root.querySelectorAll("[data-command-palette-close]");

    const loadNavigationCommandEntries = () => {
      const node = document.getElementById("navigation-command-entries");
      if (!node) {
        return [];
      }
      try {
        const parsed = JSON.parse(node.textContent || "[]");
        if (!Array.isArray(parsed)) {
          return [];
        }
        return parsed
          .filter((entry) => entry && typeof entry === "object")
          .map((entry) => ({
            label: normalizeWhitespace(String(entry.label || "")),
            href: normalizeRelativeUrl(String(entry.href || "")),
          }))
          .filter((entry) => entry.label && entry.href);
      } catch (_error) {
        return [];
      }
    };

    const buildBaseCommands = () => {
      const commands = [];
      const seen = new Set();
      const addCommand = (label, href, keywords = "") => {
        const normalizedLabel = normalizeWhitespace(label);
        const normalizedHref = normalizeRelativeUrl(href);
        const key = `${normalizedLabel}|${normalizedHref}`;
        if (!normalizedLabel || !normalizedHref || seen.has(key)) {
          return;
        }
        seen.add(key);
        commands.push({
          label: normalizedLabel,
          href: normalizedHref,
          keywords: normalizeWhitespace(`${normalizedLabel} ${keywords} ${normalizedHref}`).toLowerCase(),
        });
      };

      const configuredCommands = loadNavigationCommandEntries();
      const seedCommands = configuredCommands.length > 0
        ? configuredCommands
        : [
          { label: "Dashboard", href: "/" },
          { label: "Samples: Sample", href: "/samples" },
          { label: "Samples: Projects", href: "/projects" },
          { label: "Samples: Submitters", href: "/submitters" },
          { label: "Lab Operations: Preparation", href: "/lab/preparation" },
          { label: "Lab Operations: Graphitization", href: "/lab/graphitization" },
          { label: "Lab Operations: Analysis", href: "/lab/analysis" },
          { label: "Search: Global", href: "/search?global=1" },
          { label: "Settings", href: "/setup" },
          { label: "Help", href: "/help" },
          { label: "API Docs", href: "/docs" },
        ];
      seedCommands.forEach((entry) => {
        addCommand(entry.label, entry.href, "navigation page");
      });

      document.querySelectorAll("[data-command-link]").forEach((link) => {
        const href = link.getAttribute("href");
        if (!href) {
          return;
        }
        addCommand(
          link.dataset.commandLabel || link.textContent || "Open",
          href,
          link.textContent || "",
        );
      });

      loadStoredPages(PINNED_PAGES_STORAGE_KEY).forEach((entry) => {
        addCommand(entry.label, entry.url, "pinned");
      });
      loadStoredPages(RECENT_PAGES_STORAGE_KEY).forEach((entry) => {
        addCommand(entry.label, entry.url, "recent");
      });

      return commands;
    };

    const parseIdentifierCommand = (term) => {
      const normalized = normalizeWhitespace(term).toLowerCase();
      if (!normalized) {
        return null;
      }
      const magicCommandMap = {
        "/prep": "/lab/preparation",
        "/graph": "/lab/graphitization",
        "/ana": "/lab/analysis",
      };
      if (Object.prototype.hasOwnProperty.call(magicCommandMap, normalized)) {
        return {
          label: `Run Magic Nav ${normalized}`,
          href: magicCommandMap[normalized],
          keywords: `magic nav command ${normalized}`,
        };
      }
      if (/^\d+$/.test(normalized)) {
        return {
          label: `Open sample ${normalized}`,
          href: `/samples/${normalized}`,
          keywords: `sample ${normalized} open`,
        };
      }
      const projectMatch = normalized.match(/^pr[\s:_-]*(\d+)$/);
      if (projectMatch) {
        return {
          label: `Open project ${projectMatch[1]}`,
          href: `/projects/${projectMatch[1]}`,
          keywords: `project ${projectMatch[1]} open`,
        };
      }
      const submitterMatch = normalized.match(/^sub[\s:_-]*(\d+)$/);
      if (submitterMatch) {
        return {
          label: `Open submitter ${submitterMatch[1]}`,
          href: `/submitters/${submitterMatch[1]}`,
          keywords: `submitter ${submitterMatch[1]} open`,
        };
      }
      return null;
    };

    let filteredCommands = [];
    let activeIndex = 0;

    const render = () => {
      const term = normalizeWhitespace(input.value).toLowerCase();
      const baseCommands = buildBaseCommands();
      const identifierCommand = parseIdentifierCommand(term);
      let commands = baseCommands;
      if (identifierCommand) {
        commands = [identifierCommand, ...commands];
      }
      if (term) {
        commands = commands.filter((command) => command.keywords.includes(term));
      }
      filteredCommands = commands.slice(0, 12);
      if (activeIndex >= filteredCommands.length) {
        activeIndex = 0;
      }

      list.textContent = "";
      if (filteredCommands.length === 0) {
        const empty = document.createElement("li");
        empty.className = "command-palette-item-empty";
        empty.textContent = "No matching commands.";
        list.append(empty);
        return;
      }

      filteredCommands.forEach((command, index) => {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "command-palette-item";
        if (index === activeIndex) {
          button.classList.add("is-active");
        }
        button.setAttribute("data-command-url", command.href);

        const title = document.createElement("span");
        title.className = "command-palette-title";
        title.textContent = command.label;
        const meta = document.createElement("span");
        meta.className = "command-palette-meta";
        meta.textContent = command.href;

        button.append(title, meta);
        item.append(button);
        list.append(item);
      });
    };

    const open = () => {
      root.hidden = false;
      document.body.classList.add("has-command-palette");
      input.value = "";
      activeIndex = 0;
      render();
      window.requestAnimationFrame(() => {
        input.focus();
      });
    };

    const close = () => {
      root.hidden = true;
      document.body.classList.remove("has-command-palette");
    };

    const openCommand = (href) => {
      if (!href) {
        return;
      }
      window.location.href = href;
    };

    openTriggers.forEach((button) => {
      button.addEventListener("click", () => {
        open();
      });
    });
    closeTriggers.forEach((button) => {
      button.addEventListener("click", () => {
        close();
      });
    });

    list.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-command-url]");
      if (!trigger) {
        return;
      }
      openCommand(trigger.getAttribute("data-command-url"));
    });

    input.addEventListener("input", () => {
      activeIndex = 0;
      render();
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (filteredCommands.length > 0) {
          activeIndex = (activeIndex + 1) % filteredCommands.length;
          render();
        }
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (filteredCommands.length > 0) {
          activeIndex = (activeIndex - 1 + filteredCommands.length) % filteredCommands.length;
          render();
        }
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const selected = filteredCommands[activeIndex];
        if (selected) {
          openCommand(selected.href);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (root.hidden) {
          open();
        } else {
          close();
        }
        return;
      }
      if (event.key === "Escape" && !root.hidden) {
        event.preventDefault();
        close();
      }
    });
  };
})();
