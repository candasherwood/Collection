/* jadeli — a small, dependency-free markdown renderer.
 * Supports: headings, emphasis, strikethrough, highlight, code (inline + fenced),
 * links, images, wiki links, #tags, task lists, tables, blockquotes, callouts,
 * horizontal rules. Links, wiki links and tags become clickable elements the
 * app wires up with event delegation.
 */
(function (global) {
  "use strict";

  const PH = "\u0000";

  function escapeHtml(text) {
    return String(text)
      .replace(/\u0000/g, "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function slugify(text) {
    return String(text)
      .toLowerCase()
      .replace(/[`*_~[\]()#!]/g, "")
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-");
  }

  // ---------------------------------------------------------------- inline
  function renderInline(raw, ctx) {
    const slots = [];
    const hold = (html) => {
      slots.push(html);
      return PH + (slots.length - 1) + PH;
    };

    let text = escapeHtml(raw);

    // code spans first so nothing inside them is styled
    text = text.replace(/`([^`\n]+)`/g, (_, code) => hold(`<code>${code}</code>`));

    // images
    text = text.replace(
      /!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)/g,
      (_, alt, src, title) =>
        hold(
          `<img src="${src}" alt="${alt}"${title ? ` title="${title}"` : ""} loading="lazy">`
        )
    );

    // markdown links
    text = text.replace(
      /\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)/g,
      (_, label, href, title) =>
        hold(
          `<a href="${href}" class="external"${title ? ` title="${title}"` : ""} target="_blank" rel="noreferrer">${label}</a>`
        )
    );

    // wiki links  [[target]] / [[target|alias]] / [[target#heading]]
    text = text.replace(
      /\[\[([^\[\]|#]+)(#[^\[\]|]+)?(?:\|([^\[\]]+))?\]\]/g,
      (_, target, heading, alias) => {
        const name = target.trim();
        const resolved = ctx.resolveLink ? ctx.resolveLink(name) : null;
        const exists = resolved && resolved.path;
        const label = (alias || name).trim();
        const suffix = heading ? `<span class="wl-heading">${heading}</span>` : "";
        return hold(
          `<a class="wikilink${exists ? "" : " is-missing"}" data-wikilink="${escapeHtml(name)}" data-path="${escapeHtml(exists ? resolved.path : "")}" data-heading="${escapeHtml((heading || "").replace(/^#/, ""))}" href="#">${label}${suffix}</a>`
        );
      }
    );

    // tags
    text = text.replace(/(^|[\s(])#([A-Za-z][\w/\-]{0,63})/g, (_, lead, tag) =>
      `${lead}${hold(`<a class="tag" data-tag="${escapeHtml(tag)}" href="#">#${tag}</a>`)}`
    );

    // bold / italic / strike / highlight
    text = text
      .replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*((?:(?!\n[ \t]*\n)[^*])+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/(^|[^_\w])_((?:(?!\n[ \t]*\n)[^_])+)_(?![\w_])/g, "$1<em>$2</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>")
      .replace(/==([^=]+)==/g, "<mark>$1</mark>");

    // bare urls
    text = text.replace(/(^|[\s(])(https?:\/\/[^\s<"]+)/g, (_, lead, url) => {
      const clean = url.replace(/[.,;:!?)]+$/, "");
      const tail = url.slice(clean.length);
      return `${lead}${hold(
        `<a href="${clean}" class="external" target="_blank" rel="noreferrer">${clean}</a>`
      )}${tail}`;
    });

    return text
      .split(PH)
      .map((part, index) =>
        index % 2 === 1 ? slots[Number(part)] || "" : part
      )
      .join("");
  }

  // ---------------------------------------------------------------- blocks
  const FENCE = /^(```|~~~)\s*([\w+-]*)\s*$/;
  const HEADING = /^(#{1,6})\s+(.*)$/;
  const HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
  const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const TABLE_DIVIDER = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$/;
  const CALLOUT = /^\[!(\w+)\]\s*(.*)$/;

  function isBlockStart(line) {
    return (
      FENCE.test(line) ||
      HEADING.test(line) ||
      HR.test(line) ||
      /^\s*>/.test(line) ||
      LIST_ITEM.test(line) ||
      TABLE_DIVIDER.test(line)
    );
  }

  function renderList(items, ctx) {
    // items: [{indent, ordered, text, checkbox}]
    function parse(start, indent) {
      const ordered = items[start].ordered;
      let html = ordered ? "<ol>" : "<ul>";
      let i = start;
      while (i < items.length) {
        const item = items[i];
        if (item.indent < indent) break;
        if (item.indent === indent && item.ordered !== ordered) break;
        if (item.indent > indent) {
          const deeper = parse(i, item.indent);
          html += deeper.html;
          i = deeper.next;
          continue;
        }
        let prefix = "";
        if (item.checkbox === true) prefix = `<input type="checkbox" checked disabled> `;
        else if (item.checkbox === false) prefix = `<input type="checkbox" disabled> `;
        let inner = prefix + renderInline(item.text, ctx);
        i++;
        if (i < items.length && items[i].indent > indent) {
          const children = parse(i, items[i].indent);
          inner += children.html;
          i = children.next;
        }
        const cls = item.checkbox === null ? "" : ' class="task-item"';
        html += `<li${cls}>${inner}</li>`;
      }
      html += ordered ? "</ol>" : "</ul>";
      return { html, next: i };
    }
    if (!items.length) return "";
    let html = "";
    let index = 0;
    while (index < items.length) {
      const parsed = parse(index, items[index].indent);
      html += parsed.html;
      index = parsed.next > index ? parsed.next : index + 1;
    }
    return html;
  }

  function renderTable(rows, ctx) {
    const split = (row) =>
      row
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    const header = split(rows[0]);
    const align = split(rows[1]).map((cell) => {
      const left = cell.startsWith(":");
      const right = cell.endsWith(":");
      if (left && right) return "center";
      if (right) return "right";
      return left ? "left" : "";
    });
    const cell = (tag, content, index) =>
      `<${tag}${align[index] ? ` style="text-align:${align[index]}"` : ""}>${renderInline(content, ctx)}</${tag}>`;
    let html = "<table><thead><tr>";
    header.forEach((content, index) => (html += cell("th", content, index)));
    html += "</tr></thead><tbody>";
    for (let r = 2; r < rows.length; r++) {
      const row = split(rows[r]);
      html += "<tr>";
      for (let c = 0; c < header.length; c++) html += cell("td", row[c] || "", c);
      html += "</tr>";
    }
    return html + "</tbody></table>";
  }

  function renderBlocks(text, ctx) {
    const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    let html = "";
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (!line.trim()) {
        i++;
        continue;
      }

      // fenced code
      const fence = line.match(FENCE);
      if (fence) {
        const marker = fence[1];
        const lang = fence[2] || "";
        const body = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(marker)) {
          body.push(lines[i]);
          i++;
        }
        i++; // closing fence
        const code = escapeHtml(body.join("\n"));
        html += `<pre class="code-block"${lang ? ` data-lang="${escapeHtml(lang)}"` : ""}><code>${code}</code></pre>`;
        continue;
      }

      // horizontal rule
      if (HR.test(line)) {
        html += "<hr>";
        i++;
        continue;
      }

      // heading
      const heading = line.match(HEADING);
      if (heading) {
        const level = heading[1].length;
        const content = renderInline(heading[2].trim(), ctx);
        const id = slugify(heading[2]);
        html += `<h${level} id="${id}">${content}</h${level}>`;
        i++;
        continue;
      }

      // table
      if (line.includes("|") && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
        const headerRow = line;
        const dividerRow = lines[i + 1];
        i += 2;
        const bodyRows = [];
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
          bodyRows.push(lines[i]);
          i++;
        }
        html += renderTable([headerRow, dividerRow, ...bodyRows], ctx);
        continue;
      }

      // blockquote / callout
      if (/^\s*>/.test(line)) {
        const body = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          body.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        const callout = body.length ? body[0].match(CALLOUT) : null;
        if (callout) {
          const kind = callout[1].toLowerCase();
          const title = callout[2].trim() || kind.replace(/^\w/, (c) => c.toUpperCase());
          html += `<div class="callout callout-${kind}"><div class="callout-title">${escapeHtml(title)}</div><div class="callout-body">${renderBlocks(body.slice(1).join("\n"), ctx)}</div></div>`;
        } else {
          html += `<blockquote>${renderBlocks(body.join("\n"), ctx)}</blockquote>`;
        }
        continue;
      }

      // list
      if (LIST_ITEM.test(line)) {
        const items = [];
        while (i < lines.length && LIST_ITEM.test(lines[i])) {
          const match = lines[i].match(LIST_ITEM);
          let text = match[3];
          let checkbox = null;
          const task = text.match(/^\[([ xX])\]\s+(.*)$/);
          if (task) {
            checkbox = task[1].toLowerCase() === "x";
            text = task[2];
          }
          items.push({
            indent: match[1].replace(/\t/g, "  ").length,
            ordered: /^\d/.test(match[2]),
            text,
            checkbox,
          });
          i++;
          // continuation lines (indented, not a new item)
          while (i < lines.length && lines[i].trim() && !LIST_ITEM.test(lines[i]) && !isBlockStart(lines[i]) && /^\s{2,}/.test(lines[i])) {
            items[items.length - 1].text += " " + lines[i].trim();
            i++;
          }
        }
        html += renderList(items, ctx);
        continue;
      }

      // paragraph
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
        paragraph.push(lines[i]);
        i++;
      }
      if (!paragraph.length) {
        // safety: never loop forever
        html += `<p>${renderInline(lines[i] || "", ctx)}</p>`;
        i++;
        continue;
      }
      // soft-wrap: source lines flow into one paragraph, so emphasis, links and
      // code can span them. A line ending in two spaces or a backslash keeps a
      // hard break, which is how verse and address blocks stay on their lines.
      const segments = [];
      let current = "";
      paragraph.forEach((part) => {
        const hard = /( {2,}|\\)$/.test(part);
        const text = part.replace(/\s+$/, "");
        current = current ? `${current} ${text}` : text;
        if (hard) {
          segments.push(current);
          current = "";
        }
      });
      if (current) segments.push(current);
      const joined = segments.map((part) => renderInline(part, ctx)).join("<br>");
      html += `<p>${joined}</p>`;
    }

    return html;
  }

  function stripFrontmatter(text) {
    const match = String(text).match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
    if (!match) return { body: String(text), frontmatter: {} };
    const frontmatter = {};
    match[1].split(/\r?\n/).forEach((line) => {
      const pair = line.match(/^([\w-]+)\s*:\s*(.*)$/);
      if (pair) frontmatter[pair[1]] = pair[2].replace(/^["']|["']$/g, "");
    });
    return { body: String(text).slice(match[0].length), frontmatter };
  }

  function render(markdown, options) {
    const ctx = options || {};
    const { body, frontmatter } = stripFrontmatter(markdown || "");
    let html = renderBlocks(body, ctx);
    if (ctx.showProperties && Object.keys(frontmatter).length) {
      const rows = Object.entries(frontmatter)
        .map(
          ([key, value]) =>
            `<div class="prop"><span class="prop-key">${escapeHtml(key)}</span><span class="prop-value">${escapeHtml(value)}</span></div>`
        )
        .join("");
      html = `<div class="properties">${rows}</div>` + html;
    }
    return html;
  }

  function countWords(markdown) {
    const { body } = stripFrontmatter(markdown || "");
    const plain = body
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/[#>*_`~\[\]()|-]/g, " ")
      .trim();
    return plain ? plain.split(/\s+/).filter(Boolean).length : 0;
  }

  global.JadeliMD = { render, renderInline, countWords, stripFrontmatter, escapeHtml, slugify };
})(window);
