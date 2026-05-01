// Searchable-select enhancer. For any <select> on the page with more than
// SEARCHABLE_THRESHOLD non-blank options, replace the native dropdown with a
// type-to-filter combobox. Changes commit back to the original <select> so
// server-side form handling works unchanged. Native fallback if JS is off.
(() => {
  const SEARCHABLE_THRESHOLD = 8;
  const ATTR_SKIP = "data-no-searchable";
  const ATTR_ENHANCED = "data-searchable-enhanced";

  const realOptionCount = (select) =>
    Array.from(select.options).filter((o) => o.value && o.value !== "").length;

  const enhance = (select) => {
    if (select.hasAttribute(ATTR_ENHANCED)) return;
    if (select.hasAttribute(ATTR_SKIP)) return;
    if (select.multiple) return; // multi-select isn't supported
    if (realOptionCount(select) <= SEARCHABLE_THRESHOLD) return;

    select.setAttribute(ATTR_ENHANCED, "1");

    const wrap = document.createElement("div");
    wrap.className = "searchable-select";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("searchable-select-native");

    const input = document.createElement("input");
    input.type = "text";
    input.className = "searchable-select-input";
    input.autocomplete = "off";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    input.placeholder = select.dataset.placeholder || "Type to search…";
    if (select.disabled) input.disabled = true;
    if (select.required) input.setAttribute("aria-required", "true");
    wrap.appendChild(input);

    const list = document.createElement("ul");
    list.className = "searchable-select-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(list);

    const setInputFromSelect = () => {
      const opt = select.options[select.selectedIndex];
      input.value = opt && opt.value ? opt.text : "";
    };
    setInputFromSelect();

    let activeIndex = -1;
    let visibleOptions = [];

    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      activeIndex = -1;
      [...list.children].forEach((el) => el.classList.remove("is-active"));
    };

    const renderList = (filter) => {
      list.textContent = "";
      const term = (filter || "").toLowerCase();
      visibleOptions = Array.from(select.options)
        .filter((o) => o.value !== "" && o.text.toLowerCase().includes(term));
      if (!visibleOptions.length) {
        const empty = document.createElement("li");
        empty.className = "searchable-select-empty";
        empty.textContent = "No matches";
        list.appendChild(empty);
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
        return;
      }
      visibleOptions.forEach((opt, idx) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.dataset.value = opt.value;
        li.textContent = opt.text;
        li.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(idx);
        });
        list.appendChild(li);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      activeIndex = -1;
    };

    const choose = (idx) => {
      const opt = visibleOptions[idx];
      if (!opt) return;
      select.value = opt.value;
      input.value = opt.text;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      close();
    };

    const setActive = (idx) => {
      const items = list.querySelectorAll("li[role='option']");
      if (!items.length) return;
      activeIndex = ((idx % items.length) + items.length) % items.length;
      items.forEach((el, i) => el.classList.toggle("is-active", i === activeIndex));
      const item = items[activeIndex];
      if (item) item.scrollIntoView({ block: "nearest" });
    };

    input.addEventListener("focus", () => renderList(input.value));
    input.addEventListener("input", () => renderList(input.value));
    input.addEventListener("blur", () => setTimeout(close, 100));
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (list.hidden) renderList(input.value);
        setActive(activeIndex + 1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(activeIndex - 1);
        return;
      }
      if (event.key === "Enter") {
        if (!list.hidden && activeIndex >= 0) {
          event.preventDefault();
          choose(activeIndex);
        }
        return;
      }
      if (event.key === "Escape") {
        close();
        return;
      }
    });

    // Mirror programmatic select changes (e.g. form-error redisplay) back
    // into the input.
    select.addEventListener("change", () => setInputFromSelect());
  };

  const enhanceAll = (root) => {
    (root || document).querySelectorAll("select").forEach(enhance);
  };

  document.addEventListener("DOMContentLoaded", () => enhanceAll());

  // Re-enhance when detail-edit-mode swaps editors visible. The detail-edit
  // module dispatches no event for that, but selects are present from the
  // start (just hidden). DOMContentLoaded is sufficient.
})();
