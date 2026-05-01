// Top-of-page indeterminate progress bar shown during full-page navigation.
// Appears on form submit / link click via the beforeunload event and is
// implicitly removed when the next page renders.
(() => {
  const showProgress = () => {
    if (document.getElementById("sams-page-progress")) return;
    const bar = document.createElement("div");
    bar.id = "sams-page-progress";
    bar.className = "page-progress";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
  };

  // Trigger on actual navigation away (form submit, link click, etc.).
  window.addEventListener("beforeunload", showProgress);

  // Also show during form submits even when handlers prevent default
  // navigation; in that case the bar will be removed by the next render
  // anyway.
  document.addEventListener("submit", showProgress, true);
})();
