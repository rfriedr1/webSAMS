/* EA checks: entry strip (number box ↔ gauge), sparkline, control charts,
   review / void dialogs, and the Graph Batch Builder hint.

   Loaded only on Lab → Graphitization, Lab → EA Checks and the QC sign-off
   print view. Everything user-written (names, comments) is set with
   textContent — never innerHTML. The server re-validates every post; this
   script only makes entry fast and shows the verdict while typing. */
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const OPERATOR_KEY = "sams.eaCheck.operator";
  const WEIGHT_MAX_MG = 100; // keep in step with ea_checks.WEIGHT_MAX_MG
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const readJson = (node, fallback) => {
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || "null") ?? fallback;
    } catch (_err) {
      return fallback;
    }
  };

  const storage = {
    get(key) {
      try { return window.localStorage.getItem(key); } catch (_err) { return null; }
    },
    set(key, value) {
      try { window.localStorage.setItem(key, value); } catch (_err) { /* private mode */ }
    },
  };

  const parseNumber = (raw) => {
    const text = String(raw ?? "").trim().replace(",", ".");
    if (text === "" || !/^[-+]?\d*\.?\d+$/.test(text)) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  };

  const svg = (name, attrs = {}) => {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };

  const fmt = (value, digits = 2) => (value == null ? "—" : Number(value).toFixed(digits));

  // ---- One element field: number box + gauge ------------------------------

  const installField = (field, onChange) => {
    const number = field.querySelector("[data-ea-number]");
    const range = field.querySelector("[data-ea-range]");
    const gauge = field.querySelector("[data-ea-gauge]");
    const verdict = field.querySelector("[data-ea-verdict]");
    const ticks = field.querySelector("[data-ea-ticks]");
    const d = field.dataset;
    const spec = {
      label: d.label,
      min: Number(d.min), max: Number(d.max), ref: Number(d.ref),
      step: Number(d.step), lo: Number(d.lo), hi: Number(d.hi), decimals: Number(d.decimals || 1),
    };
    let touched = false;

    // Ticks: one per step, thinned (×5, ×10) until ≥ 4 px apart; majors at whole numbers.
    const drawTicks = () => {
      if (!ticks) return;
      ticks.replaceChildren();
      const width = ticks.getBoundingClientRect().width || 280;
      const span = spec.hi - spec.lo;
      let minor = spec.step;
      for (const factor of [1, 5, 10, 20]) {
        minor = spec.step * factor;
        if ((width / span) * minor >= 4) break;
      }
      const first = Math.ceil(spec.lo / minor - 1e-9) * minor;
      for (let v = first; v <= spec.hi + 1e-9; v += minor) {
        const tick = document.createElement("span");
        const isMajor = Math.abs(v - Math.round(v)) < 1e-6;
        tick.className = isMajor ? "is-major" : "";
        tick.style.left = `${((v - spec.lo) / span) * 100}%`;
        ticks.appendChild(tick);
      }
    };

    const state = () => {
      const value = parseNumber(number.value);
      if (value == null) return { value: null, ok: null };
      return { value, ok: value >= spec.min && value <= spec.max };
    };

    const render = () => {
      const { value, ok } = state();
      gauge.classList.toggle("is-untouched", !touched || value == null);
      gauge.classList.toggle("is-out", ok === false);
      field.classList.toggle("is-out", ok === false);
      field.classList.toggle("is-in", ok === true);
      if (value == null) {
        verdict.textContent = number.value.trim() ? "not a number" : "";
        range.setAttribute("aria-valuetext", `${spec.label} % not set`);
      } else {
        verdict.textContent = ok ? "✓ in window" : `✗ outside ${spec.min}–${spec.max}`;
        range.setAttribute("aria-valuetext", `${spec.label} ${value} %, ${ok ? "within" : "outside"} window`);
      }
      onChange();
    };

    const setFromRange = () => {
      touched = true;
      number.value = Number(range.value).toFixed(spec.decimals);
      render();
    };

    number.addEventListener("input", () => {
      const value = parseNumber(number.value);
      if (value != null) {
        touched = true;
        range.value = String(Math.min(Math.max(value, spec.lo), spec.hi));
      }
      render();
    });
    range.addEventListener("input", setFromRange);
    range.addEventListener("change", setFromRange);

    // Wheel over the gauge moves one step; the page does not scroll meanwhile.
    gauge.addEventListener("wheel", (event) => {
      event.preventDefault();
      const base = touched && parseNumber(number.value) != null ? Number(range.value) : spec.ref;
      const next = base + (event.deltaY < 0 ? spec.step : -spec.step) * (touched ? 1 : 0);
      range.value = String(Math.min(Math.max(next, spec.lo), spec.hi));
      setFromRange();
    }, { passive: false });

    drawTicks();
    render();
    return {
      field,
      spec,
      state,
      redraw: drawTicks,
      focus: () => number.focus(),
      isActive: () => !field.closest("fieldset")?.disabled,
    };
  };

  // ---- Hover tooltip (sparklines and control charts) -------------------------

  const tooltip = (() => {
    let node = null;
    return {
      show(host, lines, left, top) {
        if (!node) {
          node = document.createElement("div");
          node.className = "ea-chart-tooltip";
          node.setAttribute("role", "status");
        }
        host.appendChild(node);
        node.replaceChildren(...lines.map((line, i) => {
          const row = document.createElement(i === 0 ? "strong" : "span");
          row.textContent = line;
          return row;
        }));
        node.hidden = false;
        const maxLeft = host.clientWidth - node.offsetWidth - 4;
        node.style.left = `${Math.max(4, Math.min(left + 12, maxLeft))}px`;
        node.style.top = `${Math.max(0, top - node.offsetHeight - 10)}px`;
      },
      hide() { if (node) node.hidden = true; },
    };
  })();

  // ---- Sparkline ------------------------------------------------------------

  const drawSpark = (node, spark) => {
    if (!node || !spark?.element || !spark.points?.length) return;
    const el = spark.element;
    // Zoomed on the values and the reference (like the control charts);
    // the window band is clipped to that range.
    const values = spark.points.map((p) => p.v);
    let lo = Math.min(el.ref, ...values);
    let hi = Math.max(el.ref, ...values);
    const minSpan = Math.max(el.step * 6, (el.max - el.min) * 0.04);
    if (hi - lo < minSpan) {
      lo = (hi + lo) / 2 - minSpan / 2;
      hi = lo + minSpan;
    }
    const pad = (hi - lo) * 0.1;
    const y = (v) => 44 - ((Math.min(Math.max(v, lo - pad), hi + pad) - (lo - pad)) / (hi - lo + 2 * pad)) * 40;
    const x = (i) => (spark.points.length === 1 ? 150 : 4 + (i / (spark.points.length - 1)) * 292);
    node.replaceChildren(
      svg("rect", { x: 0, y: y(el.max), width: 300, height: Math.max(y(el.min) - y(el.max), 0), class: "spark-window" }),
      svg("line", { x1: 0, x2: 300, y1: y(el.ref), y2: y(el.ref), class: "spark-ref" }),
      svg("polyline", { points: spark.points.map((p, i) => `${x(i)},${y(p.v)}`).join(" "), class: "spark-line" }),
    );
    spark.points.forEach((p, i) => {
      if (!p.passed || i === spark.points.length - 1) {
        node.appendChild(svg("circle", { cx: x(i), cy: y(p.v), r: 2.6, class: p.passed ? "spark-last" : "spark-fail" }));
      }
    });

    // Hover: the nearest check's date, value and verdict.
    const cursor = svg("line", { x1: 0, x2: 0, y1: 0, y2: 48, class: "spark-cursor", visibility: "hidden" });
    node.appendChild(cursor);
    const host = node.parentElement;
    node.addEventListener("pointermove", (event) => {
      const box = node.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * 300;
      let best = 0;
      spark.points.forEach((_, i) => {
        if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
      });
      const p = spark.points[best];
      cursor.setAttribute("x1", x(best));
      cursor.setAttribute("x2", x(best));
      cursor.setAttribute("visibility", "visible");
      const lines = [
        `${p.checked_at || ""} · ${el.label} ${p.v.toFixed(2)} %`,
        `${p.passed ? "✓ pass" : "✗ fail"}${p.operator ? ` · ${p.operator}` : ""}`,
      ];
      // SVG elements have no offsetTop/offsetLeft: measure against the host.
      const hostBox = host.getBoundingClientRect();
      tooltip.show(
        host,
        lines,
        box.left - hostBox.left + (x(best) / 300) * box.width,
        box.top - hostBox.top + (y(p.v) / 48) * box.height,
      );
    });
    node.addEventListener("pointerleave", () => {
      cursor.setAttribute("visibility", "hidden");
      tooltip.hide();
    });
  };

  // ---- Entry card -------------------------------------------------------------

  const installCard = (card) => {
    const form = card.querySelector("[data-ea-entry]");
    const config = readJson(card.querySelector("[data-ea-card-config]"), {});
    (config.sparks || []).forEach((spark) => {
      drawSpark(card.querySelector(`[data-ea-spark][data-symbol="${spark.symbol}"]`), spark);
    });
    if (!form) return;

    const submit = form.querySelector("[data-ea-submit]");
    const submitLabel = form.querySelector("[data-ea-submit-label]");
    const hint = form.querySelector("[data-ea-hint]");
    const comment = form.querySelector("[data-ea-comment]");
    const commentInput = form.querySelector("[data-ea-comment-input]");
    const commentLabel = form.querySelector("[data-ea-comment-label]");
    const noteToggle = form.querySelector("[data-ea-note-toggle]");
    const standardSelect = form.querySelector("[data-ea-standard]");
    let noteOpen = false;
    // Filled below; `update` runs from each field's first render, so the
    // list must exist (empty) before any field is installed.
    let fields = [];

    const activeFields = () => fields.filter((f) => f.isActive());

    const update = () => {
      const states = activeFields().map((f) => f.state());
      const anyOut = states.some((s) => s.ok === false);
      comment.hidden = !(anyOut || noteOpen);
      noteToggle.hidden = anyOut || noteOpen;
      commentInput.required = anyOut;
      commentLabel.textContent = anyOut ? "Comment — required, the check is out of the window" : "Note (optional)";
      submitLabel.textContent = anyOut ? "Log failed check" : "Log check";
      submit.classList.toggle("is-fail", anyOut);
      if (hint.dataset.sticky !== "1") hint.textContent = "";
    };

    fields = Array.from(form.querySelectorAll("[data-ea-field]")).map((f) => installField(f, () => update()));

    standardSelect?.addEventListener("change", () => {
      form.querySelectorAll("[data-ea-standard-fields]").forEach((set) => {
        const on = set.dataset.eaStandardFields === standardSelect.value;
        set.hidden = !on;
        set.disabled = !on;
      });
      fields.forEach((f) => f.isActive() && f.redraw());
      update();
    });

    // Weight of the standard (mg): optional; flagged while it is not a
    // plausible number (mirrors ea_checks.parse_weight on the server).
    const weight = form.querySelector("[data-ea-weight]");
    const weightProblem = () => {
      const text = (weight?.value || "").trim().replace(",", ".");
      if (!text) return "";
      const value = Number(text);
      if (!Number.isFinite(value)) return "Weight is not a number.";
      if (value <= 0 || value > WEIGHT_MAX_MG) return `Weight must be between 0 and ${WEIGHT_MAX_MG} mg.`;
      return "";
    };
    weight?.addEventListener("input", () => {
      weight.classList.toggle("is-invalid", Boolean(weightProblem()));
      weight.setAttribute("aria-invalid", weightProblem() ? "true" : "false");
    });

    noteToggle?.addEventListener("click", () => {
      noteOpen = true;
      update();
      commentInput.focus();
    });

    // Operator chips remember the last person on this computer.
    const remembered = storage.get(OPERATOR_KEY);
    const chips = Array.from(form.querySelectorAll("[data-ea-operator]"));
    const match = chips.find((chip) => chip.value === remembered);
    if (match) match.checked = true;
    chips.forEach((chip) => chip.addEventListener("change", () => {
      if (chip.checked) {
        storage.set(OPERATOR_KEY, chip.value);
        document.querySelectorAll(`[data-ea-operator][value="${CSS.escape(chip.value)}"]`).forEach((other) => { other.checked = true; });
      }
    }));

    const say = (message) => {
      hint.textContent = message;
      hint.dataset.sticky = "1";
      window.setTimeout(() => { hint.dataset.sticky = ""; }, 2500);
    };

    form.addEventListener("submit", (event) => {
      const active = activeFields();
      const missing = active.filter((f) => f.state().value == null);
      if (missing.length) {
        event.preventDefault();
        say(`Set ${active.map((f) => `${f.spec.label} %`).join(" and ")} first.`);
        missing[0].focus();
        return;
      }
      if (weightProblem()) {
        event.preventDefault();
        say(weightProblem());
        weight.focus();
        return;
      }
      const operatorField = form.querySelector("[name=operator]:checked, input[type=text][name=operator]");
      if (!operatorField || !String(operatorField.value).trim()) {
        event.preventDefault();
        say("Pick who measured it.");
        return;
      }
      if (commentInput.required && !commentInput.value.trim()) {
        event.preventDefault();
        say("Add a short comment for the failed check.");
        commentInput.focus();
        return;
      }
      submit.disabled = true;
      submit.classList.add("is-busy");
    });

    const another = card.querySelector("[data-ea-another]");
    another?.addEventListener("click", () => {
      form.hidden = false;
      another.hidden = true;
      another.setAttribute("aria-expanded", "true");
      fields.forEach((f) => f.redraw());
      activeFields()[0]?.focus();
    });

    window.addEventListener("resize", () => fields.forEach((f) => f.isActive() && f.redraw()));
    update();
  };

  // ---- Control chart ----------------------------------------------------------


  const drawChart = (figure, data) => {
    const canvas = figure.querySelector("[data-ea-chart-canvas]");
    const symbol = figure.dataset.symbol;
    const el = (data.elements || []).find((e) => e.symbol === symbol);
    const stats = (data.stats || []).find((s) => s.symbol === symbol) || {};
    const points = (data.points || [])
      .map((p) => ({ ...p, v: p[`conc_${symbol}`], t: new Date(p.checked_at.replace(" ", "T")).getTime() }))
      .filter((p) => p.v != null && Number.isFinite(p.t));
    const width = Math.max(canvas.clientWidth, 260);
    if (!el || !points.length || !canvas.clientWidth) return;
    const height = 190;
    const m = { top: 10, right: 46, bottom: 24, left: 8 };
    const w = width - m.left - m.right;
    const h = height - m.top - m.bottom;

    // The y-axis spans the allowable range (pass window), widened only as far
    // as needed to keep every plotted point on the chart — so the band's
    // limits are always visible and the scatter reads against them.
    const values = points.map((p) => p.v);
    const lo = Math.min(el.min, el.ref, ...values);
    const hi = Math.max(el.max, el.ref, ...values);
    const pad = (hi - lo) * 0.08;
    const y0 = lo - pad;
    const y1 = hi + pad;
    const t0 = points[0].t;
    const t1 = points[points.length - 1].t;
    const x = (t, i) => m.left + (t1 > t0 ? ((t - t0) / (t1 - t0)) * w : (points.length > 1 ? (i / (points.length - 1)) * w : w / 2));
    const y = (v) => m.top + (1 - (v - y0) / (y1 - y0)) * h;

    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "ea-chart-svg", role: "img" });
    const title = svg("title");
    title.textContent = `${el.label} % control chart: ${points.length} checks, mean ${fmt(stats.mean)}, reference ${el.ref}, window ${el.min}–${el.max}`;
    root.appendChild(title);
    const clampY = (v) => Math.min(Math.max(v, y0), y1);
    root.appendChild(svg("rect", {
      x: m.left, y: y(clampY(el.max)), width: w,
      height: Math.max(y(clampY(el.min)) - y(clampY(el.max)), 0), class: "chart-window",
    }));

    const hline = (value, cls, label) => {
      if (value == null || value < y0 || value > y1) return;
      root.appendChild(svg("line", { x1: m.left, x2: m.left + w, y1: y(value), y2: y(value), class: cls }));
      if (label) {
        const text = svg("text", { x: m.left + w + 4, y: y(value) + 3.5, class: `chart-label ${cls}-label` });
        text.textContent = label;
        root.appendChild(text);
      }
    };
    const nearRef = (v) => Math.abs(y(v) - y(el.ref)) < 11;
    hline(el.max, "chart-limit", nearRef(el.max) ? "" : fmt(el.max, 1));
    hline(el.min, "chart-limit", nearRef(el.min) ? "" : fmt(el.min, 1));
    hline(stats.hi3, "chart-3s", "");
    hline(stats.lo3, "chart-3s", "");
    hline(stats.hi2, "chart-2s", "");
    hline(stats.lo2, "chart-2s", "");
    hline(el.ref, "chart-ref", fmt(el.ref));
    // Window limits outside the zoomed range: say where they are, inside
    // the plot's top/bottom-left corner (the right edge holds the scale).
    [[el.max, m.top + 11, "▲ window max"], [el.min, m.top + h - 4, "▼ window min"]].forEach(([limit, at, words]) => {
      if (limit >= y0 && limit <= y1) return;
      const text = svg("text", { x: m.left + 4, y: at, class: "chart-label chart-window-note" });
      text.textContent = `${words} ${fmt(limit, 1)}`;
      root.appendChild(text);
    });
    // A few value ticks on the right so the zoomed scale is readable;
    // skipped where a labelled line (reference, window limit) already sits.
    const labelled = [el.ref, el.min, el.max].filter((v) => v >= y0 && v <= y1);
    const tickStep = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5].find((st) => (y1 - y0) / st <= 6) || 10;
    const minGap = ((y1 - y0) / h) * 11; // ~11 px in value units
    for (let v = Math.ceil(y0 / tickStep) * tickStep; v <= y1; v += tickStep) {
      if (labelled.some((l) => Math.abs(v - l) < minGap)) continue;
      root.appendChild(svg("line", { x1: m.left + w, x2: m.left + w + 3, y1: y(v), y2: y(v), class: "chart-tick" }));
      const text = svg("text", { x: m.left + w + 5, y: y(v) + 3.5, class: "chart-axis" });
      text.textContent = v.toFixed(tickStep < 0.1 ? 2 : tickStep < 1 ? 1 : 0);
      root.appendChild(text);
    }

    // x axis: first / last date (and month starts when the span is long)
    const axis = (t, anchor) => {
      const text = svg("text", { x: Math.min(Math.max(x(t, 0), m.left), m.left + w), y: height - 6, class: "chart-axis", "text-anchor": anchor });
      text.textContent = new Date(t).toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "2-digit" });
      root.appendChild(text);
    };
    axis(t0, "start");
    if (t1 > t0) axis(t1, "end");

    root.appendChild(svg("polyline", { points: points.map((p, i) => `${x(p.t, i)},${y(p.v)}`).join(" "), class: "chart-line" }));
    points.forEach((p, i) => {
      const unusual = stats.sd && Math.abs(p.v - stats.mean) > 3 * stats.sd;
      root.appendChild(svg("circle", {
        cx: x(p.t, i), cy: y(p.v), r: p.passed ? 3.2 : 4.2,
        class: `chart-point${p.passed ? "" : " is-fail"}${unusual ? " is-unusual" : ""}`,
      }));
    });

    const cursor = svg("line", { x1: 0, x2: 0, y1: m.top, y2: m.top + h, class: "chart-cursor", visibility: "hidden" });
    root.appendChild(cursor);
    root.addEventListener("pointermove", (event) => {
      const box = root.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      let best = 0;
      points.forEach((p, i) => {
        if (Math.abs(x(p.t, i) - px) < Math.abs(x(points[best].t, best) - px)) best = i;
      });
      const p = points[best];
      const cx = x(p.t, best);
      cursor.setAttribute("x1", cx);
      cursor.setAttribute("x2", cx);
      cursor.setAttribute("visibility", "visible");
      const lines = [`${p.checked_at} · ${el.label} ${fmt(p.v)} %`, `${p.passed ? "✓ pass" : "✗ fail"} · ${p.operator}`];
      if (p.comment) lines.push(p.comment);
      tooltip.show(canvas, lines, (cx / width) * canvas.clientWidth, (y(p.v) / height) * canvas.clientHeight);
    });
    root.addEventListener("pointerleave", () => {
      cursor.setAttribute("visibility", "hidden");
      tooltip.hide();
    });
    canvas.replaceChildren(root);
  };

  const drawChartsIn = (scope) => {
    scope.querySelectorAll(".ea-charts").forEach((box) => {
      const data = readJson(box.querySelector("[data-ea-chart-data]"), null);
      if (!data) return;
      box.querySelectorAll("[data-ea-chart]").forEach((figure) => drawChart(figure, data));
    });
  };

  // ---- Dialogs ------------------------------------------------------------------

  const installDialogs = () => {
    document.querySelectorAll("[data-ea-review-open]").forEach((button) => {
      button.addEventListener("click", () => {
        const dialog = document.getElementById(button.dataset.eaReviewOpen);
        if (!dialog?.showModal) return;
        dialog.showModal();
        drawChartsIn(dialog);
      });
    });
    document.querySelectorAll("[data-ea-dialog-close]").forEach((button) => {
      button.addEventListener("click", () => button.closest("dialog")?.close());
    });
    document.querySelectorAll("dialog.ea-review").forEach((dialog) => {
      dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
      // The record shortcuts (e, [, ] …) must not fire under an open dialog.
      dialog.addEventListener("keydown", (event) => event.stopPropagation());
      const comment = dialog.querySelector("[data-ea-review-comment]");
      const commentLabel = dialog.querySelector("[data-ea-review-comment-label]");
      dialog.querySelectorAll("[data-ea-verdict-choice]").forEach((choice) => {
        choice.addEventListener("change", () => {
          const needs = choice.checked && choice.value !== "accepted";
          if (!choice.checked) return;
          comment.required = needs;
          commentLabel.textContent = needs ? "Comment (required for this verdict)" : "Comment (optional)";
        });
      });
    });

    const voidDialog = document.querySelector("[data-ea-void-dialog]");
    if (voidDialog?.showModal) {
      const form = voidDialog.querySelector("[data-ea-void-form]");
      const label = voidDialog.querySelector("[data-ea-void-label]");
      document.querySelectorAll("[data-ea-void-open]").forEach((button) => {
        button.addEventListener("click", () => {
          form.action = `/lab/ea-checks/${encodeURIComponent(button.dataset.eaVoidOpen)}/void`;
          label.textContent = button.dataset.eaVoidLabel || "";
          voidDialog.showModal();
          form.querySelector("[name=reason]")?.focus();
        });
      });
    }
  };

  // ---- Boot -------------------------------------------------------------------------

  const boot = () => {
    document.querySelectorAll("[data-ea-card]").forEach(installCard);
    drawChartsIn(document);
    installDialogs();
    document.querySelector("[data-ea-filter]")?.querySelectorAll("select").forEach((select) => {
      select.addEventListener("change", () => select.form.requestSubmit());
    });
    document.querySelector("[data-qc-print]")?.addEventListener("click", () => window.print());
    let timer = 0;
    window.addEventListener("resize", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => drawChartsIn(document), reducedMotion ? 0 : 120);
    });
    window.addEventListener("beforeprint", () => drawChartsIn(document));
  };

  if (document.readyState === "complete") boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
