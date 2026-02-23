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
      users: "Users",
      projects: "Projects",
      samples: "Samples",
      preparations: "Preparations",
      targets: "Targets",
    };

    if (root === "users") {
      crumbs.push({ label: "Users", href: "/users" });
      if (segments[1]) {
        crumbs.push({ label: `User ${segments[1]}`, href: `/users/${segments[1]}` });
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
      crumbs.push({ label: "Setup", href: "/setup" });
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
    if (crumbs.length === 0) {
      return;
    }
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

    const renderLinkGroup = (host, items, emptyLabel) => {
      host.textContent = "";
      if (!items.length) {
        const empty = document.createElement("span");
        empty.className = "quick-access-empty";
        empty.textContent = emptyLabel;
        host.append(empty);
        return;
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
      renderLinkGroup(pinnedHost, pinned, "No pinned pages");
      renderLinkGroup(recentHost, recent, "No recent pages");
      const isPinned = pinned.some((item) => item.url === currentUrl);
      pinButton.classList.toggle("is-pinned", isPinned);
      pinButton.title = isPinned ? "Unpin current page" : "Pin current page";
      pinButton.setAttribute("aria-label", isPinned ? "Unpin current page" : "Pin current page");
      const icon = pinButton.querySelector("span[aria-hidden='true']");
      if (icon) {
        icon.textContent = isPinned ? "★" : "☆";
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

    pinButton.addEventListener("click", () => {
      const pinned = loadStoredPages(PINNED_PAGES_STORAGE_KEY);
      const existingIndex = pinned.findIndex((item) => normalizeRelativeUrl(item.url) === currentUrl);
      if (existingIndex >= 0) {
        pinned.splice(existingIndex, 1);
      } else {
        pinned.unshift({ label: currentLabel, url: currentUrl });
      }
      saveStoredPages(
        PINNED_PAGES_STORAGE_KEY,
        normalizeCollection(pinned, MAX_PINNED_PAGES),
      );
      sync();
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
          { label: "Samples: Users", href: "/users" },
          { label: "Lab Operations: Preparation", href: "/lab/preparation" },
          { label: "Lab Operations: Graphitization", href: "/lab/graphitization" },
          { label: "Lab Operations: Analysis", href: "/lab/analysis" },
          { label: "Search: Global", href: "/search?global=1" },
          { label: "Setup", href: "/setup" },
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
      const userMatch = normalized.match(/^usr[\s:_-]*(\d+)$/);
      if (userMatch) {
        return {
          label: `Open user ${userMatch[1]}`,
          href: `/users/${userMatch[1]}`,
          keywords: `user ${userMatch[1]} open`,
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
