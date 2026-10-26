/* jadeli — application logic (no build step, no dependencies). */
(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const esc = (value) => (window.JadeliMD ? JadeliMD.escapeHtml(value) : String(value ?? ""));
  const FILENAME_RE = /[<>:"/\\|?*\u0000-\u001f]/g;

  const ICONS = {
    note: '<svg viewBox="0 0 24 24"><path d="M6 3h7l5 5v13H6z"/><path d="M13 3v5h5"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  };

  const state = {
    ready: false,
    vaultPath: "",
    vaultName: "vault",
    theme: "dark",
    split: false,
    focus: 0,
    panes: [],
    sidebarTab: "files",
    rightPanel: "outline",
    tree: [],
    titles: [],
    titleMap: new Map(),
    stemMap: new Map(),
    mode: "welcome",
    previousMode: "welcome",
    books: [],
    bookId: null,
    book: null,
    graphData: null,
    saving: false,
    linksTimer: null,
    outlineTimer: null,
    lastSavedAt: null,
    contextMenu: null,
  };

  const el = {};

  // Tabs, the active index and the write/read mode belong to a pane, not to the
  // app. These accessors point at the focused pane so the single-pane code can
  // keep using state.tabs / state.active / state.viewMode as before.
  const noTabs = [];
  function paneField(name, fallback) {
    Object.defineProperty(state, name, {
      configurable: true,
      get: () => {
        const pane = state.panes[state.focus];
        return pane ? pane[name] : fallback;
      },
      set: (value) => {
        const pane = state.panes[state.focus];
        if (pane) pane[name] = value;
      },
    });
  }
  paneField("tabs", noTabs);
  paneField("active", -1);
  paneField("viewMode", "split");

  const focused = () => state.panes[state.focus] || state.panes[0];
  const otherPane = () => state.panes[state.focus === 0 ? 1 : 0];
  const otherPaneIndex = () => (state.focus === 0 ? 1 : 0);

  // ------------------------------------------------------------------ api
  async function api(method, payload = {}) {
    const response = await fetch(`/api/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Server error ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Request failed");
    return data.data || {};
  }

  const prefs = (() => {
    try {
      return JSON.parse(localStorage.getItem("jadeli.prefs") || "{}");
    } catch (error) {
      return {};
    }
  })();

  function savePrefs(patch) {
    Object.assign(prefs, patch);
    try {
      localStorage.setItem("jadeli.prefs", JSON.stringify(prefs));
    } catch (error) {
      /* ignore quota issues */
    }
  }

  function saveServerPrefs(patch) {
    api("save_prefs", { prefs: patch }).catch(() => {});
  }

  // ---------------------------------------------------------------- toast
  let toastTimer = null;
  function toast(message, kind) {
    el.toast.textContent = message;
    el.toast.classList.toggle("is-error", kind === "error");
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.toast.hidden = true;
    }, kind === "error" ? 5200 : 2600);
  }

  // ------------------------------------------------------------- dialogs
  function openDialog(options) {
    const {
      title,
      fields = [],
      confirmLabel = "Save",
      danger = false,
      bodyHtml = "",
      onMount,
    } = options;

    return new Promise((resolve) => {
      const root = el.modalRoot;
      root.hidden = false;
      root.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true">
          <div class="modal-header">${esc(title)}</div>
          <div class="modal-body">
            ${bodyHtml}
            ${fields
              .map((field) => {
                const id = `field-${field.name}`;
                let control;
                if (field.type === "textarea") {
                  control = `<textarea class="field" id="${id}" rows="${field.rows || 3}" placeholder="${esc(field.placeholder || "")}">${esc(field.value ?? "")}</textarea>`;
                } else if (field.type === "select") {
                  control = `<select id="${id}">${(field.options || [])
                    .map(
                      (option) =>
                        `<option value="${esc(option.value)}" ${String(option.value) === String(field.value) ? "selected" : ""}>${esc(option.label)}</option>`
                    )
                    .join("")}</select>`;
                } else {
                  control = `<input id="${id}" type="${field.type === "number" ? "number" : "text"}" value="${esc(field.value ?? "")}" placeholder="${esc(field.placeholder || "")}" ${field.type === "number" ? 'min="0" step="500"' : ""}>`;
                }
                return `<div class="modal-field"><label for="${id}">${esc(field.label)}</label>${control}${
                  field.hint ? `<div class="hint">${esc(field.hint)}</div>` : ""
                }</div>`;
              })
              .join("")}
          </div>
          <div class="modal-footer">
            <button class="btn ghost" data-modal="cancel">Cancel</button>
            <button class="btn ${danger ? "danger" : "primary"}" data-modal="ok">${esc(confirmLabel)}</button>
          </div>
        </div>`;

      const finish = (value) => {
        root.hidden = true;
        root.innerHTML = "";
        document.removeEventListener("keydown", onKey, true);
        resolve(value);
      };

      const collect = () => {
        const values = {};
        fields.forEach((field) => {
          const node = $(`#field-${field.name}`);
          if (!node) return;
          values[field.name] = field.type === "number" ? Number(node.value) : node.value;
        });
        return values;
      };

      const submit = () => finish(collect());

      function onKey(event) {
        if (event.key === "Escape") {
          event.preventDefault();
          finish(null);
        } else if (event.key === "Enter" && !event.shiftKey) {
          const tag = (event.target && event.target.tagName) || "";
          if (tag !== "TEXTAREA") {
            event.preventDefault();
            submit();
          }
        }
      }

      document.addEventListener("keydown", onKey, true);
      root.onclick = (event) => {
        if (event.target === root) finish(null);
        const action = event.target.closest?.("[data-modal]")?.dataset.modal;
        if (action === "cancel") finish(null);
        if (action === "ok") submit();
      };

      const first = root.querySelector("input, textarea, select");
      if (first) {
        first.focus();
        if (first.select) first.select();
      }
      if (onMount) onMount(root, submit);
    });
  }

  async function confirmDialog(title, message, confirmLabel = "Continue", danger = true) {
    const result = await openDialog({
      title,
      bodyHtml: `<p class="muted" style="margin:2px 0 14px;line-height:1.6">${esc(message)}</p>`,
      confirmLabel,
      danger,
    });
    return Boolean(result);
  }

  // ----------------------------------------------------------- tree view
  function folderOpenSet() {
    try {
      return new Set(JSON.parse(localStorage.getItem("jadeli.folders") || "[]"));
    } catch (error) {
      return new Set();
    }
  }
  let openFolders = folderOpenSet();

  function isFolderOpen(path) {
    return openFolders.has(path);
  }

  function toggleFolder(path) {
    if (openFolders.has(path)) openFolders.delete(path);
    else openFolders.add(path);
    try {
      localStorage.setItem("jadeli.folders", JSON.stringify([...openFolders]));
    } catch (error) {
      /* ignore */
    }
    renderTree();
  }

  function countNotes(node) {
    if (node.type === "note") return 1;
    return (node.children || []).reduce((total, child) => total + countNotes(child), 0);
  }

  function buildTreeNodes(nodes) {
    const fragment = document.createDocumentFragment();
    (nodes || []).forEach((node) => {
      if (node.type === "folder") {
        const wrapper = document.createElement("div");
        wrapper.className = "tree-folder";
        const open = isFolderOpen(node.path);
        const button = document.createElement("button");
        button.className = "tree-row";
        button.innerHTML = `<span class="caret">${open ? "▾" : "▸"}</span>${ICONS.folder}<span class="label">${esc(node.name)}</span><span class="count">${countNotes(node)}</span>`;
        button.addEventListener("click", () => toggleFolder(node.path));
        const children = document.createElement("div");
        children.className = "tree-children";
        children.hidden = !open;
        children.appendChild(buildTreeNodes(node.children));
        wrapper.append(button, children);
        fragment.appendChild(wrapper);
      } else {
        const button = document.createElement("button");
        button.className = "tree-row";
        button.dataset.path = node.path;
        const activeTab = state.tabs[state.active];
        if (activeTab && activeTab.path === node.path) button.classList.add("is-active");
        button.innerHTML = `<span class="caret"></span>${ICONS.note}<span class="label">${esc(node.name.replace(/\.(md|markdown|txt)$/i, ""))}</span>`;
        button.addEventListener("click", () => openNote(node.path));
        button.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          showContextMenu(event, node.path);
        });
        fragment.appendChild(button);
      }
    });
    return fragment;
  }

  function renderTree() {
    el.fileTree.innerHTML = "";
    if (!state.tree.length) {
      el.fileTree.innerHTML = '<p class="muted small pad">No notes yet — create one with Ctrl+N.</p>';
      return;
    }
    el.fileTree.appendChild(buildTreeNodes(state.tree));
  }

  async function refreshTree() {
    const data = await api("tree");
    state.tree = data.tree || [];
    state.vaultName = data.vault || state.vaultName;
    el.vaultName.textContent = state.vaultName;
    renderTree();
    await refreshTitles();
    refreshTagsSoon();
  }

  async function refreshTitles() {
    const data = await api("note_titles");
    state.titles = data.notes || [];
    state.titleMap = new Map();
    state.stemMap = new Map();
    state.titles.forEach((note) => {
      state.titleMap.set(note.title.toLowerCase(), note.path);
      const stem = note.path.split("/").pop().replace(/\.(md|markdown|txt)$/i, "").toLowerCase();
      state.stemMap.set(stem, note.path);
      state.stemMap.set(note.path.replace(/\.(md|markdown|txt)$/i, "").toLowerCase(), note.path);
    });
  }

  function resolveLink(name) {
    const key = String(name || "").trim().toLowerCase();
    if (!key) return { path: "" };
    if (state.titleMap.has(key)) return { path: state.titleMap.get(key), title: name };
    if (state.stemMap.has(key)) return { path: state.stemMap.get(key), title: name };
    return { path: "" };
  }

  // ----------------------------------------------------------- context menu
  function hideContextMenu() {
    if (state.contextMenu) {
      state.contextMenu.remove();
      state.contextMenu = null;
    }
  }

  function openContextMenu(event, entries) {
    hideContextMenu();
    const menu = document.createElement("div");
    menu.className = "context-menu";
    entries.forEach(({ label, run, danger }) => {
      const button = document.createElement("button");
      button.className = `context-item${danger ? " is-danger" : ""}`;
      button.textContent = label;
      button.addEventListener("click", async () => {
        hideContextMenu();
        await run();
      });
      menu.appendChild(button);
    });

    document.body.appendChild(menu);
    const { innerWidth, innerHeight } = window;
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 8)}px`;
    menu.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 8)}px`;
    state.contextMenu = menu;
    setTimeout(() => {
      document.addEventListener("click", hideContextMenu, { once: true });
    }, 0);
  }

  function showContextMenu(event, path) {
    openContextMenu(event, [
      { label: "Open", run: () => openNote(path) },
      { label: "Open in other pane", run: () => openInOtherPane(path) },
      { label: "Rename…", run: () => renameFlow(path) },
      { label: "Duplicate", run: () => duplicateNote(path) },
      {
        label: "Reveal in file manager",
        run: async () => {
          try {
            await api("reveal", { path });
          } catch (error) {
            toast(error.message, "error");
          }
        },
      },
      { label: "Delete", run: () => deleteFlow(path), danger: true },
    ]);
  }

  function showTabMenu(event, pane, index) {
    const tab = pane.tabs[index];
    if (!tab) return;
    openContextMenu(event, [
      { label: "Open in other pane", run: () => openInOtherPane(tab.path) },
      { label: "Close", run: () => closeTab(pane, index) },
      { label: "Close other tabs", run: () => closeOtherTabs(pane, index) },
    ]);
  }

  // ----------------------------------------------------------------- tabs
  const activeTab = () => {
    const pane = focused();
    return pane ? pane.tabs[pane.active] || null : null;
  };

  function paneOfTab(tab) {
    return state.panes.find((pane) => pane.tabs.includes(tab)) || focused();
  }

  function renderPaneChrome(pane) {
    if (!pane) return;
    const empty = pane.tabs.length === 0;
    pane.els.empty.hidden = !empty;
    pane.els.bar.hidden = empty;
    pane.els.body.hidden = empty;
  }

  function renderTabs(pane) {
    const target = pane || focused();
    if (!target) return;
    target.els.tabs.innerHTML = "";
    target.tabs.forEach((tab, index) => {
      const node = document.createElement("div");
      node.className = `tab${index === target.active ? " is-active" : ""}${
        tab.content !== tab.saved ? " is-dirty" : ""
      }`;
      node.title = tab.path;
      node.innerHTML = `<span class="tab-dot"></span><span class="tab-title">${esc(tab.title)}</span><button class="tab-close" title="Close">×</button>`;
      node.addEventListener("click", (event) => {
        if (event.target.closest(".tab-close")) return;
        activateTab(target, index);
      });
      node.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        showTabMenu(event, target, index);
      });
      node.querySelector(".tab-close").addEventListener("click", (event) => {
        event.stopPropagation();
        closeTab(target, index);
      });
      target.els.tabs.appendChild(node);
    });
  }

  async function openNote(path, options = {}) {
    if (!path) return;
    let index = options.pane;
    if (index !== 0 && index !== 1) index = state.focus;
    if (index === 1 && !state.split) setSplit(true, { focus: false, persist: false });
    const pane = state.panes[index];
    if (!pane) return;
    const existing = pane.tabs.findIndex((tab) => tab.path === path);
    if (existing >= 0) {
      await activateTab(pane, existing, options);
      return;
    }
    try {
      const note = await api("read_note", { path });
      const duplicated = pane.tabs.findIndex((tab) => tab.path === note.path);
      if (duplicated >= 0) {
        await activateTab(pane, duplicated, options);
        return;
      }
      pane.tabs.push({
        path: note.path,
        title: note.title,
        content: note.content,
        saved: note.content,
        mtime: note.mtime,
        cursor: 0,
      });
      pane.active = pane.tabs.length - 1;
      await activateTab(pane, pane.active, options);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function activateTab(pane, index, options = {}) {
    if (!pane || index < 0 || index >= pane.tabs.length) return;
    const previous = pane.tabs[pane.active];
    if (previous && previous !== pane.tabs[index] && previous.content !== previous.saved) {
      await saveTab(previous, pane);
    }
    pane.active = index;
    state.mode = "doc";
    showMode();
    const tab = pane.tabs[index];
    pane.els.editor.value = tab.content;
    renderTabs(pane);
    renderBreadcrumb(pane);
    renderPreview(pane);
    setViewMode(pane, pane.viewMode, false);
    renderPaneChrome(pane);
    if (pane === focused()) {
      if (options.focus !== false) pane.els.editor.focus();
      updateOutline();
      refreshLinks();
      renderTreeActive();
      updateStatusBar();
      setRightPanel(state.rightPanel, false);
    }
    pane.els.editor.scrollTop = 0;
    pane.els.preview.scrollTop = 0;
  }

  function renderTreeActive() {
    const open = new Set();
    state.panes.forEach((pane) => {
      const tab = pane.tabs[pane.active];
      if (tab) open.add(tab.path);
    });
    const current = activeTab();
    $$(".tree-row[data-path]").forEach((row) => {
      const isCurrent = Boolean(current) && row.dataset.path === current.path;
      row.classList.toggle("is-active", isCurrent);
      row.classList.toggle("is-open", !isCurrent && open.has(row.dataset.path));
    });
  }

  async function closeTab(pane, index) {
    const tab = pane.tabs[index];
    if (!tab) return;
    if (tab.content !== tab.saved) await saveTab(tab, pane);
    const wasActive = index === pane.active;
    pane.tabs.splice(index, 1);
    if (!pane.tabs.length) {
      pane.active = -1;
      pane.els.editor.value = "";
      renderTabs(pane);
      renderBreadcrumb(pane);
      renderPreview(pane);
      renderPaneChrome(pane);
      if (pane === focused()) {
        updateOutline();
        el.panelLinks.innerHTML = "";
        renderTreeActive();
        updateStatusBar();
      }
      if (!state.panes.some((entry) => entry.tabs.length)) {
        state.mode = "welcome";
        showMode();
      }
      return;
    }
    if (index < pane.active) pane.active -= 1;
    if (wasActive) pane.active = Math.min(index, pane.tabs.length - 1);
    pane.active = Math.max(0, Math.min(pane.active, pane.tabs.length - 1));
    await activateTab(pane, pane.active, { focus: false });
  }

  async function closeOtherTabs(pane, index) {
    const keep = pane.tabs[index];
    if (!keep) return;
    for (const tab of pane.tabs.filter((entry, i) => i !== index)) {
      if (tab.content !== tab.saved) await saveTab(tab, pane);
    }
    pane.tabs = [keep];
    await activateTab(pane, 0, { focus: false });
  }

  // ---------------------------------------------------------------- saving
  function scheduleSave(pane) {
    const target = pane || focused();
    if (!target) return;
    clearTimeout(target.saveTimer);
    target.saveTimer = setTimeout(() => saveTab(target.tabs[target.active], target), 700);
  }

  // The same note can sit in both panes. Mirroring keeps the second view in
  // step instead of letting one copy silently overwrite the other.
  function mirrorTab(source) {
    state.panes.forEach((pane) => {
      let touched = false;
      pane.tabs.forEach((tab) => {
        if (tab === source || tab.path !== source.path) return;
        tab.content = source.content;
        tab.saved = source.saved;
        const active = pane.tabs[pane.active] === tab;
        if (active) {
          if (document.activeElement !== pane.els.editor) {
            const { selectionStart, selectionEnd } = pane.els.editor;
            pane.els.editor.value = tab.content;
            pane.els.editor.setSelectionRange(selectionStart, selectionEnd);
          }
          renderPreview(pane);
        }
        touched = true;
      });
      if (touched) renderTabs(pane);
    });
  }

  async function saveTab(tab, pane) {
    if (!tab || tab.content === tab.saved) return;
    const owner = pane || paneOfTab(tab);
    if (state.saving) {
      setTimeout(() => saveTab(tab, owner), 200);
      return;
    }
    state.saving = true;
    const snapshot = tab.content;
    try {
      const result = await api("write_note", { path: tab.path, content: snapshot });
      tab.saved = snapshot;
      tab.mtime = result.mtime;
      if (result.title && result.title !== tab.title) tab.title = result.title;
      state.lastSavedAt = new Date();
      state.panes.forEach((entry) => {
        if (entry.tabs.includes(tab)) renderTabs(entry);
      });
      if (owner === focused()) updateStatusBar();
      mirrorTab(tab);
      refreshTagsSoon();
      refreshTitlesSoon();
    } catch (error) {
      toast(`Could not save: ${error.message}`, "error");
    } finally {
      state.saving = false;
      if (tab.content !== tab.saved) scheduleSave(owner);
    }
  }

  async function saveActive(force) {
    const pane = focused();
    const tab = pane ? pane.tabs[pane.active] : null;
    if (!tab) return;
    if (!force && tab.content === tab.saved) return;
    await saveTab(tab, pane);
  }

  // --------------------------------------------------------------- preview
  function renderPreview(pane) {
    const target = pane || focused();
    if (!target) return;
    const tab = target.tabs[target.active];
    if (!tab) {
      target.els.preview.innerHTML = "";
      return;
    }
    const scroll = target.els.preview.scrollTop;
    target.els.preview.innerHTML = JadeliMD.render(tab.content, {
      resolveLink,
      showProperties: true,
    });
    target.els.preview.scrollTop = scroll;
  }

  function bindPreview(preview, pane) {
    preview.addEventListener("click", async (event) => {
      const external = event.target.closest('a.external[href^="http"]');
      if (external) {
        event.preventDefault();
        api("open_external", { url: external.href }).catch((error) => toast(error.message, "error"));
        return;
      }
      const wiki = event.target.closest("a.wikilink");
      if (wiki) {
        event.preventDefault();
        const path = wiki.dataset.path;
        if (path) return openNote(path, { pane: pane.index });
        const name = wiki.dataset.wikilink;
        const folder = await currentFolder();
        try {
          const created = await api("create_note", {
            path: [folder, `${name}.md`].filter(Boolean).join("/"),
            content: `# ${name}\n\n`,
          });
          await refreshTree();
          toast(`Created “${name}”`);
          return openNote(created.path, { pane: pane.index });
        } catch (error) {
          toast(error.message, "error");
        }
        return;
      }
      const tag = event.target.closest("a.tag");
      if (tag) {
        event.preventDefault();
        selectSidebarTab("search");
        el.searchInput.value = `#${tag.dataset.tag}`;
        onSearchInput();
      }
    });
  }

  function updateOutline() {
    const tab = activeTab();
    const container = el.panelOutline;
    if (!tab) {
      container.innerHTML = '<p class="muted small pad">No note open.</p>';
      return;
    }
    const headings = [];
    let inFence = false;
    tab.content.split("\n").forEach((line) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) {
        inFence = !inFence;
        return;
      }
      if (inFence) return;
      const match = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (match) headings.push({ level: match[1].length, text: match[2].trim() });
    });
    if (!headings.length) {
      container.innerHTML = '<p class="muted small pad">No headings in this note.</p>';
      return;
    }
    container.innerHTML = "";
    headings.forEach((heading) => {
      const button = document.createElement("button");
      button.className = `outline-item lvl-${heading.level}`;
      button.textContent = heading.text;
      button.addEventListener("click", () => {
        const id = JadeliMD.slugify(heading.text);
        const pane = focused();
        if (!pane) return;
        if (pane.viewMode === "edit") setViewMode(pane, "split");
        const target =
          pane.els.preview.querySelector(`#${CSS.escape(id)}`) || pane.els.preview.querySelector(`[id="${id}"]`);
        if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
      });
      container.appendChild(button);
    });
  }

  function refreshLinks() {
    clearTimeout(state.linksTimer);
    state.linksTimer = setTimeout(async () => {
      const tab = activeTab();
      if (!tab) return;
      try {
        const data = await api("links", { path: tab.path });
        renderLinksPanel(data);
      } catch (error) {
        el.panelLinks.innerHTML = `<p class="muted small pad">${esc(error.message)}</p>`;
      }
    }, 250);
  }

  function renderLinksPanel(data) {
    const container = el.panelLinks;
    const parts = [];
    parts.push(`<div class="link-group-title">Backlinks (${(data.backlinks || []).length})</div>`);
    if (!(data.backlinks || []).length) {
      parts.push('<p class="muted small pad">No other note links here yet.</p>');
    } else {
      data.backlinks.forEach((link) => {
        parts.push(
          `<button class="link-card" data-open="${esc(link.path)}"><div class="link-title">${esc(link.title)}</div><div class="link-context">${esc(link.context || link.path)}</div></button>`
        );
      });
    }
    parts.push(`<div class="link-group-title">Links out (${(data.links || []).length})</div>`);
    if (!(data.links || []).length) {
      parts.push('<p class="muted small pad">This note does not link anywhere yet.</p>');
    } else {
      data.links.forEach((link) => {
        parts.push(
          `<button class="link-card${link.exists ? "" : " is-missing"}" data-open="${esc(link.path)}" data-create="${esc(link.target)}"><div class="link-title">${esc(link.title)}</div><div class="link-context">${link.exists ? esc(link.path) : "Not created yet — click to create"}</div></button>`
        );
      });
    }
    container.innerHTML = parts.join("");
  }

  // ---------------------------------------------------------------- editor
  function onEditorInput(pane) {
    const target = pane || focused();
    if (!target) return;
    const tab = target.tabs[target.active];
    if (!tab) return;
    tab.content = target.els.editor.value;
    renderTabs(target);
    if (target === focused()) updateStatusBar();
    clearTimeout(target.previewTimer);
    target.previewTimer = setTimeout(() => renderPreview(target), 140);
    clearTimeout(state.outlineTimer);
    state.outlineTimer = setTimeout(() => {
      if (target === focused()) updateOutline();
    }, 320);
    if (target === focused()) refreshLinks();
    scheduleSave(target);
    mirrorTab(tab);
  }

  function wrapSelection(before, after, placeholder) {
    const pane = focused();
    if (!pane) return;
    const { selectionStart, selectionEnd, value } = pane.els.editor;
    const selected = value.slice(selectionStart, selectionEnd) || placeholder || "";
    pane.els.editor.setRangeText(`${before}${selected}${after}`, selectionStart, selectionEnd, "end");
    pane.els.editor.focus();
    const tab = pane.tabs[pane.active];
    if (tab) {
      tab.content = pane.els.editor.value;
      onEditorInput(pane);
      pane.els.editor.setSelectionRange(
        selectionStart + before.length,
        selectionStart + before.length + selected.length
      );
    }
  }

  function continueList(event) {
    const pane = focused();
    if (!pane) return;
    const editor = pane.els.editor;
    const { selectionStart, selectionEnd, value } = editor;
    if (selectionStart !== selectionEnd) return;
    const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
    const line = value.slice(lineStart, selectionStart);
    const match = line.match(/^(\s*)([-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$/);
    if (!match) return;
    event.preventDefault();
    const [, indent, marker, rest] = match;
    const isTask = /\[[ xX]\]/.test(line);
    if (!rest.trim()) {
      // empty item: end the list
      editor.setRangeText("\n", lineStart, selectionStart, "end");
    } else {
      let nextMarker = marker;
      if (/^\d/.test(marker)) {
        const number = parseInt(marker, 10) + 1;
        nextMarker = `${number}.`;
      }
      const insert = `\n${indent}${nextMarker} ${isTask ? "[ ] " : ""}`;
      editor.setRangeText(insert, selectionStart, selectionEnd, "end");
    }
    onEditorInput(pane);
  }

  function onEditorKey(event, pane) {
    const editor = pane.els.editor;
    if (event.key === "Tab") {
      event.preventDefault();
      const { selectionStart, selectionEnd, value } = editor;
      if (selectionStart !== selectionEnd && value.slice(selectionStart, selectionEnd).includes("\n")) {
        // indent / outdent every selected line
        const start = value.lastIndexOf("\n", selectionStart - 1) + 1;
        const block = value.slice(start, selectionEnd);
        const shifted = event.shiftKey ? block.replace(/^ {1,2}/gm, "") : block.replace(/^/gm, "  ");
        editor.setRangeText(shifted, start, selectionEnd, "end");
      } else {
        editor.setRangeText("  ", selectionStart, selectionEnd, "end");
      }
      onEditorInput(pane);
      return;
    }
    if (event.key === "Enter") {
      continueList(event);
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === "b") {
      event.preventDefault();
      wrapSelection("**", "**", "bold");
    } else if (mod && event.key.toLowerCase() === "i") {
      event.preventDefault();
      wrapSelection("*", "*", "italic");
    } else if (mod && event.key.toLowerCase() === "k") {
      event.preventDefault();
      wrapSelection("[", "](https://)", "link");
    }
  }

  function nextViewMode(pane) {
    const order = ["edit", "split", "read"];
    const current = (pane || focused() || { viewMode: "split" }).viewMode;
    return order[(order.indexOf(current) + 1) % order.length];
  }

  function setViewMode(paneOrMode, maybeMode, persist = true) {
    let pane = focused();
    let mode = paneOrMode;
    if (paneOrMode && paneOrMode.els) {
      pane = paneOrMode;
      mode = maybeMode;
    }
    if (!pane || !mode) return;
    pane.viewMode = mode;
    pane.els.body.className = `doc-body mode-${mode}`;
    $$("[data-role=view-toggle] button", pane.root).forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === mode);
    });
    if (persist) saveServerPrefs({ viewMode: mode });
  }

  // ---------------------------------------------------------------- split
  function setSplit(open, options = {}) {
    const want = Boolean(open);
    if (want === state.split) {
      showMode();
      return;
    }
    state.split = want;
    el.splitToggle.classList.toggle("is-active", want);
    el.splitToggle.setAttribute("aria-pressed", String(want));
    if (options.persist !== false) savePrefs({ splitOpen: want });

    const [first, second] = state.panes;
    if (!want) {
      if (state.focus === 1) setFocus(0, { silent: true });
      // Closing the second pane should never leave the app looking empty.
      if (second.tabs.length && !first.tabs.length) {
        first.tabs = second.tabs;
        first.active = second.active;
        second.tabs = [];
        second.active = -1;
        state.mode = "doc";
        activateTab(first, Math.max(0, Math.min(first.active, first.tabs.length - 1)), { focus: false });
      }
      renderTabs(second);
      renderPreview(second);
      renderPaneChrome(second);
    } else {
      renderPaneChrome(second);
      if (options.focus) setFocus(1);
    }
    showMode();
  }

  function toggleSplit() {
    setSplit(!state.split);
  }

  function openInOtherPane(path) {
    const target = otherPaneIndex();
    setSplit(true, { focus: false, persist: false });
    openNote(path, { pane: target, focus: false });
  }

  function setFocus(index, options = {}) {
    const pane = state.panes[index];
    if (!pane || state.focus === index) return;
    state.focus = index;
    state.panes.forEach((entry, i) => entry.root.classList.toggle("is-focused", i === index));
    if (options.silent) return;
    renderBreadcrumb(pane);
    updateOutline();
    refreshLinks();
    renderTreeActive();
    updateStatusBar();
    if (!pane.tabs.length) el.panelLinks.innerHTML = "";
  }

  function toggleSidebarForced(hidden) {
    const collapsed = hidden === undefined ? !el.sidebar.classList.contains("is-collapsed") : hidden;
    el.sidebar.classList.toggle("is-collapsed", collapsed);
    savePrefs({ sidebarCollapsed: collapsed });
  }

  function toggleRightPanel() {
    const hidden = !el.rightPanel.classList.contains("is-hidden");
    el.rightPanel.classList.toggle("is-hidden", hidden);
    savePrefs({ panelHidden: hidden });
  }

  // ----------------------------------------------------------------- modes
  function showMode() {
    const hasTabs = state.panes.some((pane) => pane.tabs.length);
    const isDoc = state.mode === "doc" && hasTabs;
    const isBook = state.mode === "book";
    const isGraph = state.mode === "graph";
    el.docView.hidden = !isDoc;
    el.splitToggle.disabled = !hasTabs;
    if (state.panes[1]) state.panes[1].root.hidden = !(isDoc && state.split);
    el.bookView.hidden = !isBook;
    el.graphView.hidden = !isGraph;
    el.welcomeView.hidden = !(state.mode === "welcome");
    el.rightPanel.classList.toggle("is-hidden", !isDoc || prefs.panelHidden);
    $$(".rail-btn").forEach((button) => {
      const tab = button.dataset.tab;
      button.classList.toggle(
        "is-active",
        (isGraph && tab === "graph") ||
          (!isGraph && tab === state.sidebarTab && tab !== "graph")
      );
    });
    if (isGraph) {
      requestAnimationFrame(() => {
        if (window.jadeliGraph) {
          window.jadeliGraph.resize();
        }
      });
    } else if (window.jadeliGraph) {
      window.jadeliGraph.stop();
    }
    updateStatusBar();
  }

  function showWelcome() {
    state.mode = "welcome";
    showMode();
  }

  function selectSidebarTab(tab, persist = true) {
    hideContextMenu();
    if (tab === "graph") {
      openGraph();
      state.sidebarTab = state.sidebarTab || "files";
      return;
    }
    if (state.mode === "graph") {
      state.mode = state.previousMode || (activeTab() ? "doc" : "welcome");
      showMode();
    }
    state.sidebarTab = tab;
    $$(".rail-btn").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === tab);
    });
    $$(".pane").forEach((pane) => {
      pane.classList.toggle("is-active", pane.dataset.pane === tab);
    });
    el.sidebar.classList.remove("is-collapsed");
    if (tab === "books") refreshBooks();
    if (tab === "tags") refreshTags();
    if (tab === "search") setTimeout(() => el.searchInput.focus(), 30);
    if (persist) saveServerPrefs({ sidebarTab: tab });
  }

  function setRightPanel(panel, persist = true) {
    state.rightPanel = panel;
    $$(".panel-tabs button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.panel === panel);
    });
    el.panelOutline.hidden = panel !== "outline";
    el.panelLinks.hidden = panel !== "links";
    if (persist) saveServerPrefs({ rightPanel: panel });
  }

  // --------------------------------------------------------------- themes
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.dataset.theme = theme;
    if (window.jadeliGraph) window.jadeliGraph.setTheme(theme);
  }

  function toggleTheme() {
    const theme = state.theme === "dark" ? "light" : "dark";
    applyTheme(theme);
    saveServerPrefs({ theme });
  }

  // -------------------------------------------------------------- statusbar
  function updateStatusBar() {
    const tab = activeTab();
    if (state.mode === "book" && state.book) {
      el.statusLeft.textContent = `${state.book.chapter_count} chapters · ${state.book.words.toLocaleString()} words`;
      el.statusRight.innerHTML = `<span>${esc(state.book.title)}</span>`;
      return;
    }
    if (state.mode === "graph" && state.graphData) {
      el.statusLeft.textContent = `${state.graphData.nodes.length} notes · ${state.graphData.edges.length} links in the graph`;
      el.statusRight.innerHTML = `<span>${esc(state.vaultName)}</span>`;
      return;
    }
    if (!tab) {
      el.statusLeft.textContent = state.split ? "No note in this pane" : "No note open";
      el.statusRight.innerHTML = `<span>${esc(state.vaultName)}</span>`;
      return;
    }
    const words = JadeliMD.countWords(tab.content);
    const chars = tab.content.length;
    el.statusLeft.textContent = `${words.toLocaleString()} words · ${chars.toLocaleString()} chars`;
    const dirty = tab.content !== tab.saved;
    const saved = state.lastSavedAt
      ? `Saved ${state.lastSavedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : "Saved";
    el.statusRight.innerHTML = `<span>${esc(tab.path)}</span><span class="${dirty ? "is-dirty" : ""}">${
      dirty ? (state.saving ? "Saving…" : "Unsaved changes") : saved
    }</span>`;
  }

  // ---------------------------------------------------------------- search
  let searchTimer = null;
  function onSearchInput() {
    clearTimeout(searchTimer);
    const query = el.searchInput.value.trim();
    if (!query) {
      el.searchResults.innerHTML = '<p class="muted small pad">Type to search across every note in the vault.</p>';
      return;
    }
    searchTimer = setTimeout(async () => {
      try {
        const data = await api("search", { query });
        renderSearchResults(data.results || [], query);
      } catch (error) {
        el.searchResults.innerHTML = `<p class="muted small pad">${esc(error.message)}</p>`;
      }
    }, 170);
  }

  function markMatches(text, query) {
    const safe = esc(text);
    const terms = query.split(/\s+/).filter((term) => term.length > 1);
    let output = safe;
    terms.forEach((term) => {
      const pattern = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
      output = output.replace(pattern, "<mark>$1</mark>");
    });
    return output;
  }

  function renderSearchResults(results, query) {
    if (!results.length) {
      el.searchResults.innerHTML = `<p class="muted small pad">Nothing found for “${esc(query)}”.</p>`;
      return;
    }
    el.searchResults.innerHTML = results
      .map(
        (result) => `
        <button class="search-result" data-open="${esc(result.path)}">
          <div class="sr-title">${markMatches(result.title, query)}</div>
          <div class="sr-path">${esc(result.path)}</div>
          <div class="sr-snippet">${markMatches(result.snippet || "", query)}</div>
        </button>`
      )
      .join("");
  }

  // ------------------------------------------------------------------ tags
  async function refreshTags() {
    try {
      const data = await api("tags");
      const tags = data.tags || [];
      if (!tags.length) {
        el.tagList.innerHTML = '<p class="muted small pad">No #tags yet. Add one anywhere in a note.</p>';
        return;
      }
      el.tagList.innerHTML = tags
        .map(
          (tag) =>
            `<button class="tree-row" data-tag="${esc(tag.tag)}"><span class="caret"></span><span class="label">#${esc(tag.tag)}</span><span class="count">${tag.count}</span></button>`
        )
        .join("");
    } catch (error) {
      el.tagList.innerHTML = `<p class="muted small pad">${esc(error.message)}</p>`;
    }
  }

  let tagsTimer = null;
  function refreshTagsSoon() {
    clearTimeout(tagsTimer);
    tagsTimer = setTimeout(() => {
      if (state.sidebarTab === "tags") refreshTags();
    }, 1500);
  }

  // ----------------------------------------------------------------- books
  async function refreshBooks() {
    try {
      const data = await api("books_list");
      state.books = data.books || [];
      renderBookList();
    } catch (error) {
      el.bookList.innerHTML = `<p class="muted small pad">${esc(error.message)}</p>`;
    }
  }

  function renderBookList() {
    if (!state.books.length) {
      el.bookList.innerHTML =
        '<p class="muted small pad">No books yet.<br><br>Create one to collect chapters into an ordered manuscript.</p>';
      return;
    }
    el.bookList.innerHTML = state.books
      .map(
        (book) => `
        <div class="book-card${book.id === state.bookId ? " is-active" : ""}" data-book="${esc(book.id)}">
          <div class="bc-title">${esc(book.title)}</div>
          <div class="bc-meta">${book.chapter_count} chapter${book.chapter_count === 1 ? "" : "s"} · ${book.words.toLocaleString()} words${book.target_words ? ` · ${book.progress}% of ${book.target_words.toLocaleString()}` : ""}</div>
          <div class="progress"><span style="width:${book.target_words ? Math.min(book.progress, 100) : 0}%"></span></div>
        </div>`
      )
      .join("");
  }

  async function openBook(bookId) {
    try {
      const data = await api("book_get", { bookId });
      state.book = data.book;
      state.bookId = bookId;
      state.mode = "book";
      state.sidebarTab = "books";
      selectSidebarTab("books", false);
      showMode();
      renderBookView();
      renderBookList();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderBookView() {
    const book = state.book;
    if (!book) {
      el.bookView.innerHTML = "";
      return;
    }
    const remaining = Math.max((book.target_words || 0) - book.words, 0);
    const rows = book.chapters.length
      ? book.chapters
          .map(
            (chapter) => `
        <div class="chapter-row${chapter.missing ? " is-missing" : ""}" data-chapter="${esc(chapter.path)}">
          <div class="chapter-index">${String(chapter.position + 1).padStart(2, "0")}</div>
          <div class="chapter-main" data-act="open">
            <div class="chapter-title">${esc(chapter.title)}</div>
            <div class="chapter-meta">${chapter.missing ? "File missing" : `${chapter.words.toLocaleString()} words`} · ${esc(chapter.path)}</div>
          </div>
          <div class="chapter-actions">
            <button class="icon-btn sm" data-act="up" title="Move up">
              <svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
            </button>
            <button class="icon-btn sm" data-act="down" title="Move down">
              <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
            </button>
            <button class="icon-btn sm" data-act="remove" title="Remove from book">
              <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
            </button>
          </div>
        </div>`
          )
          .join("")
      : '<div class="chapter-empty">No chapters yet. Add the first one to start the manuscript.</div>';

    el.bookView.innerHTML = `
      <div class="book-sheet">
        <div class="book-top">
          <div>
            <h1 class="book-title">${esc(book.title)}</h1>
            <p class="book-desc">${esc(book.description || "No description yet.")}</p>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn sm" data-book-act="edit">Edit</button>
            <button class="btn sm" data-book-act="export">Export</button>
            <button class="btn sm danger" data-book-act="delete">Delete</button>
          </div>
        </div>
        <div class="book-stats">
          <div class="stat"><div class="stat-value">${book.chapter_count}</div><div class="stat-label">Chapters</div></div>
          <div class="stat"><div class="stat-value">${book.words.toLocaleString()}</div><div class="stat-label">Words written</div></div>
          <div class="stat"><div class="stat-value">${(book.target_words || 0).toLocaleString()}</div><div class="stat-label">Word target</div></div>
          <div class="stat"><div class="stat-value">${remaining.toLocaleString()}</div><div class="stat-label">Words to go</div></div>
        </div>
        ${
          book.target_words
            ? `<div class="book-progress"><div class="progress"><span style="width:${Math.min(book.progress, 100)}%"></span></div>
               <div class="bp-label"><span>${book.progress}% of target</span><span>${(book.target_words - book.words > 0 ? remaining : 0).toLocaleString()} words left</span></div></div>`
            : ""
        }
        <div class="chapter-head">
          <h2>Chapters</h2>
          <div style="display:flex;gap:6px">
            <button class="btn sm" data-book-act="attach">Attach note</button>
            <button class="btn sm primary" data-book-act="add-chapter">+ Chapter</button>
          </div>
        </div>
        <div class="chapter-list">${rows}</div>
        <p class="muted small" style="margin-top:22px">Chapters are ordinary notes in <code>${esc(book.folder || "Books")}</code> — rename, move or link them like any other note.</p>
      </div>`;

    el.bookView.onclick = async (event) => {
      const action = event.target.closest("[data-book-act]")?.dataset.bookAct;
      if (action) {
        event.preventDefault();
        if (action === "edit") return editBookFlow();
        if (action === "export") return exportBookFlow();
        if (action === "delete") return deleteBookFlow();
        if (action === "add-chapter") return addChapterFlow();
        if (action === "attach") return attachChapterFlow();
      }
      const chapterRow = event.target.closest("[data-chapter]");
      if (!chapterRow) return;
      const chapterPath = chapterRow.dataset.chapter;
      const chapterAction = event.target.closest("[data-act]")?.dataset.act;
      if (chapterAction === "open") return openNote(chapterPath);
      if (chapterAction === "up") return moveChapter(chapterPath, -1);
      if (chapterAction === "down") return moveChapter(chapterPath, 1);
      if (chapterAction === "remove") return removeChapterFlow(chapterPath);
    };
  }

  function applyRenamedPaths(renamed) {
    if (!renamed) return;
    state.panes.forEach((pane) => {
      let changed = false;
      pane.tabs.forEach((tab) => {
        if (!renamed[tab.path]) return;
        tab.path = renamed[tab.path];
        changed = true;
      });
      if (!changed) return;
      renderTabs(pane);
      renderBreadcrumb(pane);
    });
    updateStatusBar();
    refreshLinks();
    renderTreeActive();
  }

  async function moveChapter(path, direction) {
    try {
      const data = await api("book_move_chapter", { bookId: state.bookId, path, direction });
      state.book = data.book;
      applyRenamedPaths(data.renamed);
      renderBookView();
      await refreshTree();
      refreshBooks();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function removeChapterFlow(path) {
    const chapter = (state.book?.chapters || []).find((entry) => entry.path === path);
    const confirmed = await confirmDialog(
      "Remove chapter from book",
      `“${chapter ? chapter.title : path}” will be removed from this manuscript. The note itself stays in your vault.`,
      "Remove chapter"
    );
    if (!confirmed) return;
    try {
      const data = await api("book_remove_chapter", { bookId: state.bookId, path });
      state.book = data.book;
      renderBookView();
      refreshBooks();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function addChapterFlow() {
    const values = await openDialog({
      title: "New chapter",
      fields: [
        { name: "title", label: "Chapter title", value: "", placeholder: "Chapter Two" },
      ],
      confirmLabel: "Create chapter",
    });
    if (!values || !values.title.trim()) return;
    try {
      const data = await api("book_add_chapter", { bookId: state.bookId, title: values.title.trim() });
      state.book = data.book;
      renderBookView();
      refreshBooks();
      await refreshTree();
      const added = data.book.chapters[data.book.chapters.length - 1];
      if (added) await openNote(added.path);
      toast("Chapter created");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function editBookFlow() {
    const book = state.book;
    if (!book) return;
    const values = await openDialog({
      title: "Edit book",
      fields: [
        { name: "title", label: "Title", value: book.title },
        { name: "description", label: "Description", type: "textarea", value: book.description },
        { name: "target_words", label: "Word target", type: "number", value: book.target_words || 0 },
      ],
      confirmLabel: "Save",
    });
    if (!values) return;
    try {
      const data = await api("book_update", {
        bookId: book.id,
        patch: {
          title: values.title,
          description: values.description,
          target_words: values.target_words,
        },
      });
      state.book = data.book;
      renderBookView();
      refreshBooks();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteBookFlow() {
    const book = state.book;
    if (!book) return;
    const confirmed = await confirmDialog(
      "Delete book",
      `Remove “${book.title}” from jadeli? Chapter notes stay on disk under ${book.folder}.`,
      "Delete book"
    );
    if (!confirmed) return;
    try {
      await api("book_delete", { bookId: book.id });
      state.book = null;
      state.bookId = null;
      await refreshBooks();
      showWelcome();
      toast("Book removed (chapter files kept)");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function refreshTitlesSoon() {
    clearTimeout(state.titlesTimer);
    state.titlesTimer = setTimeout(() => {
      refreshTitles().catch(() => {});
    }, 1200);
  }

  async function newBookFlow() {
    const values = await openDialog({
      title: "New book",
      fields: [
        { name: "title", label: "Book title", placeholder: "The Lantern's Edge" },
        { name: "description", label: "What is it about?", type: "textarea", rows: 2 },
        { name: "target_words", label: "Word target", type: "number", value: 50000, hint: "A novel is roughly 70,000–90,000 words." },
        { name: "chapter_title", label: "First chapter", value: "Chapter One" },
      ],
      confirmLabel: "Create book",
    });
    if (!values || !values.title.trim()) return;
    try {
      const data = await api("book_create", {
        title: values.title.trim(),
        description: values.description || "",
        target_words: values.target_words || 0,
        chapter_title: values.chapter_title || "Chapter One",
      });
      await refreshBooks();
      await refreshTree();
      await openBook(data.book.id);
      toast("Book created");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // --------------------------------------------------------------- exports
  function safeName(text) {
    return String(text || "export").replace(FILENAME_RE, "").replace(/\s+/g, " ").trim() || "export";
  }

  function manuscriptMarkdown(manuscript) {
    const { book, chapters } = manuscript;
    const head = [`# ${book.title}`];
    if (book.description) head.push(`> ${book.description}`);
    const parts = chapters.map((chapter) => {
      const content = (chapter.content || "").trim();
      return content.startsWith("#") ? content : `# ${chapter.title}\n\n${content}`;
    });
    return `${[head.join("\n\n"), ...parts].join("\n\n---\n\n")}\n`;
  }

  function manuscriptHtml(manuscript) {
    const { book, chapters } = manuscript;
    const rendered = chapters
      .map((chapter) => {
        const content = (chapter.content || "").trim();
        const body = content.startsWith("#") ? content : `# ${chapter.title}\n\n${content}`;
        return `<section class="chapter">${JadeliMD.render(body, {})}</section>`;
      })
      .join("\n");
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${esc(book.title)}</title>
<style>
  :root { color-scheme: light; }
  body {
    margin: 0 auto; max-width: 44rem; padding: 3rem 1.5rem 6rem;
    font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
    font-size: 17px; line-height: 1.75; color: #1b1d24; background: #fffdf9;
  }
  .title-page { text-align: center; padding: 4rem 0 3rem; }
  .title-page h1 { font-size: 2.4rem; margin: 0 0 0.4rem; letter-spacing: -0.01em; }
  .title-page p { color: #5d6070; font-style: italic; margin: 0; }
  h1, h2, h3, h4 { font-family: "Inter", "Segoe UI", system-ui, sans-serif; line-height: 1.25; margin: 2em 0 0.6em; }
  h1 { font-size: 1.7rem; margin-top: 0; }
  h2 { font-size: 1.3rem; }
  p { margin: 0.9em 0; }
  blockquote { margin: 1em 0; padding-left: 1em; border-left: 3px solid #cbc6bd; color: #4a4d59; }
  pre { background: #f4f2ee; padding: 1em; overflow: auto; border-radius: 6px; }
  code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 0.88em; }
  .chapter { break-before: page; }
  .chapter:first-of-type { break-before: auto; }
  .wikilink, .tag { color: inherit; text-decoration: none; }
  .tag { display: none; }
  hr { border: 0; border-top: 1px solid #ddd; margin: 2em 0; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 0.4em 0.6em; }
  @media print {
    body { padding: 0; max-width: none; background: #fff; }
    .chapter { break-before: page; }
  }
</style>
</head>
<body>
  <header class="title-page">
    <h1>${esc(book.title)}</h1>
    <p>${esc(book.description || "")}</p>
  </header>
  ${rendered}
</body>
</html>
`;
  }

  async function exportBookFlow() {
    if (!state.book) return;
    const values = await openDialog({
      title: "Export manuscript",
      bodyHtml: `<p class="muted" style="margin:0 0 14px;line-height:1.6">Chapters are combined in their current order and saved into the vault's <code>Exports</code> folder.</p>`,
      fields: [
        {
          name: "format",
          label: "Format",
          type: "select",
          value: "md",
          options: [
            { value: "md", label: "Markdown — one combined .md file" },
            { value: "html", label: "HTML — print-ready, open in a browser to save as PDF" },
          ],
        },
      ],
      confirmLabel: "Export",
    });
    if (!values) return;
    try {
      const manuscript = await api("book_manuscript", { bookId: state.book.id });
      const format = values.format;
      const name = `${safeName(manuscript.book.title)}.${format}`;
      const text = format === "html" ? manuscriptHtml(manuscript) : manuscriptMarkdown(manuscript);
      const result = await api("export_write", { name, text });
      const reveal = await confirmDialog(
        "Export ready",
        `${result.path} — ${(text.length / 1024).toFixed(1)} KB\n\nOpen the Exports folder?`,
        "Open folder",
        false
      );
      if (reveal) await api("reveal", { path: result.path });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ----------------------------------------------------------- new/rename
  async function currentFolder() {
    const tab = activeTab();
    if (!tab) return "";
    const parts = tab.path.split("/");
    parts.pop();
    return parts.join("/");
  }

  async function newNoteFlow() {
    const folder = await currentFolder();
    const values = await openDialog({
      title: "New note",
      fields: [
        { name: "title", label: "Note title", placeholder: "Chapter idea" },
        { name: "folder", label: "Folder", value: folder, hint: "Leave empty for the vault root." },
      ],
      confirmLabel: "Create note",
    });
    if (!values || !values.title.trim()) return;
    const title = values.title.trim();
    const path = [values.folder.trim().replace(/^\/+|\/+$/g, ""), `${title}.md`]
      .filter(Boolean)
      .join("/");
    try {
      const note = await api("create_note", { path, content: `# ${title}\n\n` });
      await refreshTree();
      await openNote(note.path);
      toast("Note created");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function newFolderFlow() {
    const folder = await currentFolder();
    const values = await openDialog({
      title: "New folder",
      fields: [
        { name: "name", label: "Folder name", placeholder: "Research" },
        { name: "parent", label: "Inside", value: folder },
      ],
      confirmLabel: "Create folder",
    });
    if (!values || !values.name.trim()) return;
    const path = [values.parent.trim().replace(/^\/+|\/+$/g, ""), values.name.trim()]
      .filter(Boolean)
      .join("/");
    try {
      await api("create_folder", { path });
      openFolders.add(values.parent.trim());
      await refreshTree();
      toast("Folder created");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function renameFlow(path) {
    const current = path.split("/").pop().replace(/\.md$/i, "");
    const values = await openDialog({
      title: "Rename",
      fields: [{ name: "name", label: "New name", value: current }],
      confirmLabel: "Rename",
    });
    if (!values || !values.name.trim() || values.name.trim() === current) return;
    try {
      const result = await api("rename", { path, name: values.name.trim() });
      state.panes.forEach((pane) => {
        let changed = false;
        pane.tabs.forEach((tab) => {
          if (tab.path !== path) return;
          tab.path = result.path;
          changed = true;
        });
        if (!changed) return;
        renderTabs(pane);
        renderBreadcrumb(pane);
      });
      await refreshTree();
      updateStatusBar();
      toast("Renamed");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function duplicateNote(path) {
    try {
      const note = await api("read_note", { path });
      const name = path.replace(/\.(md|markdown|txt)$/i, " copy$&");
      const copy = await api("create_note", { path: name, content: note.content });
      await refreshTree();
      await openNote(copy.path);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteFlow(path) {
    const name = path.split("/").pop();
    const confirmed = await confirmDialog(
      "Delete note",
      `${name} will be moved to the vault's .jadeli/trash folder, so you can still recover it.`,
      "Delete",
      true
    );
    if (!confirmed) return;
    try {
      await api("delete_note", { path });
      for (const pane of state.panes) {
        pane.tabs = pane.tabs.filter((tab) => tab.path !== path);
        if (!pane.tabs.length) {
          pane.active = -1;
          pane.els.editor.value = "";
          renderTabs(pane);
          renderBreadcrumb(pane);
          renderPreview(pane);
          renderPaneChrome(pane);
          continue;
        }
        pane.active = Math.max(0, Math.min(pane.active, pane.tabs.length - 1));
        await activateTab(pane, pane.active, { focus: false });
      }
      if (!state.panes.some((pane) => pane.tabs.length)) {
        state.mode = "welcome";
        showMode();
      } else if (!focused().tabs.length) {
        updateOutline();
        el.panelLinks.innerHTML = "";
      }
      updateStatusBar();
      await refreshTree();
      toast("Moved to trash");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // --------------------------------------------------------- quick switch
  function fuzzyScore(text, query) {
    const haystack = text.toLowerCase();
    const needle = query.toLowerCase();
    if (!needle) return 1;
    if (haystack.includes(needle)) return 100 - haystack.indexOf(needle);
    let score = 0;
    let position = 0;
    for (const char of needle) {
      const found = haystack.indexOf(char, position);
      if (found === -1) return 0;
      score += 10 - Math.min(9, found - position);
      position = found + 1;
    }
    return Math.max(1, score);
  }

  function openNotePicker(options = {}) {
    const {
      title = "Jump to a note",
      placeholder = "Search notes…",
      exclude = [],
    } = options;
    const excluded = new Set(exclude);
    const pool = state.titles.filter((note) => !excluded.has(note.path));
    const root = el.modalRoot;
    root.hidden = false;
    let filtered = [];
    let cursor = 0;
    let settled = false;

    root.innerHTML = `
      <div class="modal">
        <div class="modal-header">${esc(title)}</div>
        <div class="modal-body" style="padding-bottom:8px">
          <input type="text" id="picker-input" placeholder="${esc(placeholder)}" autocomplete="off">
        </div>
        <div class="quick-list" id="picker-list"></div>
      </div>`;

    const input = $("#picker-input");
    const list = $("#picker-list");

    return new Promise((resolve) => {
      const close = (value) => {
        if (settled) return;
        settled = true;
        root.hidden = true;
        root.innerHTML = "";
        document.removeEventListener("keydown", onKey, true);
        resolve(value);
      };

      const renderList = () => {
        if (!filtered.length) {
          list.innerHTML = '<p class="muted small pad">No matching notes.</p>';
          return;
        }
        list.innerHTML = filtered
          .slice(0, 40)
          .map(
            (note, index) =>
              `<button class="quick-item${index === cursor ? " is-active" : ""}" data-index="${index}">
                 <span>${esc(note.title)}</span><span class="qi-path">${esc(note.path)}</span>
               </button>`
          )
          .join("");
      };

      const update = () => {
        const query = input.value.trim();
        filtered = pool
          .map((note) => ({
            ...note,
            score: Math.max(fuzzyScore(note.title, query), fuzzyScore(note.path, query) * 0.6),
          }))
          .filter((note) => note.score > 0)
          .sort((a, b) => b.score - a.score);
        cursor = 0;
        renderList();
      };

      const choose = (index) => {
        const note = filtered[index];
        if (!note) return;
        close(note.path);
      };

      function onKey(event) {
        if (event.key === "Escape") {
          event.preventDefault();
          close(null);
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          cursor = Math.min(cursor + 1, Math.min(filtered.length, 40) - 1);
          renderList();
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          cursor = Math.max(cursor - 1, 0);
          renderList();
        } else if (event.key === "Enter") {
          event.preventDefault();
          choose(cursor);
        }
      }

      input.addEventListener("input", update);
      list.addEventListener("click", (event) => {
        const button = event.target.closest(".quick-item");
        if (button) choose(Number(button.dataset.index));
      });
      root.onclick = (event) => {
        if (event.target === root) close(null);
      };
      document.addEventListener("keydown", onKey, true);
      update();
      input.focus();
    });
  }

  async function openQuickSwitch() {
    const path = await openNotePicker({ title: "Jump to a note", placeholder: "Jump to a note…" });
    if (path) openNote(path);
  }

  async function attachChapterFlow() {
    if (!state.bookId) return;
    const inBook = (state.book?.chapters || []).map((chapter) => chapter.path);
    const path = await openNotePicker({
      title: "Attach an existing note as a chapter",
      placeholder: "Find a note…",
      exclude: inBook,
    });
    if (!path) return;
    try {
      const data = await api("book_attach_chapter", { bookId: state.bookId, path });
      state.book = data.book;
      state.mode = "book";
      showMode();
      renderBookView();
      refreshBooks();
      toast("Chapter attached");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ----------------------------------------------------------------- graph
  async function openGraph() {
    if (state.mode !== "graph") state.previousMode = state.mode;
    state.mode = "graph";
    if (!window.jadeliGraph) {
      window.jadeliGraph = new JadeliGraph($("#graph-canvas"), { onOpen: openNote });
    }
    showMode();
    window.jadeliGraph.resize();
    window.jadeliGraph.setTheme(state.theme);
    try {
      const data = await api("graph");
      state.graphData = data;
      window.jadeliGraph.setData(data, activeTab() ? activeTab().path : "");
      window.jadeliGraph.start();
      $("#graph-stats").textContent = `${data.nodes.length} notes · ${data.edges.length} links`;
      updateStatusBar();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ------------------------------------------------------------ vault flow
  async function switchVaultFlow() {
    try {
      const result = await api("pick_vault");
      if (result && result.cancelled) return;
      await reopenAfterVaultChange();
    } catch (error) {
      const values = await openDialog({
        title: "Open another vault",
        bodyHtml:
          '<p class="muted" style="margin:0 0 14px;line-height:1.6">The folder picker needs the desktop window. You can paste an absolute folder path instead.</p>',
        fields: [{ name: "path", label: "Vault folder", placeholder: "C:\\Users\\you\\Documents\\My vault" }],
        confirmLabel: "Open vault",
      });
      if (!values || !values.path.trim()) return;
      try {
        await api("open_vault", { path: values.path.trim() });
        await reopenAfterVaultChange();
      } catch (innerError) {
        toast(innerError.message, "error");
      }
    }
  }

  async function reopenAfterVaultChange() {
    state.panes.forEach((pane) => {
      pane.tabs = [];
      pane.active = -1;
      pane.els.editor.value = "";
      pane.els.preview.innerHTML = "";
      renderTabs(pane);
      renderBreadcrumb(pane);
      renderPaneChrome(pane);
    });
    state.book = null;
    state.bookId = null;
    const data = await api("state");
    state.vaultPath = data.vault;
    state.vaultName = data.vaultName;
    el.vaultName.textContent = state.vaultName;
    await refreshTree();
    await refreshBooks();
    showWelcome();
    toast(`Vault: ${state.vaultName}`);
  }

  // ----------------------------------------------------------------- bind
  function cacheElements() {
    el.toast = $("#toast");
    el.modalRoot = $("#modal-root");
    el.sidebar = $("#sidebar");
    el.vaultName = $("#vault-name");
    el.fileTree = $("#file-tree");
    el.docView = $("#doc-view");
    el.splitToggle = $("#btn-split");
    el.bookView = $("#book-view");
    el.graphView = $("#graph-view");
    el.welcomeView = $("#welcome-view");
    el.statusLeft = $("#status-left");
    el.statusRight = $("#status-right");
    el.rightPanel = $("#right-panel");
    el.panelOutline = $("#panel-outline");
    el.panelLinks = $("#panel-links");
    el.searchInput = $("#search-input");
    el.searchResults = $("#search-results");
    el.bookList = $("#book-list");
    el.tagList = $("#tag-list");

    state.panes = $$(".doc-pane").map((root, index) => ({
      index,
      root,
      tabs: [],
      active: -1,
      viewMode: "split",
      saveTimer: null,
      previewTimer: null,
      els: {
        tabs: $(".tabs", root),
        bar: $(".doc-bar", root),
        body: $(".doc-body", root),
        breadcrumb: $(".breadcrumb", root),
        editor: $(".editor", root),
        preview: $(".preview", root),
        toggle: $("[data-role=view-toggle]", root),
        empty: $(".pane-empty", root),
      },
    }));

    el.splitToggle.setAttribute("aria-pressed", "false");
    state.panes.forEach((pane) => {
      pane.root.classList.toggle("is-focused", pane.index === 0);
      pane.els.body.className = `doc-body mode-${pane.viewMode}`;
      renderPaneChrome(pane);
    });
  }

  function bindPane(pane) {
    const { editor, preview } = pane.els;

    // Clicking anywhere inside a pane makes it the pane that new notes open in
    // and the one whose outline and backlinks the right panel shows.
    pane.root.addEventListener(
      "pointerdown",
      () => {
        if (state.focus !== pane.index) setFocus(pane.index);
      },
      true
    );

    $$("[data-role=view-toggle] button", pane.root).forEach((button) => {
      button.addEventListener("click", () => {
        setFocus(pane.index);
        setViewMode(pane, button.dataset.view);
      });
    });

    $("[data-role=toggle-panel]", pane.root).addEventListener("click", () => {
      toggleRightPanel();
      showMode();
    });

    $("[data-role=open-other]", pane.root).addEventListener("click", () => {
      const tab = pane.tabs[pane.active];
      if (tab) openInOtherPane(tab.path);
      else setSplit(true, { focus: true });
    });

    const closePane = $("[data-role=close-pane]", pane.root);
    if (closePane) closePane.addEventListener("click", () => setSplit(false));

    const pick = $("[data-role=pe-pick]", pane.root);
    if (pick) {
      pick.addEventListener("click", async () => {
        setFocus(pane.index);
        const path = await openNotePicker({
          title: "Open a note in this pane",
          placeholder: "Find a note…",
        });
        if (path) openNote(path, { pane: pane.index, focus: false });
      });
    }

    const closeEmpty = $("[data-role=pe-close]", pane.root);
    if (closeEmpty) closeEmpty.addEventListener("click", () => setSplit(false));

    bindPreview(preview, pane);

    editor.addEventListener("input", () => onEditorInput(pane));
    editor.addEventListener("focus", () => setFocus(pane.index));
    editor.addEventListener("keydown", (event) => onEditorKey(event, pane));
  }

  function bindEvents() {
    // If the user starts clicking while startup is still loading, do not let
    // the saved session yank the view back later.
    document.addEventListener(
      "pointerdown",
      () => {
        state.userActed = true;
      },
      true
    );
    $("#btn-sidebar").addEventListener("click", () => toggleSidebarForced());
    $("#btn-theme").addEventListener("click", toggleTheme);
    $("#btn-new-note").addEventListener("click", newNoteFlow);
    $("#btn-new-note-2").addEventListener("click", newNoteFlow);
    $("#btn-new-folder").addEventListener("click", newFolderFlow);
    $("#btn-new-book").addEventListener("click", newBookFlow);
    $("#btn-quick").addEventListener("click", openQuickSwitch);
    $("#vault-chip").addEventListener("click", switchVaultFlow);
    $("#btn-split").addEventListener("click", toggleSplit);
    state.panes.forEach(bindPane);

    $$(".rail-btn").forEach((button) => {
      button.addEventListener("click", () => selectSidebarTab(button.dataset.tab));
    });
    $$(".panel-tabs button").forEach((button) => {
      button.addEventListener("click", () => setRightPanel(button.dataset.panel));
    });

    document.addEventListener("click", async (event) => {
      const openTarget = event.target.closest("[data-open]");
      if (openTarget) {
        event.preventDefault();
        const path = openTarget.dataset.open;
        if (path) return openNote(path);
        if (openTarget.dataset.create) {
          const target = openTarget.dataset.create;
          const folder = await currentFolder();
          const created = await api("create_note", {
            path: [folder, `${target}.md`].filter(Boolean).join("/"),
            content: `# ${target}\n\n`,
          });
          await refreshTree();
          return openNote(created.path);
        }
      }
      const tagTarget = event.target.closest("[data-tag]");
      if (tagTarget) {
        event.preventDefault();
        selectSidebarTab("search");
        el.searchInput.value = `#${tagTarget.dataset.tag}`;
        onSearchInput();
        return;
      }
      const bookTarget = event.target.closest("[data-book]");
      if (bookTarget) {
        event.preventDefault();
        return openBook(bookTarget.dataset.book);
      }
    });

    // wiki links, tags and external links are wired per pane in bindPane()

    el.searchInput.addEventListener("input", onSearchInput);

    document.addEventListener("keydown", (event) => {
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (mod && (key === "o" || (key === "p" && !event.shiftKey))) {
        event.preventDefault();
        openQuickSwitch();
      } else if (mod && key === "n" && !event.shiftKey) {
        event.preventDefault();
        newNoteFlow();
      } else if (mod && key === "s") {
        event.preventDefault();
        saveActive(true).then(() => toast("Saved"));
      } else if (mod && event.shiftKey && key === "f") {
        event.preventDefault();
        selectSidebarTab("search");
      } else if (mod && key === "e") {
        event.preventDefault();
        setViewMode(focused(), nextViewMode());
      } else if (mod && key === "w") {
        event.preventDefault();
        const current = focused();
        if (current && current.active >= 0) closeTab(current, current.active);
      } else if (mod && (event.key === "\\" || event.key === "|")) {
        event.preventDefault();
        if (event.shiftKey || event.key === "|") toggleSplit();
        else toggleSidebarForced();
      } else if (key === "escape") {
        hideContextMenu();
      }
    });

    window.addEventListener("resize", () => {
      if (state.mode === "graph" && window.jadeliGraph) window.jadeliGraph.resize();
    });

    window.addEventListener("beforeunload", () => {
      state.panes.forEach((pane) => {
        pane.tabs.forEach((tab) => {
          if (tab.content === tab.saved) return;
          try {
            navigator.sendBeacon(
              "/api/write_note",
              new Blob([JSON.stringify({ path: tab.path, content: tab.content })], {
                type: "application/json",
              })
            );
          } catch (error) {
            /* best effort */
          }
        });
      });
    });

    $("#btn-welcome-new").addEventListener("click", newNoteFlow);
    $("#btn-welcome-book").addEventListener("click", newBookFlow);
    $("#btn-welcome-search").addEventListener("click", () => selectSidebarTab("search"));
    $("#btn-graph-refresh").addEventListener("click", () => openGraph());
    $("#btn-graph-fit").addEventListener("click", () => {
      if (window.jadeliGraph) {
        window.jadeliGraph.fit();
        window.jadeliGraph.draw();
      }
    });
  }

  function renderBreadcrumb(pane) {
    const target = pane || focused();
    if (!target) return;
    const tab = target.tabs[target.active];
    if (!tab) {
      target.els.breadcrumb.innerHTML = "";
      return;
    }
    const parts = tab.path.split("/");
    const filename = parts.pop();
    target.els.breadcrumb.innerHTML =
      parts.map((part) => `<span>${esc(part)}</span><span class="sep">/</span>`).join("") +
      `<span>${esc(filename)}</span>`;
  }

  // -------------------------------------------------------------- bootstrap
  async function init() {
    cacheElements();
    bindEvents();

    try {
      const data = await api("state");
      state.vaultPath = data.vault;
      state.vaultName = data.vaultName;
      state.theme = data.theme || "dark";
      el.vaultName.textContent = state.vaultName;
      applyTheme(state.theme);
      state.panes.forEach((pane) => setViewMode(pane, data.viewMode || "split", false));
      if (prefs.splitOpen) setSplit(true, { persist: false, focus: false });
      if (prefs.sidebarCollapsed) toggleSidebarForced(true);
      el.rightPanel.classList.toggle("is-hidden", Boolean(prefs.panelHidden));
      state.rightPanel = data.rightPanel || "outline";
      setRightPanel(state.rightPanel, false);

      await refreshTree();
      await refreshBooks();
      if (!state.userActed) selectSidebarTab(data.sidebarTab || "files", false);

      if (
        !state.userActed &&
        data.lastNote &&
        state.stemMap.has(data.lastNote.replace(/\.md$/i, "").toLowerCase())
      ) {
        await openNote(data.lastNote, { focus: false });
      } else if (!state.userActed) {
        showWelcome();
      }
      state.ready = true;
      updateStatusBar();
    } catch (error) {
      el.welcomeView.innerHTML = `<div class="welcome-inner"><h1>jadeli could not start</h1><p class="muted">${esc(error.message)}</p></div>`;
      toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
