// Transfer results from targets to samples (Lab → Analysis → Magazine →
// Actions → Transfer…, sample_transfer.py, ADR-0002). One block per sample
// of the magazine: the result a transfer would write, what is stored, and
// the sample's targets with a tick box each — one ticked target is copied,
// several are averaged (weighted FM mean). Every change of ticks asks the
// server for the preview again, so the math lives only in Python. Only
// Transfer posts; the server reads everything again before it writes.
//
//   [data-magazine-actions]        root (from _magazine_actions.html), data-magazine
//   [data-sample-transfer-open]    menu entry; #action=transfer-results opens it too
//   [data-sample-transfer-body]    built here with textContent only
//   [data-sample-transfer-choices] hidden field: the ticks as JSON
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const STATUS_TEXT = {
    new: "New",
    replaces: "Replaces",
    same: "Same",
    choose: "Choose targets",
    skip: "Left out",
    not_measured: "Not measured",
    invalid: "Cannot transfer",
  };
  const LIMIT_SIGMA = 99999;
  const OPEN_UP_TO = 8; // a sample waiting for a choice shows up to this many targets unfolded
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const isNum = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));
  const fixed = (v, digits) => (isNum(v) ? Number(v).toFixed(digits) : "—");
  const age = (value, sigma) => {
    if (!isNum(value)) return "—";
    if (Number(sigma) === LIMIT_SIGMA) return `> ${Math.round(value)} BP`;
    return `${Math.round(value)} ± ${isNum(sigma) ? Math.round(sigma) : "—"} BP`;
  };

  installers.installSampleTransfer = () => {
    const root = document.querySelector("[data-magazine-actions]");
    const opener = root?.querySelector("[data-sample-transfer-open]");
    if (!root || !opener) return;

    const magazine = root.dataset.magazine;
    const toggle = root.querySelector("[data-magazine-actions-toggle]");
    const menu = root.querySelector("[data-magazine-actions-menu]");
    const dialog = root.querySelector("[data-sample-transfer-dialog]");
    const form = dialog.querySelector("[data-sample-transfer-form]");
    const body = dialog.querySelector("[data-sample-transfer-body]");
    const choicesField = dialog.querySelector("[data-sample-transfer-choices]");
    const submit = dialog.querySelector("[data-sample-transfer-submit]");

    let ticks = null; // Map sample_nr → Set of refs; null = the server's defaults
    let unfolded = new Set(); // samples whose target list is shown
    let requestId = 0;
    let timer = 0;

    const choicesJson = () => {
      if (!ticks) return "";
      const out = {};
      ticks.forEach((refs, sampleNr) => {
        out[sampleNr] = [...refs];
      });
      return JSON.stringify(out);
    };

    const setSubmit = (writes) => {
      submit.disabled = !writes;
      submit.textContent = writes ? `Transfer ${plural(writes, "sample", "samples")}` : "Transfer";
    };

    const showError = (title, advice) => {
      body.textContent = "";
      const box = el("div", "record-action-error");
      box.append(el("p", "raw-currents-problem-title", title));
      if (advice) box.append(el("p", "", advice));
      box.append(el("p", "", "Nothing was changed."));
      body.append(box);
      setSubmit(0);
    };

    // ---- One sample: its row, then its targets --------------------------
    const chip = (status, text) => el("span", `raw-currents-chip sample-transfer-chip is-${status}`, text);

    const resultCell = (row) => {
      const td = el("td", "sample-transfer-result");
      if (!row.result) {
        td.append(el("span", "detail-empty", row.message || "—"));
        return td;
      }
      const r = row.result;
      td.append(el("strong", "", age(r.c14_age, r.c14_age_sig)));
      td.append(el("span", "sample-transfer-sub", `FM ${fixed(r.av_fm, 4)} ± ${fixed(r.av_fm_sig, 4)} · δ¹³C ${fixed(r.av_dc13, 4)}`));
      if (row.mode === "mean") {
        const agreement = row.agreement;
        const line = el("span", "sample-transfer-sub");
        line.append(document.createTextNode(`Weighted mean of ${row.chosen.length} · `));
        line.append(agreement.ok
          ? el("span", "sample-transfer-agree", `✓ agree (T ${agreement.t} ≤ ${agreement.critical})`)
          : el("span", "sample-transfer-disagree", `⚠ do not agree (T ${agreement.t} > ${agreement.critical})`));
        td.append(line);
        td.append(el("span", "sample-transfer-sub", "Calibrated ranges cleared"));
      } else if (row.targets.length > 1) {
        td.append(el("span", "sample-transfer-sub", `From target ${row.sample_nr}.${row.chosen[0]}`));
      }
      if (row.limit) td.append(el("span", "sample-transfer-sub", "Near background: lower-limit age"));
      return td;
    };

    const targetRow = (row, target) => {
      const tr = el("tr", "sample-transfer-target");
      if (!target.measured) tr.classList.add("is-unmeasured");
      const tickCell = el("td", "sample-transfer-tick");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = target.chosen;
      box.disabled = !target.measured;
      box.dataset.sample = String(row.sample_nr);
      box.dataset.ref = target.ref;
      box.setAttribute("aria-label", `Use target ${target.target_id}`);
      tickCell.append(box);
      tr.append(tickCell);
      const idCell = el("td", "sample-transfer-num", target.target_id);
      tr.append(idCell);
      const magCell = el("td", "", target.magazine || "—");
      if (target.in_magazine) magCell.append(" ", chip("here", "this magazine"));
      tr.append(magCell);
      tr.append(el("td", "sample-transfer-num", target.measured ? age(target.c14_age, target.c14_age_sig) : "not measured"));
      tr.append(el("td", "sample-transfer-num", target.measured ? `FM ${fixed(target.fm, 4)} ± ${fixed(target.fm_sig, 4)}` : ""));
      const notes = el("td", "");
      if (target.discarded) notes.append(chip("discarded", "Discarded"));
      if (target.frozen) notes.append(chip("frozen", "Frozen"));
      tr.append(notes);
      return tr;
    };

    const sampleBlock = (row) => {
      const tbody = el("tbody", `sample-transfer-sample is-${row.status}`);
      tbody.dataset.sample = String(row.sample_nr);
      const tr = el("tr", "sample-transfer-head");
      const link = el("a", "table-link", row.sample_nr);
      link.href = `/samples/${row.sample_nr}`;
      link.target = "_blank";
      const sampleCell = el("td", "sample-transfer-num");
      sampleCell.append(link);
      tr.append(sampleCell);
      tr.append(el("td", "sample-transfer-label", row.label || "—"));

      const measured = row.targets.filter((t) => t.measured).length;
      const targetsCell = el("td", "");
      const fold = el("button", "sample-transfer-fold");
      fold.type = "button";
      const open = unfolded.has(row.sample_nr);
      fold.setAttribute("aria-expanded", open ? "true" : "false");
      fold.textContent = `${open ? "▾" : "▸"} ${plural(row.targets.length, "target", "targets")}${measured !== row.targets.length ? `, ${measured} measured` : ""}`;
      fold.addEventListener("click", () => {
        if (unfolded.has(row.sample_nr)) unfolded.delete(row.sample_nr);
        else unfolded.add(row.sample_nr);
        renderSample(row);
      });
      targetsCell.append(fold);
      tr.append(targetsCell);

      tr.append(resultCell(row));
      const stored = el("td", "sample-transfer-num sample-transfer-stored", isNum(row.stored.c14_age) ? age(row.stored.c14_age, row.stored.c14_age_sig) : "—");
      tr.append(stored);
      const status = el("td", "raw-currents-status");
      status.append(chip(row.status, STATUS_TEXT[row.status] || row.status));
      tr.append(status);
      tbody.append(tr);

      if (open) {
        const sub = el("tr", "sample-transfer-targets");
        const cell = el("td", "");
        cell.colSpan = 6;
        const table = el("table", "sample-transfer-target-table");
        table.setAttribute("data-table-plain", "");
        const inner = el("tbody");
        row.targets.forEach((target) => inner.append(targetRow(row, target)));
        table.append(inner);
        cell.append(table);
        sub.append(cell);
        tbody.append(sub);
      }
      return tbody;
    };

    let plan = null;
    const renderSample = (row) => {
      const old = body.querySelector(`tbody[data-sample="${row.sample_nr}"]`);
      if (old) old.replaceWith(sampleBlock(row));
    };

    const render = (next) => {
      const firstRender = !plan;
      plan = next;
      const wrapBefore = body.querySelector(".sample-transfer-wrap");
      const scrollTop = wrapBefore ? wrapBefore.scrollTop : 0;
      body.textContent = "";
      if (plan.refusal) {
        showError(plan.refusal, "");
        return;
      }
      if (firstRender) {
        unfolded = new Set(
          plan.rows
            .filter((row) => row.status === "choose" && row.targets.filter((t) => t.measured).length <= OPEN_UP_TO)
            .map((row) => row.sample_nr),
        );
      }
      const c = plan.counts;
      const summary = el("p", "record-action-from");
      if (plan.writes) {
        summary.append(el("strong", "", plural(plan.writes, "sample", "samples")));
        summary.append(document.createTextNode(" to transfer"));
      } else {
        summary.append(el("strong", "", "Nothing to transfer yet"));
      }
      const parts = [`${c.new} new`, `${c.replaces} replace a stored result`, `${c.same} same`];
      if (c.choose) parts.push(`${c.choose} wait for your choice`);
      if (c.skip) parts.push(`${c.skip} left out`);
      if (c.not_measured) parts.push(`${c.not_measured} not measured`);
      if (c.invalid) parts.push(`${c.invalid} cannot be transferred`);
      summary.append(document.createTextNode(`: ${parts.join(" · ")}.`));
      body.append(summary);
      const notes = [
        "Tick one target to transfer its result, or several for a weighted mean (FM weighted by 1/σ², age from the mean FM, calibrated ranges cleared).",
      ];
      if (plan.standards) notes.push(`${plural(plan.standards, "standard is", "standards are")} not transferred.`);
      notes.forEach((note) => body.append(el("p", "raw-currents-note", note)));

      const wrap = el("div", "sample-transfer-wrap");
      const table = el("table", "sample-transfer-table");
      table.setAttribute("data-table-plain", "");
      const head = el("tr");
      ["Sample #", "Sample Label", "Targets", "Transfers", "Stored", ""].forEach((label) => head.append(el("th", "", label)));
      const thead = el("thead");
      thead.append(head);
      table.append(thead);
      plan.rows.forEach((row) => table.append(sampleBlock(row)));
      wrap.append(table);
      body.append(wrap);
      wrap.scrollTop = scrollTop;
      setSubmit(plan.writes);
      choicesField.value = choicesJson();
    };

    async function load() {
      const thisRequest = ++requestId;
      if (!plan) {
        body.textContent = "";
        body.append(el("p", "record-action-loading", "Reading the samples and their targets …"));
      }
      setSubmit(0);
      try {
        const params = new URLSearchParams({ magazine });
        const choices = choicesJson();
        if (choices) params.set("choices", choices);
        const response = await fetch(`/lab/analysis/magazine/transfer/preview?${params}`, { headers: { Accept: "application/json" } });
        if (thisRequest !== requestId) return;
        let payload = null;
        try {
          payload = await response.json();
        } catch (_error) {
          payload = null;
        }
        if (!response.ok || !payload) {
          showError(payload?.error || `Loading failed (HTTP ${response.status}).`, "Reload the page and try again.");
          return;
        }
        if (!ticks) {
          ticks = new Map(payload.rows.map((row) => [String(row.sample_nr), new Set(row.chosen)]));
        }
        render(payload);
      } catch (_error) {
        if (thisRequest !== requestId) return;
        showError("The server could not be reached.", "Check the connection and try again.");
      }
    }

    body.addEventListener("change", (event) => {
      const box = event.target.closest("input[type=checkbox][data-ref]");
      if (!box || !ticks) return;
      const refs = ticks.get(box.dataset.sample) || new Set();
      if (box.checked) refs.add(box.dataset.ref);
      else refs.delete(box.dataset.ref);
      ticks.set(box.dataset.sample, refs);
      setSubmit(0); // wait for the new preview
      window.clearTimeout(timer);
      timer = window.setTimeout(load, 200);
    });

    const open = () => {
      if (menu) menu.hidden = true;
      toggle?.setAttribute("aria-expanded", "false");
      submit.classList.remove("is-saving");
      ticks = null;
      plan = null;
      if (!dialog.open) dialog.showModal();
      load();
    };

    opener.addEventListener("click", open);
    dialog.querySelectorAll("[data-sample-transfer-cancel]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    // Page shortcuts must not fire under the dialog.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") event.stopPropagation();
    });
    form.addEventListener("submit", (event) => {
      if (submit.disabled) {
        event.preventDefault();
        return;
      }
      choicesField.value = choicesJson();
      submit.classList.add("is-saving");
      window.setTimeout(() => {
        submit.disabled = true;
      }, 0);
    });

    // ---- #action=transfer-results: the command palette's entry -------------
    const openFromHash = () => {
      if (window.location.hash !== "#action=transfer-results") return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      open();
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
  };
})();
