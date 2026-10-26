/* jadeli — a small force-directed graph on a canvas. No dependencies. */
(function (global) {
  "use strict";

  const PALETTE = ["#8b7cf6", "#4fd1c5", "#f6ad55", "#f687b3", "#63b3ed", "#68d391", "#b794f4", "#f6e05e"];

  function hashColor(key) {
    let hash = 0;
    for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }

  class GraphView {
    constructor(canvas, options) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.onOpen = (options && options.onOpen) || (() => {});
      this.nodes = [];
      this.edges = [];
      this.scale = 1;
      this.offset = { x: 0, y: 0 };
      this.drag = null;
      this.pan = null;
      this.hover = null;
      this.frame = 0;
      this.running = false;
      this.colors = { background: "#0f1117", text: "#c8cee0", dim: "#434b61", link: "#2a3145", edge: "#3a4360" };
      this._bind();
    }

    setTheme(theme) {
      this.colors =
        theme === "light"
          ? { background: "#f7f7fa", text: "#2a2f3a", dim: "#b6bcc9", link: "#c9cfdb", edge: "#cfd5e1" }
          : { background: "#0f1117", text: "#c8cee0", dim: "#434b61", link: "#2a3145", edge: "#3a4360" };
      this.draw();
    }

    setData(data, activePath) {
      const previous = new Map(this.nodes.map((node) => [node.id, node]));
      const nodes = (data.nodes || []).map((node) => {
        const old = previous.get(node.id);
        const degree = (data.edges || []).filter(
          (edge) => edge.source === node.id || edge.target === node.id
        ).length;
        return {
          ...node,
          x: old ? old.x : Math.cos(Math.random() * Math.PI * 2) * 220 + (Math.random() - 0.5) * 60,
          y: old ? old.y : Math.sin(Math.random() * Math.PI * 2) * 220 + (Math.random() - 0.5) * 60,
          vx: 0,
          vy: 0,
          degree,
          radius: 5 + Math.min(degree * 0.9, 10) + Math.min((node.words || 0) / 2500, 4),
          color: hashColor((node.tags && node.tags[0]) || node.path.split("/")[0] || "root"),
        };
      });
      const ids = new Set(nodes.map((node) => node.id));
      this.nodes = nodes;
      this.edges = (data.edges || []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      this.activePath = activePath;
      this.needsFit = true;
      this.draw();
    }

    start() {
      if (this.running) return;
      this.running = true;
      const tick = () => {
        if (!this.running) return;
        this.step();
        this.draw();
        this.frame = requestAnimationFrame(tick);
      };
      this.frame = requestAnimationFrame(tick);
    }

    stop() {
      this.running = false;
      if (this.frame) cancelAnimationFrame(this.frame);
      this.frame = 0;
    }

    resize() {
      const ratio = global.devicePixelRatio || 1;
      const rect = this.canvas.getBoundingClientRect();
      this.canvas.width = Math.max(1, Math.round(rect.width * ratio));
      this.canvas.height = Math.max(1, Math.round(rect.height * ratio));
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.width = rect.width;
      this.height = rect.height;
      this.draw();
    }

    step() {
      const nodes = this.nodes;
      if (!nodes.length) return;
      const charge = 900;
      const damping = 0.86;

      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let distance = Math.sqrt(dx * dx + dy * dy) || 1;
          if (distance > 620) continue;
          const force = charge / (distance * distance);
          const fx = (dx / distance) * force;
          const fy = (dy / distance) * force;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      this.edges.forEach((edge) => {
        const a = nodes.find((node) => node.id === edge.source);
        const b = nodes.find((node) => node.id === edge.target);
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        const desired = 120;
        const force = (distance - desired) * 0.006;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });

      nodes.forEach((node) => {
        // gentle pull to the centre keeps disconnected notes on screen
        node.vx += -node.x * 0.0009;
        node.vy += -node.y * 0.0009;
        if (this.drag && this.drag.node === node) return;
        node.vx *= damping;
        node.vy *= damping;
        node.x += Math.max(-12, Math.min(12, node.vx));
        node.y += Math.max(-12, Math.min(12, node.vy));
      });
    }

    fit() {
      if (!this.nodes.length) return;
      const xs = this.nodes.map((node) => node.x);
      const ys = this.nodes.map((node) => node.y);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const padding = 90;
      const width = Math.max(1, maxX - minX + padding * 2);
      const height = Math.max(1, maxY - minY + padding * 2);
      this.scale = Math.min(1.4, Math.min(this.width / width, this.height / height));
      this.offset.x = this.width / 2 - ((minX + maxX) / 2) * this.scale;
      this.offset.y = this.height / 2 - ((minY + maxY) / 2) * this.scale;
      this.needsFit = false;
    }

    toScreen(node) {
      return { x: node.x * this.scale + this.offset.x, y: node.y * this.scale + this.offset.y };
    }

    toWorld(x, y) {
      return { x: (x - this.offset.x) / this.scale, y: (y - this.offset.y) / this.scale };
    }

    draw() {
      const ctx = this.ctx;
      if (!this.width || !this.height) return;
      if (this.needsFit) this.fit();
      ctx.fillStyle = this.colors.background;
      ctx.fillRect(0, 0, this.width, this.height);

      if (!this.nodes.length) {
        ctx.fillStyle = this.colors.text;
        ctx.font = "14px 'Segoe UI', system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("No notes to graph yet.", this.width / 2, this.height / 2);
        return;
      }

      const positions = new Map();
      this.nodes.forEach((node) => positions.set(node.id, this.toScreen(node)));

      ctx.strokeStyle = this.colors.edge;
      ctx.lineWidth = 1;
      this.edges.forEach((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return;
        const touchesHover = this.hover && (edge.source === this.hover.id || edge.target === this.hover.id);
        ctx.globalAlpha = this.hover ? (touchesHover ? 0.9 : 0.18) : 0.5;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });
      ctx.globalAlpha = 1;

      this.nodes.forEach((node) => {
        const point = positions.get(node.id);
        const isActive = node.path === this.activePath;
        const isHover = this.hover && this.hover.id === node.id;
        ctx.globalAlpha = this.hover && !isHover ? 0.45 : 1;
        ctx.beginPath();
        ctx.arc(point.x, point.y, Math.max(3, node.radius * this.scale), 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();
        if (isActive) {
          ctx.lineWidth = 2;
          ctx.strokeStyle = "#ffffff";
          ctx.stroke();
        }
        if ((this.scale > 0.55 && node.degree > 0) || isActive || isHover) {
          ctx.fillStyle = isHover || isActive ? this.colors.text : this.colors.text;
          ctx.font = `${isHover || isActive ? 600 : 400} ${Math.max(10, Math.min(13, 11 * this.scale + 2))}px 'Segoe UI', system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.globalAlpha = isHover || isActive ? 1 : 0.72;
          const label = node.title.length > 28 ? node.title.slice(0, 27) + "…" : node.title;
          ctx.fillText(label, point.x, point.y + node.radius * this.scale + 13);
        }
      });
      ctx.globalAlpha = 1;
    }

    hitTest(x, y) {
      let best = null;
      let bestDistance = Infinity;
      this.nodes.forEach((node) => {
        const point = this.toScreen(node);
        const distance = Math.hypot(point.x - x, point.y - y);
        const radius = Math.max(10, node.radius * this.scale + 4);
        if (distance <= radius && distance < bestDistance) {
          best = node;
          bestDistance = distance;
        }
      });
      return best;
    }

    _bind() {
      const canvas = this.canvas;

      canvas.addEventListener("mousedown", (event) => {
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        const node = this.hitTest(x, y);
        if (node && event.button === 0) {
          this.drag = { node, x0: x, y0: y, moved: false };
        } else {
          this.pan = { x, y, ox: this.offset.x, oy: this.offset.y };
        }
      });

      canvas.addEventListener("mousemove", (event) => {
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        if (this.drag) {
          const world = this.toWorld(x, y);
          this.drag.node.x = world.x;
          this.drag.node.y = world.y;
          this.drag.node.vx = 0;
          this.drag.node.vy = 0;
          if (Math.hypot(x - this.drag.x0, y - this.drag.y0) > 4) this.drag.moved = true;
          this.draw();
          return;
        }
        if (this.pan) {
          this.offset.x = this.pan.ox + (x - this.pan.x);
          this.offset.y = this.pan.oy + (y - this.pan.y);
          this.draw();
          return;
        }
        const hovered = this.hitTest(x, y);
        if ((hovered && (!this.hover || hovered.id !== this.hover.id)) || (!hovered && this.hover)) {
          this.hover = hovered;
          canvas.style.cursor = hovered ? "pointer" : "grab";
          this.draw();
        }
      });

      const end = () => {
        if (this.drag && !this.drag.moved) this.onOpen(this.drag.node.path);
        this.drag = null;
        this.pan = null;
      };
      canvas.addEventListener("mouseup", end);
      canvas.addEventListener("mouseleave", () => {
        this.drag = null;
        this.pan = null;
        if (this.hover) {
          this.hover = null;
          this.draw();
        }
      });

      canvas.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          const rect = canvas.getBoundingClientRect();
          const x = event.clientX - rect.left;
          const y = event.clientY - rect.top;
          const before = this.toWorld(x, y);
          const factor = event.deltaY < 0 ? 1.12 : 0.89;
          this.scale = Math.max(0.2, Math.min(4, this.scale * factor));
          const after = this.toScreen(before);
          this.offset.x += x - after.x;
          this.offset.y += y - after.y;
          this.draw();
        },
        { passive: false }
      );

      canvas.addEventListener("dblclick", () => {
        this.fit();
        this.draw();
      });
    }
  }

  global.JadeliGraph = GraphView;
})(window);
