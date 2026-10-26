/* JADELY — shared browser helpers for the launcher, the store and the news portal.
 *
 * Plain script, no build step: everything hangs off `window.Jadely`. The markdown
 * renderer is the notes app's own (`window.JadeliMD`, from markdown.js), so a
 * document looks the same wherever you read it.
 */
(function (global) {
  "use strict";

  // ------------------------------------------------------------------- api
  async function api(method, payload) {
    const response = await fetch("/api/" + method, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!body || !body.ok) {
      const message = (body && body.error) || "Request failed (" + response.status + ")";
      const failure = new Error(message);
      failure.kind = body && body.kind;
      throw failure;
    }
    return body.data;
  }

  // -------------------------------------------------------------- escaping
  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function attr(text) {
    return escapeHtml(text).replace(/'/g, "&#39;");
  }

  // ------------------------------------------------------------ formatting
  function formatTime(seconds) {
    const value = Number(seconds);
    if (!isFinite(value) || value <= 0) return "0:00";
    const total = Math.floor(value);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return hours ? hours + ":" + pad(minutes) + ":" + pad(secs) : minutes + ":" + pad(secs);
  }

  function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    const units = ["B", "KB", "MB", "GB"];
    let index = 0;
    let size = value;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index += 1;
    }
    return (index === 0 ? Math.round(size) : size.toFixed(1)) + " " + units[index];
  }

  function formatDate(iso) {
    if (!iso) return "";
    const parsed = new Date(iso);
    if (isNaN(parsed.getTime())) return iso;
    return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function plural(count, singular, pluralForm) {
    return count + " " + (count === 1 ? singular : pluralForm || singular + "s");
  }

  // ---------------------------------------------------------------- toasts
  let toastHost = null;

  function toast(message, kind) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.className = "toasts";
      document.body.appendChild(toastHost);
    }
    const node = document.createElement("div");
    node.className = "toast" + (kind ? " " + kind : "");
    node.textContent = message;
    toastHost.appendChild(node);
    setTimeout(() => {
      node.style.transition = "opacity .25s ease";
      node.style.opacity = "0";
      setTimeout(() => node.remove(), 260);
    }, kind === "bad" ? 6500 : 3600);
    return node;
  }

  function failure(error) {
    toast(error && error.message ? error.message : String(error), "bad");
  }

  // -------------------------------------------------------------- markdown
  function renderMarkdown(markdown, options) {
    if (global.JadeliMD && typeof global.JadeliMD.render === "function") {
      return global.JadeliMD.render(markdown || "", options || {});
    }
    return "<pre>" + escapeHtml(markdown || "") + "</pre>";
  }

  function plainText(markdown) {
    return String(markdown || "")
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/^---[\s\S]*?---/m, " ")
      .replace(/[#>*_`~\[\]()|]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // ----------------------------------------------------------------- kinds
  const GLYPHS = {
    note: "\uD83D\uDCDD",
    audio: "\uD83C\uDFA7",
    pdf: "\uD83D\uDCC4",
    document: "\uD83D\uDCC3",
    image: "\uD83D\uDDBC",
    file: "\uD83D\uDCC1",
  };

  function glyph(kind) {
    return GLYPHS[kind] || GLYPHS.file;
  }

  function kindLabel(kind) {
    return { note: "Script", audio: "Audio", pdf: "PDF", document: "Word", image: "Image" }[kind] || kind;
  }

  // ----------------------------------------------------------------- theme
  const THEME_KEY = "jadely-theme";

  function applyTheme(theme) {
    const chosen = theme || localStorage.getItem(THEME_KEY) || "dark";
    document.documentElement.setAttribute("data-theme", chosen);
    return chosen;
  }

  function toggleTheme() {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
    return next;
  }

  // ---------------------------------------------------------------- speech
  const speech = {
    utterance: null,
    queue: [],
    index: 0,
    speaking: false,
    onParagraph: null,
    onDone: null,
  };

  function speechSupported() {
    return typeof global.speechSynthesis !== "undefined" && typeof global.SpeechSynthesisUtterance !== "undefined";
  }

  function stopSpeaking() {
    if (!speechSupported()) return;
    speech.queue = [];
    speech.speaking = false;
    speech.utterance = null;
    try {
      global.speechSynthesis.cancel();
    } catch (error) {
      /* nothing to cancel */
    }
  }

  function speak(paragraphs, options) {
    const settings = options || {};
    if (!speechSupported()) {
      toast("This window cannot speak text.", "bad");
      return false;
    }
    stopSpeaking();
    speech.queue = (paragraphs || []).filter(Boolean);
    speech.index = 0;
    speech.speaking = true;
    speech.onParagraph = settings.onParagraph || null;
    speech.onDone = settings.onDone || null;
    speech.rate = settings.rate || 1;

    const next = () => {
      if (!speech.speaking) return;
      if (speech.index >= speech.queue.length) {
        speech.speaking = false;
        if (speech.onParagraph) speech.onParagraph(-1);
        if (speech.onDone) speech.onDone();
        return;
      }
      const position = speech.index;
      const utterance = new global.SpeechSynthesisUtterance(speech.queue[position]);
      utterance.rate = speech.rate;
      if (settings.language) utterance.lang = settings.language;
      utterance.onend = () => {
        speech.index += 1;
        next();
      };
      utterance.onerror = () => {
        speech.index += 1;
        next();
      };
      speech.utterance = utterance;
      if (speech.onParagraph) speech.onParagraph(position);
      global.speechSynthesis.speak(utterance);
    };
    next();
    return true;
  }

  function pauseSpeaking() {
    if (speechSupported() && global.speechSynthesis.paused) {
      global.speechSynthesis.resume();
      return false;
    }
    if (speechSupported()) global.speechSynthesis.pause();
    return true;
  }

  // Speak whatever is on screen, highlighting the block being read. Using the
  // rendered elements as the unit keeps the voice in step with the page by
  // construction — no index bookkeeping against a separate text extract.
  const SPEAKABLE = "h1, h2, h3, h4, p, li, blockquote";

  function speakableElements(container) {
    if (!container) return [];
    return Array.prototype.filter.call(container.querySelectorAll(SPEAKABLE), (node) => {
      if (!node.textContent.trim()) return false;
      if (node.closest("pre")) return false;
      if (node.querySelector("pre")) return false;
      return true;
    });
  }

  function speakElements(container, options) {
    const settings = options || {};
    const elements = speakableElements(container);
    if (!elements.length) {
      toast("There is nothing here to read out.", "bad");
      return false;
    }
    const texts = elements.map((node) => node.textContent.trim());
    return speak(texts, {
      rate: settings.rate,
      language: settings.language,
      onParagraph: (index) => {
        elements.forEach((node, position) => node.classList.toggle("speaking", position === index));
        if (index >= 0 && settings.follow !== false) {
          try {
            elements[index].scrollIntoView({ block: "center", behavior: "smooth" });
          } catch (error) {
            /* older engines */
          }
        }
      },
      onDone: () => {
        elements.forEach((node) => node.classList.remove("speaking"));
        if (settings.onDone) settings.onDone();
      },
    });
  }

  // ---------------------------------------------------------------- helpers
  function debounce(fn, wait) {
    let timer = 0;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), wait || 200);
    };
  }

  function withBusy(button, work) {
    if (!button) return Promise.resolve().then(work);
    const label = button.dataset.label || button.textContent;
    button.dataset.label = label;
    button.disabled = true;
    button.textContent = "…";
    return Promise.resolve()
      .then(work)
      .finally(() => {
        button.disabled = false;
        button.textContent = label;
      });
  }

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstElementChild;
  }

  // --------------------------------------------------------------- player
  /* One player, used by the store and the news portal. It streams through
     /media (which supports Range, so scrubbing works) and reports position back
     to the server so "continue listening" survives a restart. */
  function createPlayer(options) {
    const settings = options || {};
    const host = settings.mount;
    if (!host) throw new Error("createPlayer needs a mount element");
    host.className = "player hidden";
    host.innerHTML =
      '<div class="now"><div class="t" data-title>Nothing playing</div><div class="s" data-sub></div></div>' +
      '<div class="controls">' +
      (settings.onPrevious ? '<button class="btn small ghost" data-prev title="Previous">&#9198;</button>' : "") +
      '<button class="playbtn" data-toggle title="Play or pause">&#9654;</button>' +
      (settings.onNext ? '<button class="btn small ghost" data-next title="Next">&#9197;</button>' : "") +
      '<button class="btn small ghost" data-back title="Back 15 seconds">&minus;15</button>' +
      '<button class="btn small ghost" data-forward title="Forward 15 seconds">+15</button>' +
      "</div>" +
      '<div class="seek"><input type="range" data-seek min="0" max="1000" step="1" value="0">' +
      '<span class="time" data-current>0:00</span><span class="time" data-total>0:00</span></div>' +
      '<select class="rate" data-rate title="Speed">' +
      '<option value="0.75">0.75&times;</option><option value="1" selected>1&times;</option>' +
      '<option value="1.25">1.25&times;</option><option value="1.5">1.5&times;</option>' +
      '<option value="2">2&times;</option></select>' +
      '<button class="btn small ghost" data-close title="Stop">&times;</button>';

    const audio = document.createElement("audio");
    audio.preload = "metadata";
    host.appendChild(audio);

    const titleNode = host.querySelector("[data-title]");
    const subNode = host.querySelector("[data-sub]");
    const toggleNode = host.querySelector("[data-toggle]");
    const seekNode = host.querySelector("[data-seek]");
    const currentNode = host.querySelector("[data-current]");
    const totalNode = host.querySelector("[data-total]");
    const rateNode = host.querySelector("[data-rate]");

    let current = null;
    let lastSaved = 0;
    let seeking = false;

    function paint() {
      toggleNode.innerHTML = audio.paused ? "&#9654;" : "&#10073;&#10073;";
    }

    function report(extra) {
      if (!current) return;
      const payload = Object.assign(
        { position: audio.currentTime || 0, duration: audio.duration || current.duration || 0 },
        extra || {}
      );
      if (settings.onProgress) settings.onProgress(current, payload);
    }

    function play(item) {
      if (!item || !item.url) {
        toast("That item has no playable audio.", "bad");
        return false;
      }
      host.classList.remove("hidden");
      if (current && current.id === item.id) {
        if (audio.paused) audio.play().catch(() => {});
        else audio.pause();
        return true;
      }
      current = item;
      titleNode.textContent = item.title || "Audio";
      subNode.textContent = item.subtitle || "";
      lastSaved = 0;
      audio.src = item.url;
      if (item.startAt) {
        audio.addEventListener(
          "loadedmetadata",
          () => {
            try {
              audio.currentTime = item.startAt;
            } catch (error) {
              /* not seekable yet */
            }
          },
          { once: true }
        );
      }
      audio.play().catch(() => toast("This browser would not play that file.", "bad"));
      return true;
    }

    function stop() {
      if (current) report();
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      current = null;
      host.classList.add("hidden");
    }

    audio.addEventListener("play", paint);
    audio.addEventListener("pause", () => {
      paint();
      report();
    });
    audio.addEventListener("loadedmetadata", () => {
      totalNode.textContent = formatTime(audio.duration);
    });
    audio.addEventListener("timeupdate", () => {
      if (!seeking && audio.duration) {
        seekNode.value = String(Math.round((audio.currentTime / audio.duration) * 1000));
      }
      currentNode.textContent = formatTime(audio.currentTime);
      const now = Date.now();
      if (now - lastSaved > 5000) {
        lastSaved = now;
        report();
      }
    });
    audio.addEventListener("ended", () => {
      paint();
      // Record the end of the track rather than zero: the position is still honest
      // (and the resume guard knows not to start a finished track at the end).
      report({ position: audio.duration || 0, played: true });
      if (settings.onEnded) settings.onEnded(current);
    });
    audio.addEventListener("error", () => {
      if (audio.src) toast("Could not open that audio file.", "bad");
    });

    toggleNode.addEventListener("click", () => {
      if (!current) return;
      if (audio.paused) audio.play().catch(() => {});
      else audio.pause();
    });
    const back = host.querySelector("[data-back]");
    const forward = host.querySelector("[data-forward]");
    if (back) back.addEventListener("click", () => { audio.currentTime = Math.max(0, audio.currentTime - 15); });
    if (forward) forward.addEventListener("click", () => { audio.currentTime = Math.min(audio.duration || 1e9, audio.currentTime + 15); });
    const next = host.querySelector("[data-next]");
    const prev = host.querySelector("[data-prev]");
    if (next) next.addEventListener("click", () => settings.onNext(current));
    if (prev) prev.addEventListener("click", () => settings.onPrevious(current));
    seekNode.addEventListener("input", () => {
      seeking = true;
      if (audio.duration) {
        currentNode.textContent = formatTime((Number(seekNode.value) / 1000) * audio.duration);
      }
    });
    seekNode.addEventListener("change", () => {
      if (audio.duration) audio.currentTime = (Number(seekNode.value) / 1000) * audio.duration;
      seeking = false;
      report();
    });
    rateNode.addEventListener("change", () => {
      audio.playbackRate = Number(rateNode.value) || 1;
    });
    host.querySelector("[data-close]").addEventListener("click", () => {
      stop();
      if (settings.onClose) settings.onClose();
    });

    return {
      play,
      stop,
      pause: () => audio.pause(),
      resume: () => audio.play().catch(() => {}),
      isPlaying: () => !audio.paused && !!current,
      current: () => current,
      audio,
      host,
    };
  }

  // ------------------------------------------------------------------ boot
  function init(options) {
    applyTheme((options && options.theme) || localStorage.getItem(THEME_KEY));
    const toggle = document.querySelector("[data-theme-toggle]");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const theme = toggleTheme();
        if (options && options.onTheme) options.onTheme(theme);
      });
    }
    return api("app_state").catch(() => null);
  }

  global.Jadely = {
    api,
    escapeHtml,
    attr,
    formatTime,
    formatBytes,
    formatDate,
    plural,
    toast,
    failure,
    renderMarkdown,
    plainText,
    glyph,
    kindLabel,
    applyTheme,
    toggleTheme,
    speechSupported,
    speak,
    speakableElements,
    speakElements,
    stopSpeaking,
    pauseSpeaking,
    createPlayer,
    debounce,
    withBusy,
    el,
    init,
  };
})(window);
