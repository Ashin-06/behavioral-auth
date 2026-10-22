// Behaviour capture: timing and movement only. Key *classes* are recorded, never
// the characters, so passwords and account numbers are not collected.
(function () {
  const buf = [];
  const now = () => Math.round(performance.now() * 10) / 10;
  const cls = (k) => (/^[a-z]$/i.test(k) ? "letter" : /^[0-9]$/.test(k) ? "digit" : k === " " ? "space"
    : k === "Backspace" ? "back" : k === "Shift" ? "shift" : "other");
  const field = (el) => (el && (el.name || el.id)) || "page";

  addEventListener("keydown", (e) => { if (!e.repeat) buf.push({ t: now(), type: "kd", k: cls(e.key), f: field(e.target), i: (e.target.value || "").length }); }, true);
  addEventListener("keyup", (e) => buf.push({ t: now(), type: "ku", k: cls(e.key), f: field(e.target), i: Math.max((e.target.value || "").length - 1, 0) }), true);
  addEventListener("pointermove", (e) => buf.push({ t: now(), type: "mm", x: e.clientX, y: e.clientY }), { capture: true, passive: true });
  addEventListener("pointerdown", (e) => buf.push({ t: now(), type: "md", x: e.clientX, y: e.clientY }), true);
  addEventListener("pointerup", (e) => buf.push({ t: now(), type: "mu", x: e.clientX, y: e.clientY }), true);
  addEventListener("paste", (e) => buf.push({ t: now(), type: "paste", f: field(e.target) }), true);
  addEventListener("focusin", (e) => buf.push({ t: now(), type: "focus", f: field(e.target) }), true);
  document.addEventListener("visibilitychange", () => buf.push({ t: now(), type: "vis", v: document.visibilityState }));

  // keyup index must match its keydown: re-pair by class+field in order
  window.Behaviour = {
    take() {
      const out = buf.splice(0, buf.length);
      const open = {};
      for (const ev of out) {
        const key = ev.k + "|" + ev.f;
        if (ev.type === "kd") (open[key] = open[key] || []).push(ev);
        if (ev.type === "ku") { const d = (open[key] || []).shift(); if (d) ev.i = d.i; }
      }
      return out;
    },
  };
})();
