// Up/down steppers for the bench lookup number fields (Prep #, Target #).
//
// They replace the browser's native number spinner so every lookup field
// on the bench pages shows the same control as Sample #. A click moves to
// the next / previous *existing* value when the input has a datalist (the
// preps or targets of the loaded sample), else by one, and then fires
// `change` so the bench's own handler validates and loads the record.
(() => {
  const allowedValues = (input) => {
    const listId = input.getAttribute("list");
    const datalist = listId ? document.getElementById(listId) : null;
    if (!(datalist instanceof HTMLDataListElement)) {
      return [];
    }
    return Array.from(datalist.querySelectorAll("option"))
      .map((option) => Number.parseInt(option.getAttribute("value") || "", 10))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
  };

  const nextValue = (input, delta) => {
    const current = Number.parseInt(input.value.trim(), 10);
    const allowed = allowedValues(input);
    if (allowed.length) {
      if (!Number.isFinite(current)) {
        return delta > 0 ? allowed[0] : allowed[allowed.length - 1];
      }
      const candidates = allowed.filter((v) => (delta > 0 ? v > current : v < current));
      if (!candidates.length) {
        return null;
      }
      return delta > 0 ? candidates[0] : candidates[candidates.length - 1];
    }
    const min = Number.parseInt(input.getAttribute("min") || "1", 10);
    if (!Number.isFinite(current)) {
      return min;
    }
    return Math.max(min, current + delta);
  };

  document.addEventListener("click", (event) => {
    const button =
      event.target instanceof Element ? event.target.closest("[data-bench-number-step]") : null;
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const input = button.closest(".prep-bench-stepper")?.querySelector("input");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const delta = Number.parseInt(button.dataset.benchNumberStep || "0", 10);
    if (!Number.isFinite(delta) || delta === 0) {
      return;
    }
    const next = nextValue(input, delta);
    if (next === null || String(next) === input.value.trim()) {
      return;
    }
    input.value = String(next);
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
})();
