(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});
  // Remembered for the session so an operator who wants to see every
  // field keeps seeing them as they move between records.
  const STORAGE_KEY = "sams_detail_show_empty_fields";

  const readPreference = () => {
    try { return window.sessionStorage.getItem(STORAGE_KEY) === "1"; } catch { return false; }
  };
  const writePreference = (show) => {
    try { window.sessionStorage.setItem(STORAGE_KEY, show ? "1" : "0"); } catch { /* private mode */ }
  };

  // Collapses empty (`—`) rows in each detail-page section behind a small
  // "N empty" toggle. Edit mode reveals them through CSS regardless of the
  // toggle, so a field can always be filled in.
  installers.installDetailEmptyFields = () => {
    const lists = document.querySelectorAll(
      ".sample-field-list, .project-field-list, .user-field-list",
    );
    if (!lists.length) return;
    let showAll = readPreference();
    const toggles = [];

    lists.forEach((list) => {
      const empties = Array.from(list.querySelectorAll(".detail-field-row.is-empty-value"));
      if (!empties.length) return;
      const filled = list.querySelectorAll(".detail-field-row:not(.is-empty-value)").length;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "detail-empty-toggle";
      button.setAttribute("aria-expanded", "false");
      list.insertAdjacentElement("afterend", button);

      const apply = () => {
        empties.forEach((row) => row.classList.toggle("is-empty-hidden", !showAll));
        button.setAttribute("aria-expanded", showAll ? "true" : "false");
        const n = empties.length;
        const fields = `${n} empty field${n === 1 ? "" : "s"}`;
        button.textContent = showAll
          ? `Hide ${fields}`
          : filled
            ? `${fields} hidden`
            : n === 1
              ? "Only field is empty — show"
              : `All ${n} fields empty — show`;
      };
      toggles.push(apply);
      apply();
      button.addEventListener("click", () => {
        showAll = !showAll;
        writePreference(showAll);
        toggles.forEach((fn) => fn());
      });
    });
  };
})();
