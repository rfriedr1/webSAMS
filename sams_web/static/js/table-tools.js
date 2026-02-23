(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  const compareCellValues = (left, right) => {
    const leftTrimmed = left.trim();
    const rightTrimmed = right.trim();
    const leftNumeric = Number(leftTrimmed.replace(/,/g, ""));
    const rightNumeric = Number(rightTrimmed.replace(/,/g, ""));
    const leftIsNumeric = leftTrimmed !== "" && Number.isFinite(leftNumeric);
    const rightIsNumeric = rightTrimmed !== "" && Number.isFinite(rightNumeric);
    if (leftIsNumeric && rightIsNumeric) {
      return leftNumeric - rightNumeric;
    }
    return leftTrimmed.localeCompare(rightTrimmed, undefined, {
      numeric: true,
      sensitivity: "base",
    });
  };

  const extractCellValue = (cell) => {
    const directText = (cell.textContent || "").trim();
    const field = cell.querySelector("input, select, textarea");
    if (!field) {
      return directText;
    }
    const fieldValue = "value" in field ? String(field.value || "").trim() : "";
    if (fieldValue !== "") {
      return fieldValue;
    }
    return directText;
  };

  const normalizeWhitespace = (value) => String(value || "").replace(/\s+/g, " ").trim();

  const normalizeHeaderLabel = (value) => normalizeWhitespace(value).toLowerCase();

  const isCompactIdentifierColumn = (headerText) => {
    const normalized = normalizeHeaderLabel(headerText);
    return [
      "sample_nr",
      "prep_nr",
      "target_nr",
      "sample #",
      "prep #",
      "target #",
      "sample#",
      "prep#",
      "target#",
      "sample nr",
      "prep nr",
      "target nr",
    ].includes(normalized);
  };

  const slugifyFilePart = (value, fallback = "table_export") => {
    const slug = normalizeWhitespace(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    return slug || fallback;
  };

  const formatFileTimestamp = () => {
    const now = new Date();
    const pad = (number) => String(number).padStart(2, "0");
    return [
      now.getFullYear(),
      pad(now.getMonth() + 1),
      pad(now.getDate()),
      "_",
      pad(now.getHours()),
      pad(now.getMinutes()),
      pad(now.getSeconds()),
    ].join("");
  };

  const escapeXml = (value) => String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");

  const sanitizeSheetName = (name) => {
    const cleaned = normalizeWhitespace(name).replace(/[\\/*?:[\]]/g, " ").slice(0, 31).trim();
    return cleaned || "Sheet1";
  };

  const isNumericCellValue = (value) => {
    const normalized = String(value || "").replace(/,/g, "").trim();
    if (normalized === "") {
      return false;
    }
    return /^[-+]?(\d+(\.\d+)?|\.\d+)([eE][-+]?\d+)?$/.test(normalized);
  };

  const buildSpreadsheetXml = (sheetName, headers, rows) => {
    const columnCount = Math.max(
      headers.length,
      ...rows.map((row) => row.length),
      1,
    );
    const renderCell = (value, allowNumber = false) => {
      const text = String(value ?? "").trim();
      if (!text) {
        return "<Cell><Data ss:Type=\"String\"></Data></Cell>";
      }
      if (allowNumber && isNumericCellValue(text)) {
        return `<Cell><Data ss:Type="Number">${escapeXml(text.replace(/,/g, ""))}</Data></Cell>`;
      }
      return `<Cell><Data ss:Type="String">${escapeXml(text)}</Data></Cell>`;
    };

    const headerRow = `<Row>${Array.from({ length: columnCount }, (_unused, index) => renderCell(headers[index] || "")).join("")}</Row>`;
    const dataRows = rows
      .map((row) => `<Row>${Array.from({ length: columnCount }, (_unused, index) => renderCell(row[index] || "", true)).join("")}</Row>`)
      .join("");

    return `<?xml version="1.0" encoding="UTF-8"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Worksheet ss:Name="${escapeXml(sheetName)}">
  <Table>
   ${headerRow}
   ${dataRows}
  </Table>
 </Worksheet>
</Workbook>`;
  };

  const triggerFileDownload = (filename, content, mimeType) => {
    const blob = new Blob([content], { type: mimeType });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 0);
  };

  const inferTableTitle = (container, table) => {
    const explicitName = normalizeWhitespace(container.dataset.tableDownloadName || table.dataset.tableDownloadName || "");
    if (explicitName) {
      return explicitName;
    }

    const caption = table.querySelector("caption");
    if (caption && normalizeWhitespace(caption.textContent)) {
      return normalizeWhitespace(caption.textContent);
    }

    const summaryTitle = container.querySelector(".table-summary-title");
    if (summaryTitle && normalizeWhitespace(summaryTitle.textContent)) {
      return normalizeWhitespace(summaryTitle.textContent);
    }

    const heading = container.querySelector("h2, h3, h4, h5");
    if (heading && normalizeWhitespace(heading.textContent)) {
      return normalizeWhitespace(heading.textContent);
    }

    if (container.id) {
      return container.id;
    }
    if (table.id) {
      return table.id;
    }
    return "table";
  };

  const resolveDownloadScope = (container) => {
    const scope = String(container.dataset.tableDownloadScope || "visible").toLowerCase();
    if (scope === "all") {
      return "all";
    }
    return "visible";
  };

  const ensureToolsRow = (container, table) => {
    let tools = container.querySelector(".table-tools");
    if (tools) {
      return tools;
    }
    tools = document.createElement("div");
    tools.className = "table-tools";
    const wrap = table.closest(".table-wrap") || table;
    if (wrap.parentElement === container) {
      container.insertBefore(tools, wrap);
    } else {
      container.prepend(tools);
    }
    return tools;
  };

  const createDownloadButton = (container) => {
    const downloadText = container.dataset.tableDownloadLabel || "Download table as Excel";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "table-tool-icon table-tool-download";
    button.setAttribute("title", downloadText);
    button.setAttribute("aria-label", downloadText);
    button.setAttribute("data-table-download", "");

    const svgNs = "http://www.w3.org/2000/svg";
    const icon = document.createElementNS(svgNs, "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(svgNs, "path");
    path.setAttribute("d", "M12 3v10m0 0l4-4m-4 4-4-4M5 17h14v4H5z");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    icon.append(path);
    button.append(icon);

    const srText = document.createElement("span");
    srText.className = "sr-only";
    srText.textContent = downloadText;
    button.append(srText);

    return button;
  };

  const ensureDownloadButton = (container, table) => {
    const existing = container.querySelector("[data-table-download]");
    if (existing) {
      return existing;
    }
    const tools = ensureToolsRow(container, table);
    const button = createDownloadButton(container);
    const status = tools.querySelector(".table-tool-status");
    if (status) {
      tools.insertBefore(button, status);
    } else {
      tools.append(button);
    }
    return button;
  };

  const createTableTools = (container, table, headers, rowCount) => {
    const labelText = container.dataset.tableSearchLabel || "Search";
    const placeholder = container.dataset.tableSearchPlaceholder || "Type to filter rows";
    const columnText = container.dataset.tableColumnLabel || "Column";
    const allColumnsText = container.dataset.tableAllColumnsLabel || "All Columns";
    const clearText = container.dataset.tableClearLabel || "Clear";

    const tools = ensureToolsRow(container, table);

    let searchInput = container.querySelector("[data-table-search]");
    if (!searchInput) {
      const searchLabel = document.createElement("label");
      searchLabel.className = "table-tool-field";
      searchLabel.append(document.createTextNode(labelText));
      searchInput = document.createElement("input");
      searchInput.type = "search";
      searchInput.placeholder = placeholder;
      searchInput.setAttribute("data-table-search", "");
      searchLabel.append(searchInput);
      tools.append(searchLabel);
    } else if (!searchInput.placeholder) {
      searchInput.placeholder = placeholder;
    }

    let columnSelect = container.querySelector("[data-table-column]");
    if (!columnSelect) {
      const columnLabel = document.createElement("label");
      columnLabel.className = "table-tool-field";
      columnLabel.append(document.createTextNode(columnText));
      columnSelect = document.createElement("select");
      columnSelect.setAttribute("data-table-column", "");
      columnLabel.append(columnSelect);
      tools.append(columnLabel);
    }
    columnSelect.textContent = "";
    const allOption = document.createElement("option");
    allOption.value = "-1";
    allOption.textContent = allColumnsText;
    columnSelect.append(allOption);
    headers.forEach((header, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = header.textContent?.trim() || `Column ${index + 1}`;
      columnSelect.append(option);
    });
    let clearButton = container.querySelector("[data-table-clear]");
    if (!clearButton) {
      clearButton = document.createElement("button");
      clearButton.type = "button";
      clearButton.className = "table-tool-icon table-tool-clear";
      clearButton.setAttribute("data-table-clear", "");
      tools.append(clearButton);
    }
    clearButton.classList.add("table-tool-icon", "table-tool-clear");
    clearButton.setAttribute("title", clearText);
    clearButton.setAttribute("aria-label", clearText);
    clearButton.textContent = "";
    const clearSvgNs = "http://www.w3.org/2000/svg";
    const clearIcon = document.createElementNS(clearSvgNs, "svg");
    clearIcon.setAttribute("viewBox", "0 0 24 24");
    clearIcon.setAttribute("aria-hidden", "true");
    const clearPath = document.createElementNS(clearSvgNs, "path");
    clearPath.setAttribute("d", "M6 6l12 12M18 6L6 18");
    clearPath.setAttribute("fill", "none");
    clearPath.setAttribute("stroke", "currentColor");
    clearPath.setAttribute("stroke-width", "2");
    clearPath.setAttribute("stroke-linecap", "round");
    clearIcon.append(clearPath);
    clearButton.append(clearIcon);
    const clearSrText = document.createElement("span");
    clearSrText.className = "sr-only";
    clearSrText.textContent = clearText;
    clearButton.append(clearSrText);

    const downloadButton = ensureDownloadButton(container, table);

    let visible = container.querySelector("[data-table-visible]");
    let total = container.querySelector("[data-table-total]");
    if (!visible || !total) {
      const status = document.createElement("p");
      status.className = "table-tool-status";
      visible = document.createElement("span");
      visible.setAttribute("data-table-visible", "");
      total = document.createElement("span");
      total.setAttribute("data-table-total", "");
      status.append(visible, document.createTextNode(" / "), total, document.createTextNode(" shown"));
      tools.append(status);
    }
    visible.textContent = String(rowCount);
    total.textContent = String(rowCount);

    return {
      searchInput,
      columnSelect,
      clearButton,
      downloadButton,
      visibleCounter: visible,
      totalCounter: total,
    };
  };

  const ensureTableWrap = (table) => {
    const existingWrap = table.closest(".table-wrap");
    if (existingWrap) {
      return existingWrap;
    }
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const parent = table.parentElement;
    if (parent) {
      parent.insertBefore(wrap, table);
      wrap.append(table);
    }
    return wrap;
  };

  const ensureEmptyMessage = (container, table) => {
    let message = container.querySelector("[data-table-empty]");
    if (message) {
      return message;
    }
    message = document.createElement("p");
    message.className = "table-empty table-empty-filter";
    message.setAttribute("data-table-empty", "");
    message.hidden = true;
    message.textContent = "No matching rows.";
    const wrap = table.closest(".table-wrap");
    if (wrap && wrap.parentElement === container) {
      wrap.insertAdjacentElement("afterend", message);
    } else {
      container.append(message);
    }
    return message;
  };

  const applyCompactIdentifierColumnClasses = (headers, entries) => {
    headers.forEach((header, columnIndex) => {
      if (!isCompactIdentifierColumn(header.textContent || "")) {
        return;
      }
      header.classList.add("table-col-compact-id");
      entries.forEach((entry) => {
        const cell = entry.row.cells.item(columnIndex);
        if (cell) {
          cell.classList.add("table-col-compact-id");
        }
      });
    });
  };

  const enhanceTableContainer = (container) => {
    if (container.dataset.tableEnhanced === "true") {
      return;
    }

    const table = container.querySelector("table");
    const tbody = table?.querySelector("tbody");
    const headers = table ? Array.from(table.querySelectorAll("thead th")) : [];
    if (!table || !tbody || headers.length === 0) {
      return;
    }
    ensureTableWrap(table);

    const rows = Array.from(tbody.querySelectorAll("tr"));
    const entries = rows
      .filter((row) => !row.querySelector("td[colspan]"))
      .map((row, index) => ({
        index,
        row,
        cells: [],
        cellsLower: [],
      }));
    if (entries.length === 0) {
      const generated = createTableTools(container, table, headers, 0);
      const emptyDownloadButton = generated.downloadButton || ensureDownloadButton(container, table);
      emptyDownloadButton.disabled = true;
      container.dataset.tableEnhanced = "true";
      return;
    }

    applyCompactIdentifierColumnClasses(headers, entries);

    const sortableHeaders = headers.filter((header) => header.getAttribute("data-no-sort") !== "true");
    sortableHeaders.forEach((header) => {
      header.classList.add("table-sortable");
      header.tabIndex = 0;
      header.setAttribute("aria-sort", "none");
    });

    let searchInput = container.querySelector("[data-table-search]");
    let columnSelect = container.querySelector("[data-table-column]");
    let clearButton = container.querySelector("[data-table-clear]");
    let downloadButton = container.querySelector("[data-table-download]");
    let visibleCounter = container.querySelector("[data-table-visible]");
    let totalCounter = container.querySelector("[data-table-total]");
    if (!searchInput || !columnSelect || !clearButton || !visibleCounter || !totalCounter) {
      const generated = createTableTools(container, table, headers, entries.length);
      searchInput = generated.searchInput;
      columnSelect = generated.columnSelect;
      clearButton = generated.clearButton;
      downloadButton = generated.downloadButton;
      visibleCounter = generated.visibleCounter;
      totalCounter = generated.totalCounter;
    }
    if (!downloadButton) {
      downloadButton = ensureDownloadButton(container, table);
    }

    const emptyMessage = ensureEmptyMessage(container, table);
    let sortColumn = -1;
    let sortDirection = "none";

    const refreshCellCache = () => {
      entries.forEach((entry) => {
        const cells = Array.from(entry.row.cells).map((cell) => extractCellValue(cell));
        entry.cells = cells;
        entry.cellsLower = cells.map((value) => value.toLowerCase());
      });
    };

    const renderSortState = () => {
      sortableHeaders.forEach((header) => {
        header.classList.remove("is-sort-asc", "is-sort-desc");
        header.setAttribute("aria-sort", "none");
      });
      if (sortColumn < 0 || sortDirection === "none") {
        return;
      }
      const active = headers[sortColumn];
      if (!active) {
        return;
      }
      if (sortDirection === "asc") {
        active.classList.add("is-sort-asc");
        active.setAttribute("aria-sort", "ascending");
      } else if (sortDirection === "desc") {
        active.classList.add("is-sort-desc");
        active.setAttribute("aria-sort", "descending");
      }
    };

    const applySort = () => {
      refreshCellCache();
      const ordered = [...entries];
      if (sortColumn >= 0 && (sortDirection === "asc" || sortDirection === "desc")) {
        const multiplier = sortDirection === "asc" ? 1 : -1;
        ordered.sort((left, right) => {
          const compared = compareCellValues(left.cells[sortColumn] || "", right.cells[sortColumn] || "");
          if (compared !== 0) {
            return compared * multiplier;
          }
          return left.index - right.index;
        });
      } else {
        ordered.sort((left, right) => left.index - right.index);
      }
      ordered.forEach((entry) => tbody.appendChild(entry.row));
      renderSortState();
    };

    const applyFilter = () => {
      refreshCellCache();
      const term = searchInput.value.trim().toLowerCase();
      const columnIndex = Number(columnSelect.value);
      let visible = 0;
      entries.forEach((entry) => {
        const haystack = columnIndex >= 0 ? entry.cellsLower[columnIndex] || "" : entry.cellsLower.join(" ");
        const isVisible = term === "" || haystack.includes(term);
        entry.row.hidden = !isVisible;
        if (isVisible) {
          visible += 1;
        }
      });
      visibleCounter.textContent = String(visible);
      totalCounter.textContent = String(entries.length);
      emptyMessage.hidden = visible !== 0;
      updateDownloadState();
    };

    const collectExportRows = () => {
      const scope = resolveDownloadScope(container);
      const sourceRows = Array.from(tbody.querySelectorAll("tr")).filter((row) => !row.querySelector("td[colspan]"));
      const exportRows = scope === "all" ? sourceRows : sourceRows.filter((row) => !row.hidden);
      const headerValues = headers.map((header) => normalizeWhitespace(header.textContent || ""));
      const dataValues = exportRows.map((row) => {
        const values = Array.from(row.cells).map((cell) => extractCellValue(cell));
        if (values.length < headerValues.length) {
          return values.concat(Array.from({ length: headerValues.length - values.length }, () => ""));
        }
        return values;
      });
      return {
        headerValues,
        dataValues,
      };
    };

    const updateDownloadState = () => {
      const { dataValues } = collectExportRows();
      downloadButton.disabled = dataValues.length === 0;
    };

    const handleTableDownload = () => {
      const { headerValues, dataValues } = collectExportRows();
      if (dataValues.length === 0) {
        return;
      }
      const tableTitle = inferTableTitle(container, table);
      const worksheetName = sanitizeSheetName(tableTitle);
      const fileName = `${slugifyFilePart(tableTitle)}_${formatFileTimestamp()}.xls`;
      const xml = buildSpreadsheetXml(worksheetName, headerValues, dataValues);
      triggerFileDownload(fileName, xml, "application/vnd.ms-excel;charset=utf-8");
    };

    sortableHeaders.forEach((header) => {
      const index = headers.indexOf(header);
      const toggleSort = () => {
        if (sortColumn !== index) {
          sortColumn = index;
          sortDirection = "asc";
        } else if (sortDirection === "asc") {
          sortDirection = "desc";
        } else if (sortDirection === "desc") {
          sortColumn = -1;
          sortDirection = "none";
        } else {
          sortDirection = "asc";
        }
        applySort();
        applyFilter();
      };
      header.addEventListener("click", toggleSort);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleSort();
        }
      });
    });

    searchInput.addEventListener("input", applyFilter);
    columnSelect.addEventListener("change", applyFilter);
    clearButton.addEventListener("click", () => {
      searchInput.value = "";
      columnSelect.value = "-1";
      sortColumn = -1;
      sortDirection = "none";
      applySort();
      applyFilter();
      searchInput.focus();
    });
    downloadButton.addEventListener("click", handleTableDownload);

    applySort();
    applyFilter();
    container.dataset.tableEnhanced = "true";
  };

  installers.installTableEnhancer = () => {
    const containers = new Set();
    document.querySelectorAll("[data-table-filter]").forEach((container) => {
      containers.add(container);
    });
    document.querySelectorAll("table").forEach((table) => {
      if (table.closest("[data-table-filter]")) {
        return;
      }
      const wrap = table.closest(".table-wrap");
      const container = wrap?.parentElement || table.parentElement;
      if (container) {
        containers.add(container);
      }
    });
    containers.forEach((container) => {
      enhanceTableContainer(container);
    });
  };

  installers.installTableWrapping = () => {
    document.querySelectorAll("table").forEach((table) => {
      ensureTableWrap(table);
    });
  };
})();
