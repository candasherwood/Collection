/* JADELY News — programs of segments you can read or listen to.
 *
 * A segment pairs a markdown script with an audio file. Playback streams through
 * /media, position is saved to the library's state file, and a segment with no
 * audio can be read aloud with the system voice instead.
 */
(function () {
  "use strict";

  const J = window.Jadely;
  const $ = (id) => document.getElementById(id);

  let feed = { programs: [], continue: [], hidden: [], stats: {} };
  let hiddenShown = false;
  let program = null;
  let segment = null;
  let segmentText = "";
  let query = "";

  const player = J.createPlayer({
    mount: $("player-mount"),
    onNext: () => step(1),
    onPrevious: () => step(-1),
    onProgress: (item, payload) => {
      J.api("news_progress", {
        segment: item.id,
        position: payload.position,
        duration: payload.duration,
        played: payload.played === undefined ? null : payload.played,
      }).catch(() => {});
      if (segment && segment.id === item.id && payload.duration) {
        segment.progress = Object.assign({}, segment.progress, {
          position: payload.position,
          duration: payload.duration,
          played: payload.played === true ? true : segment.progress.played,
        });
      }
    },
    onEnded: (item) => {
      if (item) J.api("news_played", { segment: item.id, played: true }).catch(() => {});
      step(1);
    },
  });

  // ------------------------------------------------------------------- rail
  function renderRail() {
    const parts = [];

    if (feed.continue && feed.continue.length) {
      parts.push("<h3>Continue listening</h3>");
      feed.continue.forEach((entry) => {
        const percent = (entry.progress && entry.progress.percent) || 0;
        parts.push(
          `<div class="rail-item${program && program.id === entry.id ? " on" : ""}" data-program="${J.attr(entry.id)}">` +
            (entry.cover
              ? `<img class="rail-cover" src="${J.attr(entry.cover)}" alt="">`
              : '<span class="swatch" style="background:var(--accent)"></span>') +
            '<div class="grow"><div class="nowrap">' +
            J.escapeHtml(entry.title) +
            '</div><div class="faint" style="font-size:11px">' +
            J.escapeHtml(
              (entry.progress.segmentTitle ? entry.progress.segmentTitle + " · " : "") + percent + "% listened"
            ) +
            "</div></div></div>"
        );
      });
    }

    parts.push("<h3>Programs</h3>");
    if (!feed.programs.length) parts.push('<div class="rail-sub">No programs yet.</div>');
    feed.programs.forEach((entry) => {
      parts.push(
        `<div class="rail-item${program && program.id === entry.id ? " on" : ""}" data-program="${J.attr(entry.id)}">` +
          (entry.cover
            ? `<img class="rail-cover" src="${J.attr(entry.cover)}" alt="">`
            : '<span class="swatch" style="background:var(--accent)"></span>') +
          '<div class="grow"><div class="nowrap">' +
          J.escapeHtml(entry.title) +
          '</div><div class="faint" style="font-size:11px">' +
          J.escapeHtml(
            J.plural(entry.counts.segments, "segment") + (entry.durationLabel ? " · " + entry.durationLabel : "")
          ) +
          "</div></div>" +
          (entry.flags.favorite ? '<span title="Favorite">★</span>' : "") +
          "</div>"
      );
    });

    if (hiddenShown && feed.hidden && feed.hidden.length) {
      parts.push("<h3>Hidden shelves</h3>");
      feed.hidden.forEach((entry) => {
        parts.push(
          `<div class="rail-item${program && program.id === entry.id ? " on" : ""}" data-program="${J.attr(entry.id)}">` +
            '<span class="swatch" style="background:var(--faint)"></span>' +
            '<div class="grow nowrap">' +
            J.escapeHtml(entry.title) +
            '</div><span class="count">' +
            entry.counts.segments +
            "</span></div>"
        );
      });
    }

    $("rail").innerHTML = parts.join("");
  }

  // ---------------------------------------------------------------- program
  function renderProgram() {
    const host = $("program");
    if (!program) {
      host.innerHTML =
        '<div class="empty"><div class="big">Nothing to play yet.</div>' +
        "Add a folder of markdown and audio to the library, then reload. A program is a folder; each segment is a script, an audio file, or both.</div>";
      return;
    }
    const entry = program;
    const art = entry.cover
      ? `<img src="${J.attr(entry.cover)}" alt="">`
      : `<span class="glyph">${J.glyph(entry.kinds.includes("audio") ? "audio" : "note")}</span>`;
    const byline = [entry.author, entry.narrator ? "read by " + entry.narrator : "", entry.series]
      .filter(Boolean)
      .join(" · ");
    const withAudio = entry.segments.filter((item) => item.audioUrl).length;

    host.innerHTML =
      '<div class="program-hero"><div class="art">' +
      art +
      "</div><div class=\"grow\">" +
      `<h1>${J.escapeHtml(entry.title)}</h1>` +
      (byline ? `<div class="byline">${J.escapeHtml(byline)}</div>` : "") +
      '<div class="kv">' +
      `<span><b>${entry.counts.segments}</b> segments</span>` +
      (entry.durationLabel ? `<span><b>${J.escapeHtml(entry.durationLabel)}</b> of audio</span>` : "") +
      `<span><b>${entry.counts.words}</b> words</span>` +
      (entry.counts.attachments ? `<span><b>${entry.counts.attachments}</b> attachment(s)</span>` : "") +
      (entry.updatedLabel ? `<span>updated ${J.escapeHtml(entry.updatedLabel.split("T")[0])}</span>` : "") +
      "</div>" +
      (entry.description ? `<p class="program-desc">${J.escapeHtml(entry.description)}</p>` : "") +
      '<div class="actionrow">' +
      (withAudio
        ? '<button class="btn small primary" data-action="play-program">▶ Play from the start</button>'
        : '<button class="btn small primary" data-action="read-program">🔊 Read the first segment</button>') +
      `<button class="chip${entry.flags.favorite ? " on" : ""}" data-toggle-program="favorite">★ Favorite</button>` +
      `<button class="chip${entry.flags.pinned ? " on" : ""}" data-toggle-program="pinned">📌 Pin</button>` +
      (entry.tags.length ? entry.tags.map((tag) => `<span class="taglink">#${J.escapeHtml(tag)}</span>`).join("") : "") +
      "</div></div></div>" +
      (entry.attachments.length
        ? '<div class="section-head" style="margin-top:4px"><h2>Attachments</h2></div><div class="row" style="gap:8px;flex-wrap:wrap;margin-bottom:18px">' +
          entry.attachments
            .map(
              (file) =>
                `<button class="btn small" data-attachment="${J.attr(file.url)}" data-attachment-title="${J.attr(
                  file.title
                )}">${J.glyph(file.kind)} ${J.escapeHtml(file.name)} <span class="faint">${J.escapeHtml(
                  file.sizeLabel
                )}</span></button>`
            )
            .join("") +
          "</div>"
        : "") +
      '<div class="section-head" style="margin-top:6px"><h2>Segments</h2><span class="count">click to read, press ▶ to listen</span></div>' +
      '<div class="seglist">' +
      entry.segments.map(renderSegmentRow).join("") +
      "</div>";
  }

  function renderSegmentRow(item) {
    const playing = player.current() && player.current().id === item.id && player.isPlaying();
    const percent = item.progress && item.progress.duration ? Math.round((item.progress.position / item.progress.duration) * 100) : item.percent || 0;
    const bits = [
      `<span class="pill ${item.kind === "audio+script" ? "audio" : item.kind === "audio" ? "audio" : "note"}">${
        item.kind === "audio+script" ? "audio + script" : item.kind
      }</span>`,
    ];
    if (item.durationLabel) bits.push("<span>" + item.durationLabel + "</span>");
    if (item.words) bits.push("<span>" + item.words + " words</span>");
    if (item.flags.played) bits.push('<span class="pill good">played</span>');
    if (percent > 0 && percent < 96) bits.push("<span>" + percent + "% listened</span>");
    return (
      `<div class="seg${segment && segment.id === item.id ? " on" : ""}${playing ? " playing" : ""}" data-segment="${J.attr(
        item.id
      )}">` +
      `<span class="num">${item.number}</span>` +
      '<div class="grow"><div class="segtitle">' +
      J.escapeHtml(item.title) +
      '</div><div class="segsub">' +
      bits.join("") +
      "</div></div>" +
      (playing
        ? '<span class="bars"><i></i><i></i><i></i></span>'
        : item.audioUrl
        ? '<button class="segplay" data-play="' + J.attr(item.id) + '" title="Play">▶</button>'
        : '<button class="segplay" data-read="' + J.attr(item.id) + '" title="Read aloud">🔊</button>') +
      "</div>"
    );
  }

  // ------------------------------------------------------------- transcript
  function renderTranscript() {
    const host = $("transcript");
    if (!program) {
      host.innerHTML = '<div class="empty">Pick a program on the left.</div>';
      return;
    }
    if (!segment) {
      host.innerHTML =
        '<div class="empty"><div class="big">No segment open</div>Choose one from the list to see its script here.</div>';
      return;
    }
    const item = segment;
    const percent = item.progress && item.progress.duration ? Math.round((item.progress.position / item.progress.duration) * 100) : 0;
    host.innerHTML =
      '<div class="row" style="gap:8px;align-items:flex-start"><div class="grow"><h2>' +
      J.escapeHtml(item.title) +
      '</h2><div class="faint" style="font-size:12px">' +
      J.escapeHtml(program.title + " · segment " + item.number + " of " + program.segments.length) +
      "</div></div>" +
      (item.flags.played ? '<span class="pill good">played</span>' : "") +
      "</div>" +
      '<div class="row" style="gap:6px;margin-top:10px;flex-wrap:wrap">' +
      (item.audioUrl ? '<button class="btn small primary" data-action="play">▶ Listen</button>' : "") +
      (item.scriptId ? '<button class="btn small" data-action="read">🔊 Read aloud</button>' : "") +
      '<button class="btn small ghost" data-action="stop">Stop</button>' +
      `<button class="chip${item.flags.favorite ? " on" : ""}" data-segment-flag="favorite">★</button>` +
      `<button class="chip${item.flags.played ? " on" : ""}" data-segment-flag="played">✓ Played</button>` +
      "</div>" +
      (percent > 0
        ? `<div style="margin-top:10px"><div style="height:4px;background:var(--panel-3);border-radius:3px"><i style="display:block;height:100%;width:${percent}%;background:var(--accent);border-radius:3px"></i></div></div>`
        : "") +
      '<div class="panel-section">' +
      (item.scriptId
        ? '<article class="transcript" id="transcript-body">' + J.renderMarkdown(segmentText, { showProperties: true }) + "</article>"
        : '<div class="empty">This segment has no script — it is audio only.</div>') +
      "</div>" +
      (item.audioName
        ? '<div class="panel-section"><h4>Audio file</h4><div class="faint mono" style="word-break:break-all;font-size:11.5px">' +
          J.escapeHtml(item.audioName) +
          "</div></div>"
        : "");
  }

  async function selectSegment(segmentId, options) {
    if (!program || !segmentId) return;
    try {
      const data = await J.api("news_segment", { program: program.id, segment: segmentId });
      segment = data.segment;
      segmentText = data.text || "";
    } catch (error) {
      J.failure(error);
      return;
    }
    renderProgram();
    renderTranscript();
    if (options && options.scroll) {
      const node = $(  "transcript" );
      if (node) node.scrollTop = 0;
    }
  }

  async function selectProgram(programId, options) {
    try {
      const data = await J.api("news_program", { program: programId });
      program = data.program;
    } catch (error) {
      J.failure(error);
      return;
    }
    const preferred =
      (program.progress && program.progress.segmentId) ||
      (program.segments[0] && program.segments[0].id);
    segment = null;
    segmentText = "";
    renderRail();
    renderProgram();
    if (preferred) await selectSegment(preferred);
    if (options && options.play) await playSegment(preferred);
  }

  // ---------------------------------------------------------------- playback
  function audioSegments() {
    return (program ? program.segments : []).filter((item) => item.audioUrl);
  }

  async function playSegment(segmentId) {
    if (!program) return;
    const item = program.segments.find((entry) => entry.id === segmentId);
    if (!item) return;
    if (!item.audioUrl) return readSegment(segmentId);
    if (segment && segment.id !== item.id) await selectSegment(item.id);
    const position = (item.progress && item.progress.position) || 0;
    const resume = item.duration && position < item.duration - 5 ? position : 0;
    player.play({
      id: item.id,
      title: item.title,
      subtitle: program.title + " · " + (item.durationLabel || ""),
      url: item.audioUrl,
      duration: item.duration,
      startAt: resume,
    });
    renderProgram();
    if (resume) J.toast("Resuming at " + J.formatTime(resume) + ".");
  }

  async function step(direction) {
    if (!program) return;
    const list = audioSegments();
    if (!list.length) return;
    const currentId = player.current() ? player.current().id : null;
    const index = list.findIndex((item) => item.id === currentId);
    const nextIndex = Math.min(list.length - 1, Math.max(0, index + direction));
    if (nextIndex === index) return;
    await playSegment(list[nextIndex].id);
  }

  async function readSegment(segmentId, options) {
    if (!program) return;
    const item = program.segments.find((entry) => entry.id === segmentId);
    if (!item) return;
    if (!item.scriptId) {
      J.toast("That segment has no script to read — it is audio only.", "bad");
      return;
    }
    if (!segment || segment.id !== item.id) await selectSegment(item.id);
    const started = J.speakElements($("transcript-body"), { rate: (options && options.rate) || 1 });
    if (started) J.toast("Reading aloud with the system voice. Press Stop to end it.");
  }

  // ------------------------------------------------------------------ modal
  function openPdf(url, title) {
    $("modals").innerHTML =
      '<div class="modal-backdrop"><div class="modal">' +
      '<header><h2 class="grow nowrap">' +
      J.escapeHtml(title || "Attachment") +
      '</h2><span class="pill pdf">PDF</span><button class="btn small ghost" data-close="1">Close</button></header>' +
      '<div class="body pdf"><iframe src="' + J.attr(url) + '#view=FitH" title="attachment"></iframe></div>' +
      "</div></div>";
    const backdrop = $("modals").querySelector(".modal-backdrop");
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) closeModal();
    });
  }

  function closeModal() {
    $("modals").innerHTML = "";
  }

  // ------------------------------------------------------------------ feed
  async function loadFeed(options) {
    const data = await J.api("news_feed", { includeHidden: hiddenShown });
    feed = data;
    renderRail();
    const wanted = (options && options.program) || (program && program.id) || (feed.programs[0] && feed.programs[0].id);
    if (wanted) {
      const known =
        feed.programs.some((entry) => entry.id === wanted) || (feed.hidden || []).some((entry) => entry.id === wanted);
      await selectProgram(known ? wanted : feed.programs[0] && feed.programs[0].id);
    } else {
      program = null;
      renderProgram();
      renderTranscript();
    }
  }

  // ----------------------------------------------------------------- events
  document.addEventListener("click", async (event) => {
    const target = event.target;

    if (target.dataset && target.dataset.close) return closeModal();

    const programLink = target.closest("[data-program]");
    if (programLink) return selectProgram(programLink.dataset.program);

    const attachment = target.closest("[data-attachment]");
    if (attachment) return openPdf(attachment.dataset.attachment, attachment.dataset.attachmentTitle);

    const playButton = target.closest("[data-play]");
    if (playButton) {
      event.stopPropagation();
      return playSegment(playButton.dataset.play);
    }

    const readButton = target.closest("[data-read]");
    if (readButton) {
      event.stopPropagation();
      return readSegment(readButton.dataset.read);
    }

    const row = target.closest("[data-segment]");
    if (row && !target.closest("[data-action]")) return selectSegment(row.dataset.segment);

    const toggleProgram = target.closest("[data-toggle-program]");
    if (toggleProgram && program) {
      try {
        await J.api("news_toggle", { program: program.id, flag: toggleProgram.dataset.toggleProgram });
      } catch (error) {
        J.failure(error);
      }
      return loadFeed();
    }

    const segmentFlag = target.closest("[data-segment-flag]");
    if (segmentFlag && segment) {
      try {
        if (segmentFlag.dataset.segmentFlag === "played") {
          await J.api("news_played", { segment: segment.id, played: !segment.flags.played });
        } else {
          await J.api("store_toggle", { itemId: segment.scriptId || segment.audioId, flag: segmentFlag.dataset.segmentFlag });
        }
      } catch (error) {
        J.failure(error);
      }
      await loadFeed({ program: program.id });
      return selectSegment(segment.id);
    }

    const action = target.closest("[data-action]");
    if (action) {
      const what = action.dataset.action;
      if (what === "play" && segment) return playSegment(segment.id);
      if (what === "read" && segment) return readSegment(segment.id);
      if (what === "stop") {
        J.stopSpeaking();
        document.querySelectorAll(".speaking").forEach((node) => node.classList.remove("speaking"));
        return;
      }
      if (what === "play-program" && program) return playSegment(audioSegments()[0] && audioSegments()[0].id);
      if (what === "read-program" && program) return readSegment(program.segments[0] && program.segments[0].id);
    }
  });

  $("q").addEventListener(
    "input",
    J.debounce(async (event) => {
      query = event.target.value.trim();
      if (!query) {
        await loadFeed();
        return;
      }
      try {
        const results = await J.api("news_search", { query });
        const hits = results.results || [];
        $("program").innerHTML =
          '<div class="section-head"><h2>Search</h2><span class="count">' +
          J.plural(hits.length, "match") +
          '</span></div><div class="seglist">' +
          (hits.length
            ? hits
                .map(
                  (hit) =>
                    `<div class="seg" data-open="${J.attr(hit.program)}" data-open-segment="${J.attr(hit.segment)}">` +
                    '<span class="num">↗</span><div class="grow"><div class="segtitle">' +
                    J.escapeHtml(hit.title) +
                    '</div><div class="segsub"><span>' +
                    J.escapeHtml(hit.programTitle) +
                    "</span><span>" +
                    J.escapeHtml(hit.kind) +
                    "</span></div></div></div>"
                )
                .join("")
            : '<div class="empty">No segment matches that.</div>') +
          "</div>";
      } catch (error) {
        J.failure(error);
      }
    }, 200)
  );

  document.addEventListener("click", async (event) => {
    const open = event.target.closest("[data-open]");
    if (!open) return;
    await selectProgram(open.dataset.open);
    await selectSegment(open.dataset.openSegment);
  });

  $("btn-hidden").addEventListener("click", async (event) => {
    hiddenShown = !hiddenShown;
    event.target.classList.toggle("ghost", !hiddenShown);
    await loadFeed();
    if (hiddenShown && (!feed.hidden || !feed.hidden.length)) J.toast("No shelves are marked hidden.");
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("modals").innerHTML) closeModal();
    if (event.target.tagName === "INPUT") return;
    if (event.key === " ") {
      event.preventDefault();
      if (player.current()) player.play(player.current());
      else if (program) playSegment(program.segments[0].id);
    }
    if (event.key === "ArrowRight") step(1);
    if (event.key === "ArrowLeft") step(-1);
  });

  // -------------------------------------------------------------------- init
  (async function boot() {
    await J.init();
    try {
      await loadFeed();
    } catch (error) {
      J.failure(error);
    }
  })();
})();
