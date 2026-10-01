// Sample photos on the sample detail page: a thumbnail strip that is loaded
// after the page has rendered, plus a full-window viewer with zoom and pan.
//
// The photos sit on a network share. Listing it can take seconds (or fail),
// so the strip is fetched separately from `/api/samples/<nr>/photos`, whose
// `state` says what happened: ok | scanning | not_configured | unavailable.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});
  const SVG_NS = "http://www.w3.org/2000/svg";

  const ICON_PATHS = {
    download: "M12 4v11m0 0l-4-4m4 4l4-4M5 20h14",
    zoomIn: "M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14zm9 16l-4-4M11 8v6M8 11h6",
    zoomOut: "M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14zm9 16l-4-4M8 11h6",
    fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
    close: "M6 6l12 12M18 6L6 18",
    previous: "M15 5l-7 7l7 7",
    next: "M9 5l7 7l-7 7",
  };

  const icon = (name) => {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", ICON_PATHS[name]);
    svg.appendChild(path);
    return svg;
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const iconButton = (name, label, className = "photo-icon-button") => {
    const button = el("button", className);
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(icon(name));
    return button;
  };

  // A download leaves the page where it is, but some browsers still fire
  // `beforeunload` for it, which starts the page-progress sweep — and with
  // no new page to replace it, the bar would run forever.
  const clearPageProgress = () => {
    window.setTimeout(() => document.getElementById("sams-page-progress")?.remove(), 600);
  };

  // --- Viewer ---------------------------------------------------------------
  //
  // One <dialog> for the page. The image is drawn at its natural pixel size
  // and positioned with `translate(x, y) scale(s)` (origin top-left), so
  // `scale` reads directly as "percent of actual size" and zooming around
  // the cursor is plain arithmetic.
  const createViewer = () => {
    const dialog = el("dialog", "photo-viewer");
    dialog.setAttribute("aria-label", "Sample photo viewer");

    const bar = el("header", "photo-viewer-bar");
    const title = el("div", "photo-viewer-title");
    const nameLabel = el("strong", "photo-viewer-name");
    const counter = el("span", "photo-viewer-counter");
    title.append(nameLabel, counter);

    const tools = el("div", "photo-viewer-tools");
    const zoomOutButton = iconButton("zoomOut", "Zoom out (−)", "photo-viewer-button");
    const zoomLevel = el("button", "photo-viewer-button photo-viewer-level", "100%");
    zoomLevel.type = "button";
    zoomLevel.title = "Actual size (1)";
    const zoomInButton = iconButton("zoomIn", "Zoom in (+)", "photo-viewer-button");
    const fitButton = iconButton("fit", "Fit to window (0)", "photo-viewer-button");
    const downloadLink = el("a", "photo-viewer-button sample-photo-download");
    downloadLink.title = "Download this photo";
    downloadLink.setAttribute("aria-label", "Download this photo");
    downloadLink.setAttribute("download", "");
    downloadLink.appendChild(icon("download"));
    downloadLink.addEventListener("click", clearPageProgress);
    const closeButton = iconButton("close", "Close (Esc)", "photo-viewer-button");
    tools.append(zoomOutButton, zoomLevel, zoomInButton, fitButton, downloadLink, closeButton);
    bar.append(title, tools);

    const stage = el("div", "photo-viewer-stage");
    const image = el("img", "photo-viewer-image");
    image.alt = "";
    image.draggable = false;
    const note = el("p", "photo-viewer-note", "Loading…");
    const previousButton = iconButton("previous", "Previous photo (←)", "photo-viewer-nav is-previous");
    const nextButton = iconButton("next", "Next photo (→)", "photo-viewer-nav is-next");
    stage.append(image, note, previousButton, nextButton);

    dialog.append(bar, stage);
    document.body.appendChild(dialog);

    let photos = [];
    let current = 0;
    let scale = 1;
    let x = 0;
    let y = 0;
    let fitScale = 1;
    let loaded = false;

    const stageSize = () => ({ width: stage.clientWidth, height: stage.clientHeight });
    const maxScale = () => Math.max(fitScale * 8, 2);
    const isFitted = () => Math.abs(scale - fitScale) < 0.0005;

    const apply = () => {
      const { width, height } = stageSize();
      const drawnWidth = image.naturalWidth * scale;
      const drawnHeight = image.naturalHeight * scale;
      // Smaller than the stage: keep it centred. Larger: never let an edge
      // be dragged inside the stage, so the photo cannot be lost off-screen.
      x = drawnWidth <= width ? (width - drawnWidth) / 2 : Math.min(0, Math.max(width - drawnWidth, x));
      y = drawnHeight <= height ? (height - drawnHeight) / 2 : Math.min(0, Math.max(height - drawnHeight, y));
      image.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
      zoomLevel.textContent = `${Math.round(scale * 100)}%`;
      zoomOutButton.disabled = scale <= fitScale + 0.0005;
      zoomInButton.disabled = scale >= maxScale() - 0.0005;
      stage.classList.toggle("is-pannable", drawnWidth > width + 1 || drawnHeight > height + 1);
    };

    const measureFit = () => {
      const { width, height } = stageSize();
      if (!image.naturalWidth || !image.naturalHeight) return 1;
      // Never enlarge a small photo just to fill the window.
      return Math.min(width / image.naturalWidth, height / image.naturalHeight, 1);
    };

    const fit = () => {
      fitScale = measureFit();
      scale = fitScale;
      apply();
    };

    // Zoom to `next`, keeping the image point under (originX, originY) still.
    const zoomTo = (next, originX, originY) => {
      if (!loaded) return;
      const { width, height } = stageSize();
      const cx = originX ?? width / 2;
      const cy = originY ?? height / 2;
      const clamped = Math.min(maxScale(), Math.max(fitScale, next));
      const ratio = clamped / scale;
      x = cx - (cx - x) * ratio;
      y = cy - (cy - y) * ratio;
      scale = clamped;
      apply();
    };

    const show = (index) => {
      current = (index + photos.length) % photos.length;
      const photo = photos[current];
      loaded = false;
      image.hidden = true;
      note.hidden = false;
      note.textContent = "Loading…";
      nameLabel.textContent = photo.name;
      counter.textContent = photos.length > 1 ? `${current + 1} / ${photos.length}` : "";
      downloadLink.href = photo.download_url;
      const single = photos.length < 2;
      previousButton.hidden = single;
      nextButton.hidden = single;
      image.src = photo.url;
    };

    image.addEventListener("load", () => {
      loaded = true;
      note.hidden = true;
      image.hidden = false;
      fit();
    });
    image.addEventListener("error", () => {
      note.hidden = false;
      note.textContent = "This photo could not be loaded.";
    });

    const stagePoint = (event) => {
      const rect = stage.getBoundingClientRect();
      return { px: event.clientX - rect.left, py: event.clientY - rect.top };
    };

    stage.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        // A trackpad pinch arrives as ctrl+wheel with small deltas; a mouse
        // wheel as ~100 per notch (or a few "lines" in Firefox).
        const unit = event.deltaMode === 1 ? 16 : 1;
        const speed = event.ctrlKey ? 0.01 : 0.0015;
        const { px, py } = stagePoint(event);
        zoomTo(scale * Math.exp(-event.deltaY * unit * speed), px, py);
      },
      { passive: false },
    );

    // Drag to pan; two pointers pinch-zoom around their midpoint.
    const pointers = new Map();
    let pinchDistance = 0;

    const pinchState = () => {
      const [a, b] = Array.from(pointers.values());
      return {
        distance: Math.hypot(a.px - b.px, a.py - b.py),
        midX: (a.px + b.px) / 2,
        midY: (a.py + b.py) / 2,
      };
    };

    stage.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button") || event.button !== 0) return;
      stage.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, stagePoint(event));
      if (pointers.size === 2) pinchDistance = pinchState().distance;
      stage.classList.add("is-dragging");
    });

    stage.addEventListener("pointermove", (event) => {
      const previous = pointers.get(event.pointerId);
      if (!previous) return;
      const point = stagePoint(event);
      pointers.set(event.pointerId, point);
      if (pointers.size === 1) {
        x += point.px - previous.px;
        y += point.py - previous.py;
        apply();
      } else if (pointers.size === 2) {
        const { distance, midX, midY } = pinchState();
        if (pinchDistance > 0) zoomTo(scale * (distance / pinchDistance), midX, midY);
        pinchDistance = distance;
      }
    });

    const releasePointer = (event) => {
      pointers.delete(event.pointerId);
      pinchDistance = 0;
      if (!pointers.size) stage.classList.remove("is-dragging");
    };
    stage.addEventListener("pointerup", releasePointer);
    stage.addEventListener("pointercancel", releasePointer);

    stage.addEventListener("dblclick", (event) => {
      if (event.target.closest("button")) return;
      const { px, py } = stagePoint(event);
      if (isFitted()) {
        // Already at actual size when fitted (small photo): go to 2x instead.
        zoomTo(fitScale >= 1 ? 2 : 1, px, py);
      } else {
        fit();
      }
    });

    zoomInButton.addEventListener("click", () => zoomTo(scale * 1.4));
    zoomOutButton.addEventListener("click", () => zoomTo(scale / 1.4));
    zoomLevel.addEventListener("click", () => zoomTo(1));
    fitButton.addEventListener("click", fit);
    closeButton.addEventListener("click", () => dialog.close());
    previousButton.addEventListener("click", () => show(current - 1));
    nextButton.addEventListener("click", () => show(current + 1));

    // Captured on `document`, not on the dialog: the record shortcuts
    // (e, [, ], j, k, Esc = cancel edit ...) listen there too and none of
    // them may fire while the viewer is on top — wherever the focus sits.
    document.addEventListener("keydown", (event) => {
      if (!dialog.open) return;
      event.stopPropagation();
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const actions = {
        Escape: () => dialog.close(),
        ArrowLeft: () => photos.length > 1 && show(current - 1),
        ArrowRight: () => photos.length > 1 && show(current + 1),
        "+": () => zoomTo(scale * 1.4),
        "=": () => zoomTo(scale * 1.4),
        "-": () => zoomTo(scale / 1.4),
        _: () => zoomTo(scale / 1.4),
        0: fit,
        1: () => zoomTo(1),
      };
      const action = actions[event.key];
      if (!action) return;
      event.preventDefault();
      action();
    }, true);

    window.addEventListener("resize", () => {
      if (!dialog.open || !loaded) return;
      const wasFitted = isFitted();
      fitScale = measureFit();
      if (wasFitted || scale < fitScale) scale = fitScale;
      apply();
    });

    dialog.addEventListener("close", () => {
      // Drop the decoded bitmap; a camera JPEG is tens of MB in memory.
      image.removeAttribute("src");
      pointers.clear();
    });

    return {
      open(list, index) {
        photos = list;
        if (!photos.length) return;
        if (!dialog.open) dialog.showModal();
        show(index);
      },
    };
  };

  // --- Thumbnail strip --------------------------------------------------------

  const SCAN_POLL_MS = 2000;
  const SCAN_POLL_LIMIT = 40;

  installers.installSamplePhotos = () => {
    const root = document.querySelector("[data-sample-photos]");
    if (!root) return;
    const body = root.querySelector("[data-photos-body]");
    const count = root.querySelector("[data-photos-count]");
    const refreshButton = root.querySelector("[data-photos-refresh]");
    const url = root.dataset.photosUrl;
    const sampleNr = root.dataset.sampleNr;
    let viewer = null;
    let pollTimer = 0;
    let polls = 0;

    const note = (text, kind) => {
      const paragraph = el("p", "sample-photos-note", text);
      if (kind) paragraph.classList.add(`is-${kind}`);
      return paragraph;
    };

    const setCount = (n) => {
      count.hidden = !n;
      count.textContent = n ? String(n) : "";
    };

    const renderPhotos = (photos) => {
      const viewable = photos.filter((photo) => photo.viewable);
      const list = el("ul", "sample-photo-grid");
      photos.forEach((photo) => {
        const item = el("li", "sample-photo");
        if (photo.viewable) {
          const thumb = el("button", "sample-photo-thumb");
          thumb.type = "button";
          thumb.title = `View ${photo.name}`;
          thumb.setAttribute("aria-label", `View ${photo.name}`);
          const img = el("img");
          img.loading = "lazy";
          img.decoding = "async";
          img.alt = photo.name;
          img.src = photo.url;
          thumb.appendChild(img);
          thumb.addEventListener("click", () => {
            viewer = viewer || createViewer();
            viewer.open(viewable, viewable.indexOf(photo));
          });
          item.appendChild(thumb);
        } else {
          // TIFF / HEIC: browsers cannot draw them, so offer the file only.
          const extension = photo.name.split(".").pop().toUpperCase();
          const tile = el("div", "sample-photo-thumb is-file", extension);
          tile.title = "This format cannot be previewed in the browser — download it to view.";
          item.appendChild(tile);
        }
        if (photo.group) {
          const badge = el("span", "sample-photo-badge", "Group photo");
          badge.title = "This photo shows several samples; it is listed on each of them.";
          item.appendChild(badge);
        }
        const caption = el("div", "sample-photo-caption");
        const text = el("div", "sample-photo-text");
        const name = el("span", "sample-photo-name", photo.name);
        // Full path below the photo folder: says which sub-folder it is in.
        name.title = photo.path;
        text.append(name, el("span", "sample-photo-meta", `${photo.size_label} · ${photo.modified}`));
        const download = el("a", "photo-icon-button sample-photo-download");
        download.href = photo.download_url;
        download.setAttribute("download", photo.name);
        download.title = `Download ${photo.name}`;
        download.setAttribute("aria-label", `Download ${photo.name}`);
        download.appendChild(icon("download"));
        download.addEventListener("click", clearPageProgress);
        caption.append(text, download);
        item.appendChild(caption);
        list.appendChild(item);
      });
      return list;
    };

    // Why the photos cannot be shown: what happened, what to do, and the
    // facts an administrator needs (folder, account, the system's message).
    const renderProblem = (problem) => {
      const box = el("div", "sample-photos-problem");
      box.setAttribute("role", "status");
      const title = el("p", "sample-photos-problem-title");
      title.append(el("strong", "", "Photos unavailable: "), `${problem.title}.`);
      box.appendChild(title);
      if (problem.advice) box.appendChild(el("p", "sample-photos-problem-advice", problem.advice));
      const facts = [
        ["Folder", problem.folder],
        ["webSAMS runs as", problem.account],
        ["System message", problem.os_error],
      ].filter(([, value]) => value);
      if (facts.length) {
        const list = el("dl", "sample-photos-problem-facts");
        facts.forEach(([label, value]) => list.append(el("dt", "", label), el("dd", "", value)));
        box.appendChild(list);
      }
      const actions = el("div", "sample-photos-problem-actions");
      const retry = el("button", "sample-photos-retry", "Try again");
      retry.type = "button";
      retry.addEventListener("click", () => {
        retry.disabled = true;
        polls = 0;
        load(true);
      });
      const check = el("a", "table-link", "Folder check");
      check.href = "/setup?section=sample_photos";
      check.title = "Setup → Sample Photos";
      actions.append(retry, check);
      box.appendChild(actions);
      return box;
    };

    const render = (data) => {
      const photos = data.photos || [];
      setCount(data.state === "ok" ? photos.length : 0);
      // Nothing to rescan until a folder is set.
      refreshButton.hidden = data.state === "not_configured";
      if (data.state === "scanning") {
        body.replaceChildren(note("Reading the photo folder…"));
        return;
      }
      if (data.state === "not_configured") {
        const paragraph = note("No photo folder is configured yet. Set it under ");
        const link = el("a", "table-link", "Setup → Sample Photos");
        link.href = "/setup?section=sample_photos";
        paragraph.append(link, ".");
        body.replaceChildren(paragraph);
        return;
      }
      if (data.state !== "ok") {
        body.replaceChildren(renderProblem(data.problem || {
          title: data.message || "The photo folder is not available",
          advice: "",
        }));
        return;
      }
      const nodes = [];
      if (data.message) nodes.push(note(data.message));
      if (photos.length) {
        nodes.push(renderPhotos(photos));
      } else {
        const paragraph = note("No photos for this sample yet. Image files whose name starts with ");
        paragraph.append(el("strong", "", sampleNr), " appear here.");
        nodes.push(paragraph);
      }
      body.replaceChildren(...nodes);
    };

    const load = async (refresh) => {
      window.clearTimeout(pollTimer);
      refreshButton.disabled = true;
      refreshButton.classList.add("is-busy");
      let data;
      try {
        const response = await fetch(refresh ? `${url}?refresh=true` : url, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
      } catch (_error) {
        data = {
          state: "unavailable",
          problem: {
            title: "The photo list could not be loaded",
            advice: "webSAMS did not answer. Check the connection to the webSAMS server and try again.",
          },
        };
      }
      render(data);
      // The first listing of a big share outlasts one request; ask again.
      if (data.state === "scanning" && polls < SCAN_POLL_LIMIT) {
        polls += 1;
        pollTimer = window.setTimeout(() => load(false), SCAN_POLL_MS);
        return;
      }
      polls = 0;
      refreshButton.disabled = false;
      refreshButton.classList.remove("is-busy");
    };

    refreshButton.addEventListener("click", () => {
      polls = 0;
      load(true);
    });
    load(false);
  };
})();
