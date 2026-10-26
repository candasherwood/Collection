/* JADELY launcher — the hub page.
 *
 * Shows every app with its live status, starts and stops windows, and reports
 * what is in the library. Status is re-read every few seconds while the window
 * is visible, so a window you closed elsewhere falls out of the list on its own.
 */
(function () {
  "use strict";

  const J = window.Jadely;
  const POLL_MS = 4000;
  let state = null;
  let polling = 0;

  const $ = (id) => document.getElementById(id);

  // -------------------------------------------------------------- rendering
  function renderSummary() {
    const launch = state;
    const library = launch.library || { kinds: {}, items: 0 };
    const kinds = library.kinds || {};
    const bits = ["note", "audio", "pdf", "document", "image"]
      .filter((kind) => kinds[kind])
      .map((kind) => (kinds[kind] || 0) + " " + J.kindLabel(kind).toLowerCase());
    $("summary").innerHTML = [
      card("Apps running", String(launch.running || 0), "of " + (launch.apps || []).length + " available"),
      card("Library", String(library.items || 0), bits.join(" · ") || "nothing yet"),
      card("Words", String(library.words || 0), (library.programs || 0) + " programs"),
      card("Audio", library.durationLabel || "0:00", "ready to play"),
      card("Size", library.sizeLabel || "0 B", "on disk, yours"),
      card("PDF engine", (launch.engine && launch.engine.resolved) === "edge" ? "Browser" : "Built-in", (launch.engine && launch.engine.browserName) || "stdlib writer"),
    ].join("");
  }

  function card(key, value, sub) {
    return (
      '<div class="stat"><div class="k">' +
      J.escapeHtml(key) +
      '</div><div class="v">' +
      J.escapeHtml(value) +
      '</div><div class="s">' +
      J.escapeHtml(sub || "") +
      "</div></div>"
    );
  }

  function renderApps() {
    const apps = (state && state.apps) || [];
    $("apps-count").textContent = J.plural(apps.length, "app") + " · click Open to start one in its own window";
    $("apps").innerHTML = apps
      .map((app) => {
        const running = app.running;
        const accent = app.accent || "#6f7887";
        const initials = (app.short || app.name || "?").slice(0, 1).toUpperCase();
        const actions = [];
        if (running) {
          actions.push(`<button class="btn small" data-stop="${J.attr(app.id)}">Stop</button>`);
          if (app.page) actions.push(`<a class="btn small ghost" href="${J.attr(app.page)}">Open here</a>`);
        } else {
          actions.push(`<button class="btn small primary" data-start="${J.attr(app.id)}">Open</button>`);
        }
        if (app.page) actions.push(`<button class="btn small ghost" data-preview="${J.attr(app.id)}">New window</button>`);
        if (app.folder) actions.push(`<button class="btn small ghost" data-reveal="${J.attr(app.folder)}">Folder</button>`);
        return (
          '<div class="card launch-card">' +
          '<div class="top">' +
          `<div class="app-mark" style="background: ${J.attr(accent)}">${J.escapeHtml(initials)}</div>` +
          '<div class="grow"><h3>' +
          J.escapeHtml(app.name) +
          '</h3><div class="row" style="gap:6px;margin-top:2px"><span class="status-dot' +
          (running ? " on" : "") +
          '"></span><span class="faint" style="font-size:12px">' +
          (running ? "running · pid " + app.pid + (app.started ? " · since " + app.started.split("T")[1] : "") : "not running") +
          "</span>" +
          (app.orphan ? '<span class="pill warn">untracked</span>' : "") +
          (app.kind === "external" ? '<span class="pill">external</span>' : "") +
          "</div></div></div>" +
          '<div class="desc">' +
          J.escapeHtml(app.description || "") +
          "</div>" +
          '<div class="kv">' +
          (app.page ? "<span><b>page</b> " + J.escapeHtml(app.page) + "</span>" : (app.folder ? "<span><b>folder</b> " + J.escapeHtml(app.folder) + "</span>" : "")) +
          "</div>" +
          '<div class="actions">' +
          actions.join("") +
          "</div></div>"
        );
      })
      .join("");
  }

  function renderLibrary() {
    const library = (state && state.library) || {};
    const kinds = library.kinds || {};
    const root = ((state && state.paths) || {}).library || "";
    $("library-count").textContent = J.plural(library.items || 0, "item") + " across " + J.plural(library.programs || 0, "program");
    const chips = Object.keys(kinds)
      .sort((a, b) => kinds[b] - kinds[a])
      .map(
        (kind) =>
          `<a class="chip" href="/store?kind=${J.attr(kind)}">${J.glyph(kind)} ${J.escapeHtml(
            J.kindLabel(kind)
          )} <span class="count">${kinds[kind]}</span></a>`
      )
      .join("");
    $("library-panel").innerHTML =
      `<div class="row" style="flex-wrap:wrap;gap:6px">${chips || '<span class="faint">Nothing indexed yet.</span>'}</div>` +
      '<div class="row" style="margin-top:14px;gap:8px;flex-wrap:wrap">' +
      '<button class="btn small" data-open-app="store">Open the store</button>' +
      '<button class="btn small" data-open-app="news">Open the news portal</button>' +
      '<button class="btn small ghost" data-reveal="' + J.attr(root) + '">Show the library folder</button>' +
      '<button class="btn small ghost" data-import="1">Import files…</button>' +
      "</div>" +
      `<div class="faint" style="margin-top:10px">${J.escapeHtml(root)}</div>`;
  }

  function renderConvert() {
    const engine = (state && state.engine) || {};
    const library = (state && state.library) || {};
    const convertible = (library.kinds && library.kinds.note) || 0;
    $("convert-count").textContent = convertible ? J.plural(convertible, "script") + " can be converted" : "nothing to convert";
    $("convert-panel").innerHTML =
      '<div class="row" style="gap:10px;flex-wrap:wrap">' +
      `<span class="pill ${engine.resolved === "edge" ? "good" : "warn"}">${J.escapeHtml(engine.resolved === "edge" ? "high fidelity" : "built-in writer")}</span>` +
      `<span class="muted grow">${
        engine.resolved === "edge"
          ? "PDFs are printed by " + J.escapeHtml(engine.browserName || "your browser") + " using the print stylesheet."
          : "No browser found, so JADELY lays the pages out itself. Still a real PDF."
      }</span>` +
      '<button class="btn small primary" id="btn-convert-all">Convert everything</button>' +
      "</div>" +
      '<div class="faint" style="margin-top:10px">Markdown, plain text and Word .docx files become PDFs beside the original. Existing PDFs are left alone; legacy .doc needs Word first.</div>';
  }

  function renderPaths() {
    const paths = (state && state.paths) || {};
    const rows = [
      ["Application", paths.app],
      ["Library", paths.library],
      ["Vault", paths.vault],
    ].filter((row) => row[1]);
    $("paths-panel").innerHTML = rows
      .map(
        ([label, value]) =>
          '<div class="rowitem" style="cursor:default">' +
          `<span class="glyph">${J.escapeHtml(label.slice(0, 1))}</span>` +
          '<div class="grow"><div class="title">' +
          J.escapeHtml(label) +
          '</div><div class="sub mono nowrap">' +
          J.escapeHtml(value) +
          "</div></div>" +
          `<button class="btn small ghost" data-reveal="${J.attr(value)}">Show</button>` +
          "</div>"
      )
      .join("");
  }

  function render() {
    if (!state) return;
    $("version").textContent = "v" + (state.version || "");
    renderSummary();
    renderApps();
    renderLibrary();
    renderConvert();
    renderPaths();
  }

  // ----------------------------------------------------------------- loading
  async function load(options) {
    try {
      state = await J.api("launcher_state");
      if (!state.engine) {
        try {
          state.engine = await J.api("convert_engine");
        } catch (error) {
          state.engine = { resolved: "stdlib" };
        }
      }
      render();
    } catch (error) {
      if (!options || !options.quiet) J.failure(error);
    }
  }

  function poll(active) {
    clearInterval(polling);
    if (active) polling = setInterval(() => load({ quiet: true }), POLL_MS);
  }

  // ------------------------------------------------------------------ events
  document.addEventListener("click", async (event) => {
    const start = event.target.closest("[data-start]");
    const stop = event.target.closest("[data-stop]");
    const preview = event.target.closest("[data-preview]");
    const reveal = event.target.closest("[data-reveal]");
    const openApp = event.target.closest("[data-open-app]");
    const importBtn = event.target.closest("[data-import]");

    try {
      if (start) {
        await J.withBusy(start, async () => {
          const result = await J.api("launcher_start", { app: start.dataset.start });
          J.toast(result.message, result.alreadyRunning ? undefined : "good");
        });
        load();
      } else if (stop) {
        await J.withBusy(stop, async () => {
          const result = await J.api("launcher_stop", { app: stop.dataset.stop });
          J.toast(result.message, result.stopped ? "good" : undefined);
        });
        load();
      } else if (preview) {
        const app = (state.apps || []).find((item) => item.id === preview.dataset.preview);
        if (app && app.page) window.open(app.page, "_blank", "width=1200,height=860");
        else J.toast("That app has no page of its own.", "bad");
      } else if (reveal) {
        const result = await J.api("reveal_path", { path: reveal.dataset.reveal });
        if (result && result.ok) J.toast("Opened in the file manager.");
      } else if (openApp) {
        const app = (state.apps || []).find((item) => item.id === openApp.dataset.openApp);
        if (app && app.page) window.open(app.page, "_blank");
      } else if (importBtn) {
        await J.withBusy(importBtn, async () => {
          const result = await J.api("store_import_pick", { folder: "Imported" });
          if (result.cancelled) return;
          const count = (result.imported || []).length;
          J.toast(
            count ? J.plural(count, "file") + " imported into the library." : "Nothing new to import.",
            count ? "good" : undefined
          );
          if ((result.skipped || []).length) J.toast(result.skipped.length + " file(s) skipped.");
        });
        load();
      }
    } catch (error) {
      J.failure(error);
    }
  });

  $("btn-refresh").addEventListener("click", () => load());
  $("btn-stop-all").addEventListener("click", async (event) => {
    if (!window.confirm("Stop every app the launcher started?")) return;
    await J.withBusy(event.target, async () => {
      const result = await J.api("launcher_stop_all");
      J.toast(J.plural((result.results || []).length, "app") + " handled.", "good");
    });
    load();
  });

  document.addEventListener("click", async (event) => {
    if (event.target.id !== "btn-convert-all") return;
    if (!window.confirm("Convert every markdown, text and .docx file in the library to PDF?")) return;
    await J.withBusy(event.target, async () => {
      const report = await J.api("convert_batch", {});
      const counts = report.counts || {};
      J.toast(
        counts.converted + " converted, " + counts.skipped + " already had PDFs, " + counts.failed + " failed.",
        counts.failed ? "bad" : "good"
      );
    });
    load();
  });

  document.addEventListener("visibilitychange", () => poll(!document.hidden));

  // -------------------------------------------------------------------- init
  (async function boot() {
    const info = await J.init();
    if (info) {
      // Paint something immediately from app_state, then fill in the live parts.
      state = { version: info.version, library: info.library, engine: info.convert, apps: [], paths: {} };
      render();
    }
    await load();
    poll(!document.hidden);
  })();
})();
