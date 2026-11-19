// Photo bench (Samples → Photos): webcam feed, camera controls, label
// reading and saving photos into the photo folder.
//
// Photo first, number second. A shot is decoded for the label's QR /
// DataMatrix code; when that names a sample the bench is not on, a
// suggestion card asks the operator to confirm it (Enter) or reject it
// (Esc). Nothing is ever saved under a number that was neither confirmed
// nor typed. Without a readable label the number is typed or scanned.
//
// The "New photos" tray always belongs to the bench's current sample; each
// shot's chip says whether its label agrees (✓), names another sample (≠)
// or could not be read. Saving posts the JPEGs to /samples/<nr>/photos,
// which picks the file names (<nr>.jpg, <nr>_2.jpg …) and the range folder.
//
// Camera settings are kept per browser (i.e. per bench PC) in
// localStorage, like the benches' "Balance g → mg" switch.
//
// Label decoding: the browser's own BarcodeDetector where it exists
// (macOS Chrome), otherwise zxing-wasm 3.1.6, vendored under
// /static/vendor/zxing-wasm (no internet needed).
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});
  const SETTINGS_KEY = "sams_photo_bench_camera";
  const JPEG_QUALITY = 0.92;
  const LIVE_INTERVAL_MS = 350;
  const LIVE_MAX_WIDTH = 960;
  const LIVE_HINT_HOLD_MS = 1500;
  const LABEL_FORMATS = ["QRCode", "DataMatrix", "MicroQRCode"];

  // ---- label text → sample number -------------------------------------
  // Mirrors `sample_nr_from_label` in sams_web/photo_bench.py: the number
  // alone, `MAMS-48211`, or a text with exactly one run of 3+ digits.
  const labelSampleNr = (text) => {
    const cleaned = String(text || "").trim();
    if (cleaned === "") return null;
    if (/^\d+$/.test(cleaned)) {
      const nr = Number.parseInt(cleaned, 10);
      return nr > 0 ? nr : null;
    }
    const mams = cleaned.match(/MAMS[\s:_-]*0*(\d{1,7})\b/i);
    if (mams) {
      const nr = Number.parseInt(mams[1], 10);
      return nr > 0 ? nr : null;
    }
    const runs = (cleaned.match(/\d+/g) || []).filter((run) => run.length >= 3);
    if (runs.length === 1) {
      const nr = Number.parseInt(runs[0], 10);
      return nr > 0 ? nr : null;
    }
    return null;
  };

  // ---- small helpers ----------------------------------------------------
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const toast = (message, kind = "info", options) => {
    if (window.SAMSToast && typeof window.SAMSToast.show === "function") {
      window.SAMSToast.show(message, kind, options);
    }
  };

  const loadSettings = () => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(SETTINGS_KEY) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  };

  const saveSettings = (settings) => {
    try {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (_error) {
      // Storage blocked: the settings hold until the page is left.
    }
  };

  const isTypingTarget = (target) =>
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

  const canvasToBlob = (canvas) =>
    new Promise((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("toBlob failed"))), "image/jpeg", JPEG_QUALITY);
    });

  // ---- label decoder ------------------------------------------------------
  const createDecoder = (wasmUrl) => {
    let ready = null;

    const nativeDetector = async () => {
      if (!("BarcodeDetector" in window)) return null;
      try {
        const supported = await window.BarcodeDetector.getSupportedFormats();
        const wanted = ["qr_code", "data_matrix"].filter((format) => supported.includes(format));
        if (!wanted.length) return null;
        const detector = new window.BarcodeDetector({ formats: wanted });
        return async (source) => (await detector.detect(source)).map((code) => code.rawValue);
      } catch (_error) {
        return null;
      }
    };

    const zxingReader = async () => {
      const zxing = window.ZXingWASM;
      if (!zxing || typeof zxing.readBarcodes !== "function") return null;
      await zxing.prepareZXingModule({
        overrides: {
          locateFile: (path, prefix) => (path.endsWith(".wasm") ? wasmUrl : prefix + path),
        },
        fireImmediately: true,
      });
      return async (source, quick) => {
        const imageData = source instanceof ImageData ? source : null;
        if (!imageData) return [];
        const results = await zxing.readBarcodes(imageData, {
          formats: LABEL_FORMATS,
          tryHarder: !quick,
          maxNumberOfSymbols: 4,
        });
        return results.filter((result) => result.isValid).map((result) => result.text);
      };
    };

    const init = () => {
      if (!ready) {
        ready = (async () => {
          const native = await nativeDetector();
          if (native) return { kind: "native", read: native };
          try {
            const reader = await zxingReader();
            return reader ? { kind: "zxing", read: reader } : null;
          } catch (error) {
            console.warn("Photo bench: the label reader could not start", error);
            return null;
          }
        })();
      }
      return ready;
    };

    // Reads every label code on `canvas`. Returns the decoded texts.
    const read = async (canvas, { quick = false } = {}) => {
      const decoder = await init();
      if (!decoder) return null;
      try {
        if (decoder.kind === "native") return await decoder.read(canvas);
        const context = canvas.getContext("2d", { willReadFrequently: true });
        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
        return await decoder.read(imageData, quick);
      } catch (error) {
        console.warn("Photo bench: label decoding failed", error);
        return [];
      }
    };

    return { init, read };
  };

  // What a shot's label codes say: one number, several, or none.
  const interpretCodes = (texts) => {
    if (texts === null) return { state: "noreader", nrs: [], text: "" };
    const nrs = [...new Set(texts.map(labelSampleNr).filter((nr) => nr !== null))];
    return { state: nrs.length === 1 ? "one" : nrs.length > 1 ? "several" : "none", nrs, text: texts[0] || "" };
  };

  // ---- camera controls ----------------------------------------------------
  // Numeric controls a UVC webcam may report (`track.getCapabilities()`).
  // `mode` names the auto/manual switch the value only works under.
  const CONTROLS = [
    { key: "brightness", label: "Brightness" },
    { key: "contrast", label: "Contrast" },
    { key: "saturation", label: "Saturation" },
    { key: "sharpness", label: "Sharpness" },
    { key: "exposureCompensation", label: "Exposure compensation" },
    { key: "exposureTime", label: "Exposure time", mode: "exposureMode" },
    { key: "colorTemperature", label: "White balance (K)", mode: "whiteBalanceMode" },
    { key: "focusDistance", label: "Focus", mode: "focusMode" },
    { key: "zoom", label: "Zoom" },
  ];
  const MODE_LABELS = {
    exposureMode: "Auto exposure",
    whiteBalanceMode: "Auto white balance",
    focusMode: "Autofocus",
  };
  // Used when the camera has no brightness / contrast of its own: applied
  // to the preview (CSS) and to every shot (canvas filter), in percent.
  const SOFT_CONTROLS = [
    { key: "softBrightness", label: "Brightness", min: 50, max: 160, step: 1, unit: "%" },
    { key: "softContrast", label: "Contrast", min: 50, max: 160, step: 1, unit: "%" },
  ];

  installers.installPhotoBench = () => {
    const bench = document.querySelector("[data-photo-bench]");
    if (!(bench instanceof HTMLElement) || bench.dataset.photoBenchInstalled === "true") return;
    bench.dataset.photoBenchInstalled = "true";

    const q = (selector) => bench.querySelector(selector);
    const lookupForm = q("[data-photo-bench-lookup-form]");
    const sampleInput = q("[data-photo-bench-sample-input]");
    const openLink = q("[data-photo-bench-open]");
    const factsHost = q("[data-photo-bench-facts]");
    const video = q("[data-photo-bench-video]");
    const stage = q("[data-photo-bench-stage]");
    const cameraNote = q("[data-photo-bench-camera-note]");
    const liveHint = q("[data-photo-bench-live-hint]");
    const captureButton = q("[data-photo-bench-capture]");
    const fileInput = q("[data-photo-bench-file]");
    const resolutionLabel = q("[data-photo-bench-resolution]");
    const controlGrid = q("[data-photo-bench-control-grid]");
    const controlsNote = q("[data-photo-bench-controls-note]");
    const deviceRow = q("[data-photo-bench-device-row]");
    const deviceSelect = q("[data-photo-bench-device]");
    const resetButton = q("[data-photo-bench-reset]");
    const suggestionBox = q("[data-photo-bench-suggestion]");
    const suggestionTitle = q("[data-photo-bench-suggestion-title]");
    const suggestionFacts = q("[data-photo-bench-suggestion-facts]");
    const suggestionNote = q("[data-photo-bench-suggestion-note]");
    const confirmButton = q("[data-photo-bench-suggestion-confirm]");
    const rejectButton = q("[data-photo-bench-suggestion-reject]");
    const tray = q("[data-photo-bench-tray]");
    const trayEmpty = q("[data-photo-bench-tray-empty]");
    const shotCount = q("[data-photo-bench-shot-count]");
    const discardButton = q("[data-photo-bench-discard]");
    const saveButtons = Array.from(bench.querySelectorAll("[data-photo-bench-save]"));
    const dialog = q("[data-photo-bench-dialog]");
    const canEdit = bench.dataset.photoBenchCanEdit === "1";
    const maxFiles = Number.parseInt(bench.dataset.photoBenchMaxFiles || "10", 10);
    const maxBytes = Number.parseInt(bench.dataset.photoBenchMaxMb || "20", 10) * 1024 * 1024;

    const decoder = createDecoder(bench.dataset.photoBenchWasmUrl || "");
    const onFile = window.SAMSSamplePhotos
      ? window.SAMSSamplePhotos.mount(q("[data-sample-photos]"))
      : { load: () => {}, setSample: () => {} };

    const initialFacts = factsHost.querySelector("[data-photo-facts]");
    const initialNr = Number.parseInt(initialFacts?.dataset.photoFactsSample || "", 10);

    /** The bench's sample: confirmed from a label, typed, or loaded. */
    let current = Number.isFinite(initialNr) ? initialNr : null;
    /** @type {{id:number, blob:Blob, url:string, name:string, label:{state:string, nrs:number[], text:string}}[]} */
    let shots = [];
    let shotSerial = 0;
    /** Open suggestion: { nr, shot } */
    let suggestion = null;
    let saving = false;
    let stream = null;
    let track = null;
    let settings = loadSettings();
    let trackDefaults = {};

    // ---- dialog -------------------------------------------------------
    // ask({title, text, actions: [{value, label, primary?, focus?}]}) → value
    const ask = ({ title, text, actions }) =>
      new Promise((resolve) => {
        q("[data-photo-bench-dialog-title]").textContent = title;
        q("[data-photo-bench-dialog-text]").textContent = text;
        const host = q("[data-photo-bench-dialog-actions]");
        host.replaceChildren();
        let focusTarget = null;
        actions.forEach((action) => {
          const button = el("button", `bench-button${action.primary ? " is-primary" : action.ghost ? " is-ghost" : ""}`, action.label);
          button.type = "submit";
          button.value = action.value;
          if (action.focus) focusTarget = button;
          host.appendChild(button);
        });
        const onClose = () => {
          dialog.removeEventListener("close", onClose);
          resolve(dialog.returnValue || "cancel");
        };
        dialog.returnValue = "";
        dialog.addEventListener("close", onClose);
        dialog.showModal();
        (focusTarget || host.querySelector("button"))?.focus();
      });

    // ---- current sample, facts, tray ----------------------------------
    const shotStatus = (shot) => {
      const { state, nrs } = shot.label;
      if (state === "pending") return "pending";
      if (state === "one") return current !== null && nrs[0] === current ? "match" : current === null ? "found" : "mismatch";
      if (state === "several") return "several";
      return "none";
    };

    const chipFor = (shot) => {
      const status = shotStatus(shot);
      const nrs = shot.label.nrs;
      switch (status) {
        case "pending":
          return { text: "Reading label…", kind: "muted" };
        case "match":
          return { text: `✓ Label ${nrs[0]}`, kind: "ok", title: "The label in this photo names this sample." };
        case "found":
          return { text: `Label ${nrs[0]}`, kind: "info", title: "Confirm the sample, or type its number." };
        case "mismatch":
          return { text: `≠ Label ${nrs[0]}`, kind: "warn", title: `The label in this photo names sample ${nrs[0]}, not ${current}.` };
        case "several":
          return { text: `Several labels (${nrs.join(", ")})`, kind: "warn", title: "More than one sample label is in this photo." };
        default:
          return {
            text: shot.label.state === "noreader" ? "Label not checked" : "No label read",
            kind: "muted",
            title: shot.label.state === "noreader" ? "The label reader could not start in this browser." : "No label code was found in this photo.",
          };
      }
    };

    const renderTray = () => {
      const items = shots.map((shot, index) => {
        const item = el("li", "photo-bench-shot");
        const thumb = el("button", "photo-bench-shot-thumb");
        thumb.type = "button";
        thumb.title = `View photo ${index + 1}`;
        thumb.setAttribute("aria-label", `View photo ${index + 1}`);
        const img = el("img");
        img.alt = `New photo ${index + 1}`;
        img.src = shot.url;
        thumb.appendChild(img);
        thumb.addEventListener("click", () => {
          const list = shots.map((s, i) => ({ name: `New photo ${i + 1} (not saved)`, url: s.url, download_url: s.url }));
          window.SAMSSamplePhotos?.openViewer(list, index);
        });
        const remove = el("button", "photo-icon-button photo-bench-shot-remove", "×");
        remove.type = "button";
        remove.title = `Drop photo ${index + 1}`;
        remove.setAttribute("aria-label", `Drop photo ${index + 1}`);
        remove.addEventListener("click", () => dropShots([shot.id]));
        const chip = chipFor(shot);
        const label = el("span", `photo-bench-chip is-${chip.kind}`, chip.text);
        if (chip.title) label.title = chip.title;
        const caption = el("div", "photo-bench-shot-caption");
        caption.append(el("span", "photo-bench-shot-name", `${index + 1}`), label);
        item.append(thumb, remove, caption);
        return item;
      });
      tray.replaceChildren(...items);
      trayEmpty.hidden = shots.length > 0;
      shotCount.textContent = shots.length ? `${shots.length} not saved` : "";
      updateActions();
    };

    const updateActions = () => {
      const savable = canEdit && current !== null && shots.length > 0 && !saving && !suggestion;
      saveButtons.forEach((button) => {
        button.disabled = !savable;
      });
      if (discardButton) discardButton.disabled = shots.length === 0 || saving;
      captureButton.disabled = !track || saving;
      bench.classList.toggle("has-unsaved", shots.length > 0);
    };

    const dropShots = (ids) => {
      const drop = new Set(ids);
      shots.forEach((shot) => {
        if (drop.has(shot.id)) URL.revokeObjectURL(shot.url);
      });
      shots = shots.filter((shot) => !drop.has(shot.id));
      renderTray();
    };

    const parseFragment = (html) => {
      const template = document.createElement("template");
      // Server-rendered Jinja fragment (autoescaped): safe to parse.
      template.innerHTML = html;
      return template.content.querySelector("[data-photo-facts]");
    };

    const fetchFacts = async (params) => {
      const response = await fetch(`/samples/photos/facts?${new URLSearchParams(params)}`, {
        headers: { Accept: "text/html" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const fragment = parseFragment(await response.text());
      if (!fragment) throw new Error("No facts in the answer");
      const nr = Number.parseInt(fragment.dataset.photoFactsSample || "", 10);
      return { fragment, nr: Number.isFinite(nr) ? nr : null };
    };

    // Puts `nr` on the bench (facts line, Open link, On file strip, URL).
    const setCurrent = (nr, fragment) => {
      current = nr;
      factsHost.replaceChildren(fragment);
      sampleInput.value = nr === null ? "" : String(nr);
      if (openLink) {
        openLink.hidden = nr === null;
        openLink.href = nr === null ? "#" : `/samples/${nr}`;
      }
      onFile.setSample(nr);
      const url = new URL(window.location.href);
      if (nr === null) url.searchParams.delete("sample_nr");
      else url.searchParams.set("sample_nr", String(nr));
      window.history.replaceState(window.history.state, "", url);
      renderTray();
    };

    const clearCurrent = () => {
      const empty = el("div", "photo-bench-facts");
      empty.setAttribute("data-photo-facts", "");
      setCurrent(null, empty);
    };

    // ---- saving ---------------------------------------------------------
    const mismatchText = (list) => {
      const numbered = list.map((shot) => ({ index: shots.indexOf(shot) + 1, shot }));
      const parts = numbered.map(({ index, shot }) =>
        shotStatus(shot) === "several"
          ? `photo ${index} shows several labels (${shot.label.nrs.join(", ")})`
          : `photo ${index} shows label ${shot.label.nrs[0]}`
      );
      return `${parts.join("; ")}, but this is sample ${current}.`;
    };

    /** Saves `list` (default: every shot) under the current sample. */
    const save = async (list = shots, { quiet = false } = {}) => {
      if (!canEdit || current === null || !list.length || saving) return false;
      if (list.length > maxFiles) {
        toast(`Save at most ${maxFiles} photos at once: drop some first.`, "error");
        return false;
      }
      const doubtful = list.filter((shot) => ["mismatch", "several"].includes(shotStatus(shot)));
      if (doubtful.length) {
        const reason = mismatchText(doubtful);
        const answer = await ask({
          title: `Save as sample ${current}?`,
          text: `${reason[0].toUpperCase()}${reason.slice(1)} Save anyway, or go back and drop or retake ${doubtful.length === 1 ? "it" : "them"}?`,
          actions: [
            { value: "back", label: "Go back", ghost: true, focus: true },
            { value: "save", label: "Save anyway", primary: true },
          ],
        });
        if (answer !== "save") return false;
      }
      saving = true;
      const savedFor = current;
      const clicked = saveButtons.find((button) => button.matches(":focus")) || saveButtons[0];
      clicked?.classList.add("is-saving");
      updateActions();
      try {
        const body = new FormData();
        list.forEach((shot) => body.append("files", shot.blob, shot.name));
        const response = await fetch(`/samples/${encodeURIComponent(savedFor)}/photos`, {
          method: "POST",
          body,
          headers: { Accept: "application/json" },
        });
        let data = {};
        try {
          data = await response.json();
        } catch (_error) {
          data = {};
        }
        if (!response.ok) {
          const reason = data.problem?.advice ? `${data.error} ${data.problem.advice}` : data.error;
          toast(reason || `The photos were not saved (HTTP ${response.status}).`, "error", { duration: 0 });
          return false;
        }
        const names = (data.saved || []).map((photo) => photo.name);
        if (!quiet || names.length) {
          toast(`Saved ${names.length} photo${names.length === 1 ? "" : "s"} of ${savedFor}: ${names.join(", ")}`, "success");
        }
        saving = false;
        dropShots(list.map((shot) => shot.id));
        if (current === savedFor) onFile.load(false);
        return true;
      } catch (_error) {
        toast("webSAMS did not answer; the photos were not saved. Check the connection and try again.", "error", { duration: 0 });
        return false;
      } finally {
        saving = false;
        saveButtons.forEach((button) => button.classList.remove("is-saving"));
        updateActions();
      }
    };

    const saveAndNext = async () => {
      if (!(await save())) return;
      clearCurrent();
      sampleInput.focus();
    };

    saveButtons.forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.photoBenchSave === "next") saveAndNext();
        else save();
      });
    });

    discardButton?.addEventListener("click", async () => {
      if (!shots.length) return;
      const answer = await ask({
        title: `Discard ${shots.length} photo${shots.length === 1 ? "" : "s"}?`,
        text: "They have not been saved.",
        actions: [
          { value: "keep", label: "Keep", ghost: true, focus: true },
          { value: "discard", label: "Discard", primary: true },
        ],
      });
      if (answer === "discard") dropShots(shots.map((shot) => shot.id));
    });

    // Before the bench leaves a sample that still has unsaved photos.
    // → "save" (and saved), "discard", or "keep" (stay).
    const resolveUnsaved = async (nextLabel) => {
      if (!shots.length || current === null) return "none";
      const answer = await ask({
        title: `${shots.length} unsaved photo${shots.length === 1 ? "" : "s"} of sample ${current}`,
        text: `Save ${shots.length === 1 ? "it" : "them"} before ${nextLabel}?`,
        actions: [
          { value: "discard", label: "Discard", ghost: true },
          { value: "keep", label: "Keep editing", focus: true },
          ...(canEdit ? [{ value: "save", label: "Save", primary: true }] : []),
        ],
      });
      if (answer === "save") return (await save()) ? "save" : "keep";
      if (answer === "discard") {
        dropShots(shots.map((shot) => shot.id));
        return "discard";
      }
      return "keep";
    };

    // ---- typed / scanned lookup ----------------------------------------
    const loadTyped = async (raw) => {
      const value = String(raw || "").trim();
      if (value === "") return;
      if (current !== null && value === String(current)) return;
      let facts;
      try {
        facts = await fetchFacts({ sample_nr: value });
      } catch (_error) {
        toast("The sample could not be loaded. Check the connection and try again.", "error");
        return;
      }
      if (facts.nr === null) {
        // Say why inline, keep the bench where it was.
        const reason = facts.fragment.querySelector(".error")?.textContent || `No sample ${value}.`;
        toast(reason, "error");
        sampleInput.value = current === null ? value : String(current);
        sampleInput.select();
        return;
      }
      if ((await resolveUnsaved(`loading sample ${facts.nr}`)) === "keep") {
        sampleInput.value = current === null ? "" : String(current);
        return;
      }
      closeSuggestion();
      setCurrent(facts.nr, facts.fragment);
    };

    if (lookupForm instanceof HTMLFormElement && window.SAMSBench) {
      window.SAMSBench.installLookupForm({
        bench,
        form: lookupForm,
        sampleInput,
        sampleStepAttr: "data-photo-bench-sample-step",
        currentSample: () => (current === null ? "" : String(current)),
        dependents: [],
      });
    }
    lookupForm?.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      // The camera keeps running: switch the sample in place.
      event.preventDefault();
      loadTyped(sampleInput.value);
    });

    // ---- suggestion card ------------------------------------------------
    const closeSuggestion = () => {
      suggestion = null;
      suggestionBox.hidden = true;
      bench.classList.remove("has-suggestion");
      updateActions();
    };

    const openSuggestion = async (shot) => {
      const nr = shot.label.nrs[0];
      suggestion = { nr, shot, known: false };
      suggestionTitle.textContent = `Label reads ${nr}`;
      suggestionFacts.replaceChildren(el("p", "photo-bench-suggestion-loading", "Looking it up…"));
      suggestionNote.hidden = true;
      confirmButton.hidden = false;
      confirmButton.disabled = true;
      suggestionBox.hidden = false;
      bench.classList.add("has-suggestion");
      updateActions();
      let facts = null;
      try {
        facts = await fetchFacts({ label: shot.label.text });
      } catch (_error) {
        facts = null;
      }
      if (!suggestion || suggestion.shot !== shot) return;
      if (!facts) {
        suggestionFacts.replaceChildren(el("p", "error", "The sample could not be looked up. Check the connection."));
        confirmButton.hidden = true;
        rejectButton.focus();
        return;
      }
      suggestionFacts.replaceChildren(facts.fragment.cloneNode(true));
      if (facts.nr === null) {
        suggestionTitle.textContent = `Label reads ${nr}: no such sample`;
        confirmButton.hidden = true;
        suggestionNote.textContent = "Type or scan the sample number instead.";
        suggestionNote.hidden = false;
        rejectButton.focus();
        return;
      }
      suggestion.known = true;
      suggestion.fragment = facts.fragment;
      const others = shots.filter((s) => s !== shot);
      if (current !== null && others.length && canEdit) {
        confirmButton.firstChild.textContent = `Save ${others.length} photo${others.length === 1 ? "" : "s"} of ${current} and switch `;
        suggestionNote.textContent = `The ${others.length === 1 ? "photo" : "photos"} already taken belong${others.length === 1 ? "s" : ""} to sample ${current} and ${others.length === 1 ? "is" : "are"} saved first.`;
        suggestionNote.hidden = false;
      } else if (current !== null && others.length) {
        confirmButton.firstChild.textContent = "Switch ";
        suggestionNote.textContent = `The other photos would move to sample ${nr} as well.`;
        suggestionNote.hidden = false;
      } else {
        confirmButton.firstChild.textContent = "Confirm ";
      }
      confirmButton.disabled = false;
      confirmButton.focus();
    };

    const confirmSuggestion = async () => {
      if (!suggestion || !suggestion.known || confirmButton.disabled) return;
      const { nr, shot, fragment } = suggestion;
      const others = shots.filter((s) => s !== shot);
      confirmButton.disabled = true;
      if (current !== null && others.length && canEdit) {
        // One acknowledgement covers both: file the last sample's photos,
        // then move on to the one under the camera.
        const saved = await save(others);
        if (!saved) {
          confirmButton.disabled = false;
          return;
        }
      }
      closeSuggestion();
      setCurrent(nr, fragment);
    };

    const rejectSuggestion = () => {
      if (!suggestion) return;
      const hadSample = current !== null;
      closeSuggestion();
      renderTray();
      if (!hadSample) {
        sampleInput.focus();
        sampleInput.select();
      }
    };

    confirmButton.addEventListener("click", confirmSuggestion);
    rejectButton.addEventListener("click", rejectSuggestion);

    // ---- shots ------------------------------------------------------------
    const addShot = async (blob, canvas) => {
      shotSerial += 1;
      const shot = {
        id: shotSerial,
        blob,
        url: URL.createObjectURL(blob),
        name: `photo-${shotSerial}.jpg`,
        label: { state: "pending", nrs: [], text: "" },
      };
      shots.push(shot);
      renderTray();
      const texts = await decoder.read(canvas);
      shot.label = interpretCodes(texts);
      if (!shots.includes(shot)) return;
      renderTray();
      if (shot.label.state === "one" && shot.label.nrs[0] !== current && !suggestion) {
        openSuggestion(shot);
      } else if (shot.label.state !== "one" && current === null && !suggestion) {
        toast(
          shot.label.state === "several"
            ? "Several labels are in view: type or scan the sample number."
            : "No label was read: type or scan the sample number.",
          "info"
        );
        sampleInput.focus();
      }
    };

    const capture = async () => {
      if (!track || saving || suggestion || !video.videoWidth) return;
      if (shots.length >= maxFiles) {
        toast(`At most ${maxFiles} photos per save: save these first.`, "error");
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.filter = softFilter();
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      context.filter = "none";
      stage.classList.remove("is-flash");
      void stage.offsetWidth;
      stage.classList.add("is-flash");
      let blob;
      try {
        blob = await canvasToBlob(canvas);
      } catch (_error) {
        toast("The photo could not be taken. Try again.", "error");
        return;
      }
      addShot(blob, canvas);
    };

    captureButton.addEventListener("click", capture);

    fileInput?.addEventListener("change", async () => {
      const files = Array.from(fileInput.files || []);
      fileInput.value = "";
      for (const file of files) {
        if (!/^image\/jpe?g$/i.test(file.type) && !/\.jpe?g$/i.test(file.name)) {
          toast(`${file.name} is not a JPEG picture; only JPEG is saved.`, "error");
          continue;
        }
        if (file.size > maxBytes) {
          toast(`${file.name} is larger than ${bench.dataset.photoBenchMaxMb} MB.`, "error");
          continue;
        }
        if (shots.length >= maxFiles) {
          toast(`At most ${maxFiles} photos per save: save these first.`, "error");
          break;
        }
        // The file goes up as it is; a drawn copy is only for the label.
        let canvas = null;
        try {
          const bitmap = await createImageBitmap(file);
          canvas = document.createElement("canvas");
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
          canvas.getContext("2d", { willReadFrequently: true }).drawImage(bitmap, 0, 0);
          bitmap.close?.();
        } catch (_error) {
          toast(`${file.name} could not be read as a picture.`, "error");
          continue;
        }
        await addShot(file, canvas);
      }
    });

    // ---- live hint --------------------------------------------------------
    let liveBusy = false;
    let liveHideTimer = 0;
    const liveCanvas = document.createElement("canvas");
    const liveTick = async () => {
      if (liveBusy || !track || suggestion || document.hidden || !video.videoWidth) return;
      if (dialog.open) return;
      liveBusy = true;
      try {
        const scale = Math.min(1, LIVE_MAX_WIDTH / video.videoWidth);
        liveCanvas.width = Math.round(video.videoWidth * scale);
        liveCanvas.height = Math.round(video.videoHeight * scale);
        liveCanvas.getContext("2d", { willReadFrequently: true }).drawImage(video, 0, 0, liveCanvas.width, liveCanvas.height);
        const texts = await decoder.read(liveCanvas, { quick: true });
        const label = interpretCodes(texts || []);
        if (label.state === "none") return;
        const text =
          label.state === "several"
            ? `Labels ${label.nrs.join(", ")} in view`
            : label.nrs[0] === current
              ? `✓ Label ${label.nrs[0]} in view`
              : `Label ${label.nrs[0]} in view`;
        liveHint.textContent = text;
        liveHint.classList.toggle("is-match", label.state === "one" && label.nrs[0] === current);
        liveHint.hidden = false;
        window.clearTimeout(liveHideTimer);
        liveHideTimer = window.setTimeout(() => {
          liveHint.hidden = true;
        }, LIVE_HINT_HOLD_MS);
      } finally {
        liveBusy = false;
      }
    };

    // ---- camera ------------------------------------------------------------
    const showCameraNote = (title, lines = []) => {
      const nodes = [el("p", "photo-bench-camera-title", title), ...lines.map((line) => (line instanceof Node ? line : el("p", "", line)))];
      cameraNote.replaceChildren(...nodes);
      cameraNote.hidden = false;
      stage.classList.add("is-off");
    };

    const insecureNote = () => {
      const origin = window.location.origin;
      const steps = el("ol", "photo-bench-steps");
      const step1 = el("li");
      step1.append("In Chrome or Edge on this PC, open ", el("code", "", "chrome://flags/#unsafely-treat-insecure-origin-as-secure"), " (Edge: ", el("code", "", "edge://flags/…"), ").");
      const step2 = el("li");
      step2.append("Add ", el("code", "", origin), ", set it to Enabled and relaunch the browser.");
      steps.append(step1, step2);
      showCameraNote("The camera is blocked on this page", [
        `Browsers only allow the camera on https:// pages or on localhost, and this page is ${origin}.`,
        steps,
        "Once webSAMS runs behind https this is no longer needed. Until then, Add file… still works.",
      ]);
    };

    const softFilter = () => {
      const brightness = Number(settings.soft?.softBrightness ?? 100);
      const contrast = Number(settings.soft?.softContrast ?? 100);
      return brightness === 100 && contrast === 100 ? "none" : `brightness(${brightness}%) contrast(${contrast}%)`;
    };

    const applySoftPreview = () => {
      video.style.filter = softFilter() === "none" ? "" : softFilter();
    };

    const deviceSettings = () => {
      const id = settings.deviceId || "default";
      settings.devices = settings.devices || {};
      settings.devices[id] = settings.devices[id] || { values: {}, modes: {} };
      return settings.devices[id];
    };

    const applyConstraint = async (constraint) => {
      if (!track) return;
      try {
        await track.applyConstraints({ advanced: [constraint] });
      } catch (error) {
        console.warn("Photo bench: camera refused", constraint, error);
      }
    };

    const formatValue = (value, step) => {
      const decimals = step && step < 1 ? Math.min(3, String(step).split(".")[1]?.length || 2) : 0;
      return Number(value).toFixed(decimals);
    };

    const sliderRow = ({ id, label, min, max, step, value, unit = "", onInput }) => {
      const row = el("div", "photo-bench-control");
      const head = el("div", "photo-bench-control-head");
      const name = el("label", "", label);
      name.htmlFor = id;
      const shown = el("output", "photo-bench-control-value", `${formatValue(value, step)}${unit}`);
      head.append(name, shown);
      const input = el("input");
      input.type = "range";
      input.id = id;
      input.min = String(min);
      input.max = String(max);
      input.step = String(step || 1);
      input.value = String(value);
      input.addEventListener("input", () => {
        shown.textContent = `${formatValue(input.value, step)}${unit}`;
        onInput(Number(input.value));
      });
      row.append(head, input);
      return { row, input, shown };
    };

    const buildControls = () => {
      controlGrid.querySelectorAll(".photo-bench-control:not(.is-device)").forEach((node) => node.remove());
      if (!track || typeof track.getCapabilities !== "function") {
        controlsNote.textContent = "This browser does not offer camera controls.";
        controlsNote.hidden = false;
        buildSoftControls();
        return;
      }
      const caps = track.getCapabilities();
      const live = track.getSettings();
      const saved = deviceSettings();
      const rows = [];
      const modeBoxes = {};

      Object.entries(MODE_LABELS).forEach(([modeKey, modeLabel]) => {
        const modes = caps[modeKey] || [];
        if (!(modes.includes("manual") && (modes.includes("continuous") || modes.includes("single-shot")))) return;
        const auto = modes.includes("continuous") ? "continuous" : "single-shot";
        const row = el("label", "photo-bench-control is-switch");
        const box = el("input");
        box.type = "checkbox";
        box.checked = (saved.modes[modeKey] || live[modeKey] || auto) !== "manual";
        box.addEventListener("change", () => {
          saved.modes[modeKey] = box.checked ? auto : "manual";
          saveSettings(settings);
          applyConstraint({ [modeKey]: saved.modes[modeKey] });
        });
        row.append(box, el("span", "", modeLabel));
        modeBoxes[modeKey] = { box, auto };
        rows.push(row);
      });

      CONTROLS.forEach((control) => {
        const range = caps[control.key];
        if (!range || typeof range.min !== "number" || typeof range.max !== "number" || range.max <= range.min) return;
        const value = saved.values[control.key] ?? live[control.key] ?? range.min;
        const { row } = sliderRow({
          id: `photo-bench-${control.key}`,
          label: control.label,
          min: range.min,
          max: range.max,
          step: range.step || 1,
          value,
          onInput: (next) => {
            saved.values[control.key] = next;
            const constraint = { [control.key]: next };
            // A manual value only takes while its auto mode is off.
            const mode = control.mode && modeBoxes[control.mode];
            if (mode && mode.box.checked) {
              mode.box.checked = false;
              saved.modes[control.mode] = "manual";
            }
            if (mode) constraint[control.mode] = "manual";
            saveSettings(settings);
            applyConstraint(constraint);
          },
        });
        rows.push(row);
      });

      controlGrid.append(...rows);
      const hasBrightness = Boolean(caps.brightness && caps.brightness.max > caps.brightness.min);
      controlsNote.hidden = rows.length > 0;
      controlsNote.textContent = "This camera offers no adjustable settings; brightness and contrast are adjusted in the picture instead.";
      if (!hasBrightness) buildSoftControls();
    };

    const buildSoftControls = () => {
      settings.soft = settings.soft || {};
      SOFT_CONTROLS.forEach((control) => {
        const { row } = sliderRow({
          id: `photo-bench-${control.key}`,
          label: `${control.label} (picture)`,
          min: control.min,
          max: control.max,
          step: control.step,
          unit: control.unit,
          value: settings.soft[control.key] ?? 100,
          onInput: (next) => {
            settings.soft[control.key] = next;
            saveSettings(settings);
            applySoftPreview();
          },
        });
        row.title = "The camera has no setting for this: it is applied to the picture.";
        controlGrid.appendChild(row);
      });
      applySoftPreview();
    };

    // Saved values for this camera, applied once the stream runs.
    const applySaved = async () => {
      const saved = deviceSettings();
      const constraint = {};
      Object.entries(saved.modes || {}).forEach(([key, value]) => {
        constraint[key] = value;
      });
      Object.entries(saved.values || {}).forEach(([key, value]) => {
        constraint[key] = value;
      });
      if (Object.keys(constraint).length) await applyConstraint(constraint);
      applySoftPreview();
    };

    const fillDevices = async () => {
      try {
        const devices = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === "videoinput");
        const activeId = track?.getSettings().deviceId || "";
        deviceSelect.replaceChildren(
          ...devices.map((device, index) => {
            const option = el("option", "", device.label || `Camera ${index + 1}`);
            option.value = device.deviceId;
            option.selected = device.deviceId === activeId;
            return option;
          })
        );
        deviceRow.hidden = devices.length < 2;
      } catch (_error) {
        deviceRow.hidden = true;
      }
    };

    const stopCamera = () => {
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      track = null;
    };

    const startCamera = async () => {
      stopCamera();
      updateActions();
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        insecureNote();
        return;
      }
      showCameraNote("Starting the camera…");
      const videoConstraints = {
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      };
      if (settings.deviceId) videoConstraints.deviceId = { exact: settings.deviceId };
      // The browser's permission prompt may be waiting for an answer.
      const promptHint = window.setTimeout(() => {
        showCameraNote("Waiting for the camera…", [
          "If the browser asks, allow the camera for this page (the prompt sits next to the address bar).",
        ]);
      }, 4000);
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
        window.clearTimeout(promptHint);
      } catch (error) {
        window.clearTimeout(promptHint);
        if (settings.deviceId && (error.name === "OverconstrainedError" || error.name === "NotFoundError")) {
          // The remembered camera is gone: fall back to any camera.
          delete settings.deviceId;
          saveSettings(settings);
          return startCamera();
        }
        const reasons = {
          NotAllowedError: [
            "Camera access was refused",
            "Allow the camera for this page: click the camera icon in the address bar (or the site settings), then reload.",
          ],
          NotFoundError: ["No camera was found", "Plug the webcam in, then reload the page."],
          NotReadableError: [
            "The camera is in use",
            "Another program (or another browser tab) is using it. Close that, then reload the page.",
          ],
        };
        const [title, advice] = reasons[error.name] || ["The camera could not be started", error.message || String(error)];
        showCameraNote(title, [advice]);
        return;
      }
      track = stream.getVideoTracks()[0] || null;
      video.srcObject = stream;
      try {
        await video.play();
      } catch (_error) {
        // Autoplay of a muted stream is allowed; ignore odd refusals.
      }
      cameraNote.hidden = true;
      stage.classList.remove("is-off");
      trackDefaults = track?.getSettings() || {};
      await applySaved();
      buildControls();
      fillDevices();
      updateActions();
    };

    video.addEventListener("loadedmetadata", () => {
      resolutionLabel.textContent = video.videoWidth ? `${video.videoWidth} × ${video.videoHeight}` : "";
    });

    deviceSelect?.addEventListener("change", () => {
      settings.deviceId = deviceSelect.value || undefined;
      saveSettings(settings);
      startCamera();
    });

    resetButton?.addEventListener("click", async () => {
      const saved = deviceSettings();
      saved.values = {};
      saved.modes = {};
      settings.soft = {};
      saveSettings(settings);
      // Back to what the camera reported when the stream started.
      const restore = {};
      ["exposureMode", "whiteBalanceMode", "focusMode", ...CONTROLS.map((c) => c.key)].forEach((key) => {
        if (trackDefaults[key] !== undefined) restore[key] = trackDefaults[key];
      });
      if (Object.keys(restore).length) await applyConstraint(restore);
      applySoftPreview();
      buildControls();
    });

    // ---- keyboard ----------------------------------------------------------
    // Capture-phase so a suggestion's Enter / Esc wins over anything below;
    // the photo viewer and the dialog handle their own keys.
    document.addEventListener(
      "keydown",
      (event) => {
        if (dialog.open || document.querySelector("dialog.photo-viewer[open]")) return;
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
          event.preventDefault();
          if (!saveButtons[0]?.disabled) save();
          return;
        }
        if (suggestion) {
          if (event.key === "Escape") {
            event.preventDefault();
            rejectSuggestion();
          } else if (event.key === "Enter" && !isTypingTarget(event.target)) {
            event.preventDefault();
            if (!confirmButton.hidden) confirmSuggestion();
            else rejectSuggestion();
          }
          return;
        }
        if (event.key === " " && !isTypingTarget(event.target) && !event.repeat) {
          event.preventDefault();
          capture();
        }
      },
      true
    );

    // Space on a focused button would also "click" it on keyup.
    document.addEventListener(
      "keyup",
      (event) => {
        if (event.key === " " && !suggestion && !dialog.open && event.target instanceof HTMLButtonElement && bench.contains(event.target)) {
          event.preventDefault();
        }
      },
      true
    );

    window.addEventListener("beforeunload", (event) => {
      if (!shots.length) return;
      event.preventDefault();
      event.returnValue = "";
    });
    window.addEventListener("pagehide", stopCamera);

    // ---- start -------------------------------------------------------------
    renderTray();
    decoder.init();
    startCamera();
    window.setInterval(liveTick, LIVE_INTERVAL_MS);
    if (current === null) sampleInput.focus();
  };

  // Exposed for tests in the browser console.
  window.SAMSPhotoBench = { labelSampleNr };
})();
