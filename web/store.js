/* JADELY Store — browse, flag, play and convert everything in the library.
 *
 * The store never owns your content: it reads the folders you point it at, keeps
 * flags in `<file>.flags.json` sidecars, and conversions land as real PDFs beside
 * the original file.
 */
(function () {
  "use strict";

  const J = window.Jadely;
  const $ = (id) => document.getElementById(id);

  // program: null = every shelf, "" = the loose files at a library root
  const filters = { query: "", kind: "", tag: "", flag: "", program: null, view: "grid", sort: "newest" };
  let items = [];
  let shelves = [];
  let tags = [];
  let stats = { kinds: {} };
  let roots = [];
  let selected = null;
  let detail = null;

  const VIEWS = [
    { id: "all", label: "Everything", glyph: "▦" },
    { id: "favorite", label: "Favorites", glyph: "★" },
    { id: "pinned", label: "Pinned", glyph: "📌" },
    { id: "played", label: "Played", glyph: "✓" },
  ];

  const KINDS = ["note", "audio", "pdf", "document", "image"];

  const player = J.createPlayer({
    mount: $("player-mount"),
    onProgress: (item, payload) => {
      J.api("store_progress", {
        itemId: item.id,
        position: payload.position,
        duration: payload.duration,
        played: payload.played === undefined ? null : payload.played,
      }).catch(() => {});
      if (detail && detail.id === item.id && payload.duration) {
        detail.progress = Object.assign({}, detail.progress, {
          position: payload.position,
          duration: payload.duration,
        });
        renderPanel();
      }
      const row = items.find((entry) => entry.id === item.id);
      if (row && payload.duration) {
        row.progress = { position: payload.position, duration: payload.duration };
      }
    },
  });

  // ---------------------------------------------------------------- loading
  async function loadState() {
    const state = await J.api("store_state");
    shelves = state.shelves || [];
    tags = state.tags || [];
    stats = state.stats || { kinds: {} };
    roots = (stats.roots || []).map((root) => root.path);
    renderRail();
    renderKindFilters();
  }

  async function loadItems() {
    const data = await J.api("store_search", {
      query: filters.query,
      kind: filters.kind,
      tag: filters.tag,
      flag: filters.flag,
      program: filters.program,
      limit: 400,
    });
    items = data.items || [];
    items = sortItems(items);
    renderItems();
    renderHead();
  }

  function sortItems(list) {
    const sorted = list.slice();
    const by = {
      name: (a, b) => a.title.localeCompare(b.title),
      newest: (a, b) => b.mtimeEpoch - a.mtimeEpoch,
      oldest: (a, b) => a.mtimeEpoch - b.mtimeEpoch,
      size: (a, b) => b.size - a.size,
      duration: (a, b) => (b.duration || 0) - (a.duration || 0),
      words: (a, b) => (b.words || 0) - (a.words || 0),
    }[filters.sort];
    return by ? sorted.sort(by) : sorted;
  }

  // ------------------------------------------------------------------- rail
  function railItem(label, options) {
    const settings = options || {};
    const active =
      (settings.view && !filters.kind && !filters.tag && !filters.flag && filters.program === null && settings.view === "all") ||
      (settings.flag && filters.flag === settings.flag) ||
      (settings.kind && filters.kind === settings.kind && !filters.program) ||
      (settings.tag && filters.tag === settings.tag) ||
      (settings.program !== undefined && settings.program !== null && filters.program === settings.program);
    return (
      `<div class="rail-item${active ? " on" : ""}" ${settings.attrs || ""}>` +
      (settings.cover
        ? `<img class="rail-cover" src="${J.attr(settings.cover)}" alt="">`
        : `<span class="swatch" style="background:${J.attr(settings.colour || "var(--faint)")}"></span>`) +
      `<span class="grow nowrap">${J.escapeHtml(label)}</span>` +
      (settings.count !== undefined ? `<span class="count">${settings.count}</span>` : "") +
      "</div>"
    );
  }

  function renderRail() {
    const kinds = stats.kinds || {};
    const parts = ['<h3>Library</h3>'];
    VIEWS.forEach((view) => {
      const attrs =
        view.id === "all"
          ? 'data-view="all"'
          : `data-flag="${J.attr(view.id)}" data-view="flag"`;
      parts.push(railItem(view.label, { attrs, flag: view.id === "all" ? "" : view.id, view: view.id === "all" ? "all" : undefined, count: view.id === "all" ? stats.items : undefined }));
    });

    parts.push("<h3>Kinds</h3>");
    KINDS.filter((kind) => kinds[kind]).forEach((kind) => {
      parts.push(
        railItem(J.kindLabel(kind), {
          attrs: `data-kind="${J.attr(kind)}"`,
          kind,
          colour: "var(--accent)",
          count: kinds[kind],
        })
      );
    });

    if (shelves.length) {
      parts.push("<h3>Shelves</h3>");
      shelves.forEach((shelf) => {
        parts.push(
          railItem(shelf.title, {
            attrs: `data-program="${J.attr(shelf.folder)}"`,
            program: shelf.folder || "",
            cover: shelf.cover || "",
            count: shelf.items,
          })
        );
      });
    }

    if (tags.length) {
      parts.push("<h3>Tags</h3>");
      tags.slice(0, 24).forEach((tag) => {
        parts.push(railItem("#" + tag.tag, { attrs: `data-tag="${J.attr(tag.tag)}"`, tag: tag.tag, count: tag.count }));
      });
    }

    parts.push("<h3>Folders</h3>");
    roots.forEach((root) => {
      parts.push(
        `<div class="rail-item" data-reveal-root="${J.attr(root)}" title="${J.attr(root)}">` +
          '<span class="swatch" style="background:var(--faint)"></span>' +
          `<span class="grow nowrap">${J.escapeHtml(root.split(/[\\/]/).pop() || root)}</span></div>`
      );
    });
    parts.push('<div class="rail-sub" data-folders="1">Add or remove folders…</div>');
    $("rail").innerHTML = parts.join("");
  }

  function renderKindFilters() {
    const kinds = stats.kinds || {};
    const chips = ['<span class="chip' + (!filters.kind ? " on" : "") + '" data-kind="">All</span>'];
    KINDS.filter((kind) => kinds[kind]).forEach((kind) => {
      chips.push(
        `<span class="chip${filters.kind === kind ? " on" : ""}" data-kind="${J.attr(kind)}">${J.glyph(kind)} ${J.escapeHtml(
          J.kindLabel(kind)
        )} <span class="count">${kinds[kind]}</span></span>`
      );
    });
    $("kind-filters").innerHTML = chips.join("");
  }

  function renderHead() {
    const bits = [];
    if (filters.program !== null) bits.push(filters.program || "Loose files");
    if (filters.kind) bits.push(J.kindLabel(filters.kind));
    if (filters.tag) bits.push("#" + filters.tag);
    if (filters.flag) bits.push(filters.flag);
    if (filters.query) bits.push('“' + filters.query + '”');
    $("view-title").textContent = bits.length ? bits.join(" · ") : "Everything";
    $("view-count").textContent = J.plural(items.length, "item");
    const convertButton = $("btn-convert-here");
    if (filters.program !== null && filters.program !== "") {
      convertButton.classList.remove("hidden");
      convertButton.textContent = "Convert this shelf to PDF";
    } else {
      convertButton.classList.add("hidden");
    }
  }

  // ------------------------------------------------------------------ items
  function flagStrip(item) {
    const marks = [];
    if (item.flags.favorite) marks.push('<button class="starbtn" data-toggle="favorite" title="Favorite">★</button>');
    else marks.push('<button class="starbtn off" data-toggle="favorite" title="Favorite">★</button>');
    if (item.flags.pinned) marks.push('<button class="starbtn" data-toggle="pinned" title="Pinned">📌</button>');
    if (item.flags.played) marks.push('<button class="starbtn" title="Played">✓</button>');
    return '<div class="tile-flags">' + marks.join("") + "</div>";
  }

  function progressOf(item) {
    const progress = item.progress || {};
    if (!progress.duration || !progress.position) return null;
    return Math.min(100, Math.round((progress.position / progress.duration) * 100));
  }

  function renderItems() {
    const host = $("items");
    if (!items.length) {
      host.innerHTML =
        '<div class="empty"><div class="big">Nothing here yet.</div>' +
        "Drop markdown, PDFs, audio or Word files into the library folder, or use Import.</div>";
      return;
    }
    if (filters.view === "list") {
      host.innerHTML = items
        .map((item) => {
          const percent = progressOf(item);
          return (
            `<div class="rowitem${selected === item.id ? " on" : ""}" data-id="${J.attr(item.id)}">` +
            `<span class="glyph">${J.glyph(item.kind)}</span>` +
            '<div class="grow"><div class="title nowrap">' +
            J.escapeHtml(item.title) +
            '</div><div class="sub nowrap">' +
            J.escapeHtml(item.program || "Loose files") +
            " · " +
            J.escapeHtml(item.name) +
            "</div></div>" +
            '<div class="right">' +
            (percent !== null ? `<span>${percent}%</span>` : "") +
            (item.durationLabel ? `<span>${J.escapeHtml(item.durationLabel)}</span>` : "") +
            (item.words ? `<span>${item.words} words</span>` : "") +
            `<span>${J.escapeHtml(item.sizeLabel)}</span>` +
            (item.flags.favorite ? '<span title="Favorite">★</span>' : "") +
            "</div></div>"
          );
        })
        .join("");
      return;
    }
    host.innerHTML =
      '<div class="grid">' +
      items
        .map((item) => {
          const percent = progressOf(item);
          const art = item.cover
            ? `<img src="${J.attr(item.cover)}" alt="">`
            : `<span class="kindglyph">${J.glyph(item.kind)}</span>`;
          const meta = [J.kindLabel(item.kind)];
          if (item.durationLabel) meta.push(item.durationLabel);
          if (item.words) meta.push(item.words + " words");
          meta.push(item.sizeLabel);
          return (
            `<div class="tile${selected === item.id ? " on" : ""}" data-id="${J.attr(item.id)}">` +
            `<div class="tile-art">${art}` +
            (percent !== null
              ? `<div style="position:absolute;left:0;right:0;bottom:0;height:3px;background:rgba(0,0,0,.5)"><i style="display:block;height:100%;width:${percent}%;background:var(--accent)"></i></div>`
              : "") +
            flagStrip(item) +
            "</div>" +
            '<div class="tile-body"><div class="tile-title nowrap">' +
            J.escapeHtml(item.title) +
            '</div><div class="tile-meta">' +
            meta.map((part) => `<span>${J.escapeHtml(String(part))}</span>`).join("") +
            "</div></div></div>"
          );
        })
        .join("") +
      "</div>";
  }

  // ------------------------------------------------------------------ panel
  function flagButton(item, field, label, glyph) {
    const on = !!item.flags[field];
    return `<button class="chip${on ? " on" : ""}" data-flag-toggle="${J.attr(field)}">${glyph} ${J.escapeHtml(label)}</button>`;
  }

  function renderPanel() {
    const host = $("panel");
    if (!detail) {
      host.innerHTML =
        '<div class="empty"><div class="big">Nothing selected</div>Pick something to see its flags, tags and actions.</div>';
      return;
    }
    const item = detail;
    const percent = progressOf(item);
    const canPlay = item.kind === "audio";
    const canRead = item.kind === "note" || item.kind === "document";
    const pdfPath = item.absolute.replace(/\.[^.\\/]+$/, ".pdf");
    const hasPdf = items.some((entry) => entry.absolute === pdfPath);
    host.innerHTML =
      '<div class="row" style="gap:9px;align-items:flex-start">' +
      `<span class="glyph" style="font-size:20px">${J.glyph(item.kind)}</span>` +
      '<div class="grow"><h2>' +
      J.escapeHtml(item.title) +
      '</h2><div class="kv" style="margin-top:3px"><span>' +
      J.escapeHtml(item.program || "Loose files") +
      "</span><span>" +
      J.escapeHtml(item.name) +
      "</span></div></div></div>" +
      (percent !== null
        ? `<div style="margin-top:10px"><div class="muted" style="font-size:12px">${J.escapeHtml(
            (item.progress.positionLabel || "") + " listened"
          )}</div><div style="height:4px;background:var(--panel-3);border-radius:3px;margin-top:5px"><i style="display:block;height:100%;width:${percent}%;background:var(--accent);border-radius:3px"></i></div></div>`
        : "") +
      '<div class="row" style="gap:6px;margin-top:12px;flex-wrap:wrap">' +
      (canPlay ? '<button class="btn small primary" data-action="play">▶ Play</button>' : "") +
      (canRead ? '<button class="btn small primary" data-action="read">Read</button>' : "") +
      (item.kind === "pdf" ? '<button class="btn small primary" data-action="pdf">Open PDF</button>' : "") +
      "</div>" +
      '<div class="panel-section"><h4>Flags</h4><div class="flag-row">' +
      flagButton(item, "favorite", "Favorite", "★") +
      flagButton(item, "pinned", "Pinned", "📌") +
      flagButton(item, "played", "Played", "✓") +
      flagButton(item, "downloaded", "Offline", "⤓") +
      "</div></div>" +
      '<div class="panel-section"><h4>Tags</h4>' +
      '<div class="row" style="gap:6px;flex-wrap:wrap" id="tag-list">' +
      (item.tags.length
        ? item.tags.map((tag) => `<span class="taglink" data-remove-tag="${J.attr(tag)}">#${J.escapeHtml(tag)} ✕</span>`).join("")
        : '<span class="faint">No tags yet.</span>') +
      "</div>" +
      '<div class="row" style="gap:6px;margin-top:8px"><input id="tag-input" class="rate grow" placeholder="add a tag" value="">' +
      '<button class="btn small" data-action="add-tag">Add</button></div>' +
      "</div>" +
      '<div class="panel-section"><h4>Note</h4>' +
      `<textarea id="flag-note" class="rate" rows="3" style="width:100%;resize:vertical" placeholder="a note kept in the flag file">${J.escapeHtml(
        item.flags.note || ""
      )}</textarea>` +
      '<div class="row" style="margin-top:7px;gap:6px"><button class="btn small" data-action="save-note">Save note</button></div>' +
      "</div>" +
      '<div class="panel-section"><h4>Details</h4><dl class="meta-grid">' +
      row("Kind", J.kindLabel(item.kind)) +
      row("Size", item.sizeLabel) +
      (item.durationLabel ? row("Duration", item.durationLabel) : "") +
      (item.words ? row("Words", String(item.words)) : "") +
      row("Modified", J.formatDate(item.mtime)) +
      row("Folder", item.folder || "—") +
      "</dl></div>" +
      '<div class="panel-section"><h4>Actions</h4><div class="row" style="gap:6px;flex-wrap:wrap">' +
      (item.convertible && !hasPdf ? '<button class="btn small" data-action="convert">Convert to PDF</button>' : "") +
      (hasPdf && item.convertible ? '<span class="pill good">PDF exists</span>' : "") +
      '<button class="btn small ghost" data-action="export">Export…</button>' +
      '<button class="btn small ghost" data-action="copy">Copy path</button>' +
      '<button class="btn small ghost" data-action="reveal">Show in folder</button>' +
      '<button class="btn small danger" data-action="delete">Delete</button>' +
      "</div></div>" +
      (item.siblings && item.siblings.length
        ? '<div class="panel-section"><h4>Also in this shelf</h4>' +
          item.siblings
            .map(
              (other) =>
                `<div class="rowitem" data-id="${J.attr(other.id)}" style="padding:5px 7px"><span class="glyph" style="width:24px;height:24px;font-size:12px">${J.glyph(
                  other.kind
                )}</span><div class="grow nowrap" style="font-size:12.5px">${J.escapeHtml(other.title)}</div></div>`
            )
            .join("") +
          "</div>"
        : "") +
      '<div class="faint mono" style="margin-top:14px;font-size:11px;word-break:break-all">' +
      J.escapeHtml(item.absolute) +
      "</div>";
  }

  function row(key, value) {
    return `<dt>${J.escapeHtml(key)}</dt><dd>${J.escapeHtml(value)}</dd>`;
  }

  async function select(itemId) {
    selected = itemId;
    renderItems();
    try {
      const data = await J.api("store_item", { itemId });
      detail = data.item;
    } catch (error) {
      detail = null;
      J.failure(error);
    }
    renderPanel();
  }

  async function refresh(options) {
    const settings = options || {};
    await loadItems();
    if (settings.state !== false) await loadState();
    if (selected) {
      try {
        detail = (await J.api("store_item", { itemId: selected })).item;
        renderPanel();
      } catch (error) {
        selected = null;
        detail = null;
        renderPanel();
      }
    }
  }

  // ----------------------------------------------------------------- modals
  function closeModal() {
    J.stopSpeaking();
    $("modals").innerHTML = "";
  }

  function openModal(html, className) {
    $("modals").innerHTML =
      '<div class="modal-backdrop"><div class="modal ' + (className || "") + '">' + html + "</div></div>";
    const backdrop = $("modals").querySelector(".modal-backdrop");
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) closeModal();
    });
  }

  function modalHeader(title, extra) {
    return (
      '<header><h2 class="grow nowrap">' +
      J.escapeHtml(title) +
      "</h2>" +
      (extra || "") +
      '<button class="btn small ghost" data-close="1">Close</button></header>'
    );
  }

  async function openReader(itemId) {
    let item = detail && detail.id === itemId ? detail : (await J.api("store_item", { itemId })).item;
    const percent = progressOf(item);
    openModal(
      modalHeader(
        item.title,
        '<button class="btn small" data-speak="1">🔊 Read aloud</button>' +
          '<button class="btn small ghost" data-stop-speech="1">Stop</button>' +
          (item.convertible ? '<button class="btn small ghost" data-reader-convert="1">Convert to PDF</button>' : "")
      ) +
        '<div class="body"><article class="reader" id="reader-body">' +
        J.renderMarkdown(item.text || "", { showProperties: true }) +
        "</article></div>"
    );
    if (percent !== null) J.toast("Resuming from " + (item.progress.positionLabel || "the start") + ".");
  }

  function openPdf(item) {
    openModal(
      modalHeader(item.title, '<span class="pill pdf">PDF</span>') +
        '<div class="body pdf"><iframe src="' + J.attr(item.url) + '#view=FitH" title="' +
        J.attr(item.title) +
        '"></iframe></div>'
    );
  }

  async function openFolders() {
    const state = await J.api("store_roots");
    const list = (state.roots || [])
      .map(
        (root) =>
          '<div class="rowitem" style="cursor:default"><span class="glyph">📁</span>' +
          '<div class="grow"><div class="title">' +
          J.escapeHtml(root.name) +
          '</div><div class="sub mono nowrap">' +
          J.escapeHtml(root.path) +
          "</div></div>" +
          (root.exists ? "" : '<span class="pill bad">missing</span>') +
          `<button class="btn small ghost" data-remove-root="${J.attr(root.path)}">Remove</button>` +
          "</div>"
      )
      .join("");
    openModal(
      modalHeader("Library folders") +
        '<div class="body"><p class="muted">A library is just folders of files. JADELY indexes everything inside them and never moves anything.</p>' +
        list +
        '<div class="row" style="margin-top:12px;gap:6px">' +
        '<button class="btn small primary" data-add-root="1">Add a folder…</button>' +
        '<input class="rate grow" id="root-input" placeholder="or paste a folder path">' +
        '<button class="btn small" data-add-root-path="1">Add path</button>' +
        "</div></div>"
    );
  }

  // ---------------------------------------------------------------- actions
  async function playItem(itemId) {
    try {
      const item = (await J.api("store_item", { itemId })).item;
      detail = item;
      renderPanel();
      const progress = item.progress || {};
      const resume = progress.position && item.duration && progress.position < item.duration - 5 ? progress.position : 0;
      player.play({
        id: item.id,
        title: item.title,
        subtitle: (item.program || "") + (item.durationLabel ? " · " + item.durationLabel : ""),
        url: item.url,
        duration: item.duration,
        startAt: resume,
      });
      if (resume) J.toast("Resuming at " + J.formatTime(resume) + ".");
    } catch (error) {
      J.failure(error);
    }
  }

  async function convertItem(itemId, button) {
    await J.withBusy(button, async () => {
      const result = await J.api("convert_item", { itemId });
      J.toast("PDF written with the " + result.engine + " engine · " + J.formatBytes(result.bytes), "good");
    });
    await refresh();
    if (detail) select(detail.id);
  }

  async function convertBatch(program, button) {
    if (!window.confirm("Convert every markdown, text and .docx file" + (program ? " in " + program : "") + " to PDF?")) return;
    await J.withBusy(button, async () => {
      const report = await J.api("convert_batch", { program: program || "" });
      const counts = report.counts || {};
      J.toast(
        counts.converted + " converted · " + counts.skipped + " already had PDFs · " + counts.failed + " failed",
        counts.failed ? "bad" : "good"
      );
      (report.failed || []).slice(0, 3).forEach((failure) => J.toast(failure.error, "bad"));
    });
    await refresh();
  }

  async function askForPath(message) {
    const answer = window.prompt(message, "");
    return answer ? answer.trim() : "";
  }

  async function doImport(button) {
    await J.withBusy(button, async () => {
      let result = await J.api("store_import_pick", { folder: "Imported" });
      if (result.cancelled) {
        const path = await askForPath("Folder or file path to import into the library:");
        if (!path) return;
        result = await J.api("store_import", { paths: [path], folder: "Imported" });
      }
      const count = (result.imported || []).length;
      J.toast(count ? J.plural(count, "file") + " imported into " + result.folder : "Nothing new to import.", count ? "good" : undefined);
    });
    await refresh();
  }

  async function doExport(itemId, program) {
    const call = program
      ? () => J.api("store_export_program", { program })
      : () => J.api("store_export", { itemId });
    let result = await call();
    if (result.cancelled) {
      const path = await askForPath("Destination folder:");
      if (!path) return;
      result = program
        ? await J.api("store_export_program", { program, folder: path })
        : await J.api("store_export", { itemId, folder: path });
    }
    J.toast("Exported to " + (result.exported === undefined ? result.folder : result.exported), "good");
  }

  // ----------------------------------------------------------------- events
  document.addEventListener("click", async (event) => {
    const target = event.target;
    const inModal = target.closest("#modals");

    if (target.dataset && target.dataset.close) return closeModal();
    if (target.dataset && target.dataset.themeToggle !== undefined) return;

    // toolbar and rail
    if (target.id === "view-grid" || target.id === "view-list") {
      filters.view = target.id === "view-grid" ? "grid" : "list";
      $("view-grid").classList.toggle("ghost", filters.view !== "grid");
      $("view-list").classList.toggle("ghost", filters.view !== "list");
      return renderItems();
    }
    const chip = target.closest("#kind-filters .chip");
    if (chip) {
      filters.kind = chip.dataset.kind || "";
      renderKindFilters();
      renderRail();
      return refresh();
    }
    const railClick = target.closest(".rail-item, .rail-sub");
    if (railClick && !railClick.dataset.revealRoot) {
      if (railClick.dataset.view === "all") {
        filters.flag = filters.kind = filters.tag = "";
        filters.program = null;
      } else if (railClick.dataset.flag) {
        filters.flag = railClick.dataset.flag;
        filters.kind = filters.tag = filters.program = "";
      } else if (railClick.dataset.kind !== undefined) {
        filters.kind = railClick.dataset.kind;
        filters.flag = filters.tag = "";
        filters.program = null;
      } else if (railClick.dataset.tag) {
        filters.tag = railClick.dataset.tag;
        filters.kind = filters.flag = filters.program = "";
      } else if (railClick.dataset.program !== undefined) {
        filters.program = railClick.dataset.program;
        filters.kind = filters.flag = filters.tag = "";
      } else if (railClick.dataset.folders) {
        return openFolders();
      } else if (railClick.dataset.revealRoot) {
        try {
          await J.api("reveal_path", { path: railClick.dataset.revealRoot });
        } catch (error) {
          J.failure(error);
        }
        return;
      }
      renderRail();
      renderKindFilters();
      return refresh();
    }

    if (target.id === "btn-import") return doImport(target);
    if (target.id === "btn-folders") return openFolders();
    if (target.id === "btn-convert-here") return convertBatch(filters.program, target);

    // item tiles / rows
    const toggleStar = target.closest("[data-toggle]");
    if (toggleStar && !inModal) {
      const tile = toggleStar.closest("[data-id]");
      if (tile) {
        try {
          await J.api("store_toggle", { itemId: tile.dataset.id, flag: toggleStar.dataset.toggle });
        } catch (error) {
          J.failure(error);
        }
        return refresh({ state: false });
      }
    }
    const itemNode = target.closest("[data-id]");
    if (itemNode && !inModal) return select(itemNode.dataset.id);

    // panel actions
    const toggle = target.closest("[data-flag-toggle]");
    if (toggle && detail) {
      try {
        await J.api("store_toggle", { itemId: detail.id, flag: toggle.dataset.flagToggle });
      } catch (error) {
        J.failure(error);
      }
      return refresh();
    }
    const removeTag = target.closest("[data-remove-tag]");
    if (removeTag && detail) {
      const remaining = detail.tags.filter((tag) => tag !== removeTag.dataset.removeTag);
      await J.api("store_flags", { itemId: detail.id, patch: { tags: remaining } });
      return refresh();
    }
    const action = target.closest("[data-action]");
    if (action && detail) {
      const what = action.dataset.action;
      try {
        if (what === "play") await playItem(detail.id);
        else if (what === "read") await openReader(detail.id);
        else if (what === "pdf") openPdf(detail);
        else if (what === "convert") await convertItem(detail.id, action);
        else if (what === "export") await doExport(detail.id, "");
        else if (what === "copy") {
          await navigator.clipboard.writeText(detail.absolute);
          J.toast("Path copied.");
        } else if (what === "reveal") await J.api("store_reveal", { itemId: detail.id });
        else if (what === "delete") {
          if (window.confirm("Move “" + detail.title + "” to the library trash?")) {
            const result = await J.api("store_delete", { itemId: detail.id });
            J.toast("Moved to " + result.movedTo, "good");
            selected = null;
            detail = null;
            await refresh();
            renderPanel();
          }
        } else if (what === "add-tag") {
          const input = $("tag-input");
          const value = (input.value || "").trim().replace(/^#/, "");
          if (value) {
            const tags = detail.tags.concat(value);
            await J.api("store_flags", { itemId: detail.id, patch: { tags } });
            await refresh();
          }
        } else if (what === "save-note") {
          const note = $("flag-note").value;
          await J.api("store_flags", { itemId: detail.id, patch: { note } });
          J.toast("Note saved to the flag file.", "good");
          await refresh();
        }
      } catch (error) {
        J.failure(error);
      }
      return;
    }

    // folders modal
    if (target.dataset && target.dataset.addRoot) {
      try {
        const result = await J.api("store_add_root", {});
        if (result.cancelled) {
          const path = await askForPath("Folder to add to the library:");
          if (!path) return;
          await J.api("store_add_root", { path });
        }
        closeModal();
        await refresh();
      } catch (error) {
        J.failure(error);
      }
      return;
    }
    if (target.dataset && target.dataset.addRootPath) {
      const value = ($("root-input") || {}).value;
      if (value) {
        try {
          await J.api("store_add_root", { path: value.trim() });
          closeModal();
          await refresh();
        } catch (error) {
          J.failure(error);
        }
      }
      return;
    }
    const removeRoot = target.closest("[data-remove-root]");
    if (removeRoot) {
      try {
        await J.api("store_remove_root", { path: removeRoot.dataset.removeRoot });
        openFolders();
        await refresh();
      } catch (error) {
        J.failure(error);
      }
      return;
    }

    // reader controls
    if (target.dataset && target.dataset.speak) {
      const body = $("reader-body");
      const started = J.speakElements(body, { rate: 1 });
      if (started) J.toast("Reading aloud. Press Stop to end it.");
      return;
    }
    if (target.dataset && target.dataset.stopSpeech) {
      J.stopSpeaking();
      document.querySelectorAll(".speaking").forEach((node) => node.classList.remove("speaking"));
      return;
    }
    if (target.dataset && target.dataset.readerConvert && detail) {
      return convertItem(detail.id, target);
    }
  });

  $("q").addEventListener(
    "input",
    J.debounce((event) => {
      filters.query = event.target.value.trim();
      refresh({ state: false });
    }, 180)
  );
  $("sort").addEventListener("change", (event) => {
    filters.sort = event.target.value;
    renderItems();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("modals").innerHTML) closeModal();
  });

  // -------------------------------------------------------------------- init
  (async function boot() {
    const state = await J.init();
    if (state && state.convert) {
      $("engine-note").textContent =
        state.convert.resolved === "edge" ? "PDF via " + (state.convert.browserName || "browser") : "PDF via built-in writer";
    }
    try {
      await loadState();
      await loadItems();
      renderPanel();
    } catch (error) {
      J.failure(error);
    }
  })();
})();
