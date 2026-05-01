// Lightweight toast notifications. Append to a global region; auto-dismiss
// after a few seconds; can stack. Used by detail-page save flows and other
// short-lived feedback.
//
// Usage:
//   window.SAMSToast.show("Sample details were saved.", "success");
//   window.SAMSToast.show("Save failed.", "error", { duration: 0 }); // sticky
//
// Auto-promotes ?saved / ?bench_saved / ?graph_saved query params on first
// load to a success toast, then strips the param from the URL via
// history.replaceState so refreshing doesn't re-toast.
(() => {
  const REGION_ID = "sams-toast-region";
  const DEFAULT_DURATION = 4500;
  const ICONS = {
    success: "✓",
    error: "!",
    info: "i",
  };

  const ensureRegion = () => {
    let region = document.getElementById(REGION_ID);
    if (region) {
      return region;
    }
    region = document.createElement("div");
    region.id = REGION_ID;
    region.className = "toast-region";
    region.setAttribute("aria-live", "polite");
    region.setAttribute("aria-atomic", "false");
    document.body.appendChild(region);
    return region;
  };

  const dismiss = (toast) => {
    if (!toast || toast.dataset.dismissing === "1") {
      return;
    }
    toast.dataset.dismissing = "1";
    toast.classList.add("is-leaving");
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 220);
  };

  const show = (message, kind = "info", options = {}) => {
    if (!message) {
      return null;
    }
    const region = ensureRegion();
    const toast = document.createElement("div");
    const safeKind = ["success", "error", "info"].includes(kind) ? kind : "info";
    toast.className = `toast toast-${safeKind}`;
    toast.setAttribute("role", safeKind === "error" ? "alert" : "status");

    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = ICONS[safeKind] || ICONS.info;
    toast.appendChild(icon);

    const body = document.createElement("span");
    body.className = "toast-body";
    body.textContent = String(message);
    toast.appendChild(body);

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "toast-close";
    closeBtn.setAttribute("aria-label", "Dismiss notification");
    closeBtn.textContent = "×";
    closeBtn.addEventListener("click", () => dismiss(toast));
    toast.appendChild(closeBtn);

    region.appendChild(toast);

    const duration = options.duration === 0 ? 0 : (options.duration || DEFAULT_DURATION);
    if (duration > 0) {
      setTimeout(() => dismiss(toast), duration);
    }
    return toast;
  };

  // Public API
  window.SAMSToast = { show };

  // Auto-promote save-related query params on first load.
  document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    const successKeys = ["saved", "bench_saved", "graph_saved", "graph_batch_saved"];
    const successMessages = {
      saved: "Changes were saved.",
      bench_saved: "Bench entry saved.",
      graph_saved: "Graphitization entry saved.",
      graph_batch_saved: "Graph batch saved.",
    };
    let toasted = false;
    successKeys.forEach((key) => {
      if (params.get(key) === "true") {
        show(successMessages[key], "success");
        params.delete(key);
        toasted = true;
      }
    });
    const noticeKeys = ["bench_notice", "graph_notice", "graph_batch_notice"];
    noticeKeys.forEach((key) => {
      const value = params.get(key);
      if (value) {
        show(value.replace(/\+/g, " "), "info");
        params.delete(key);
        toasted = true;
      }
    });
    if (toasted) {
      const newSearch = params.toString();
      const newUrl = window.location.pathname + (newSearch ? "?" + newSearch : "") + window.location.hash;
      history.replaceState(null, "", newUrl);
    }
  });
})();
