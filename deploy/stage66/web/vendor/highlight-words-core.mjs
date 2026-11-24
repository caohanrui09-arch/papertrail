const b = ({
  chunks: n
}) => {
  const c = n.filter(
    ({ start: e, end: s }) => Number.isFinite(e) && Number.isFinite(s) && s > e
  ).sort(
    (e, s) => e.start - s.start || s.end - e.end
  ), i = [];
  let t;
  for (const { start: e, end: s, searchIndex: r } of c)
    t && e < t.end ? t.end = Math.max(t.end, s) : (t = { start: e, end: s, searchIndex: r }, i.push(t));
  return i;
};
function k({
  chunksToHighlight: n,
  totalLength: c
}) {
  const i = [], t = (r) => {
    r.end > r.start && i.push(r);
  }, e = (r) => Math.max(0, Math.min(r, c));
  let s = 0;
  for (const r of n) {
    if (!Number.isFinite(r.start) || !Number.isFinite(r.end))
      continue;
    const a = Math.max(s, e(r.start)), l = Math.max(a, e(r.end));
    t({ start: s, end: a, highlight: !1 }), t({ start: a, end: l, highlight: !0, searchIndex: r.searchIndex }), s = l;
  }
  return t({ start: s, end: c, highlight: !1 }), i;
}
function E(n) {
  return n;
}
function I({
  autoEscape: n,
  caseSensitive: c,
  sanitize: i = E,
  searchWords: t,
  textToHighlight: e
}) {
  const s = String(e ?? ""), { offsets: r, text: a } = R(s, i), l = c ? "g" : "gi", o = [];
  return (t ?? []).forEach((u, x) => {
    const f = w(
      u,
      n !== !1,
      l,
      i
    );
    if (f === null)
      return;
    const C = f.unicode || f.flags.includes("v");
    let g;
    for (; g = f.exec(a); ) {
      const d = g.index, h = f.lastIndex;
      h > d && o.push(
        r ? {
          start: r.start[d],
          end: r.end[h - 1],
          searchIndex: x
        } : {
          // Don't split surrogate pairs (e.g. emoji) between chunks
          start: p(s, d - 1) ? d - 1 : d,
          end: p(s, h - 1) ? h + 1 : h,
          searchIndex: x
        }
      ), g.index === f.lastIndex && (f.lastIndex += C && p(a, f.lastIndex) ? 2 : 1);
    }
  }), o;
}
function R(n, c) {
  const i = c(n);
  if (i === n)
    return { offsets: null, text: i };
  const t = { end: [], start: [] }, e = /* @__PURE__ */ new Map();
  let s = "", r = 0;
  for (const a of n) {
    const l = r + a.length;
    let o = e.get(a);
    if (o === void 0 && (o = c(a), e.set(a, o)), o.length === 0)
      for (let u = t.end.length - 1; u >= 0 && t.end[u] === r; u--)
        t.end[u] = l;
    for (let u = 0; u < o.length; u++)
      t.start.push(r), t.end.push(l);
    s += o, r = l;
  }
  return { offsets: t, text: s };
}
function w(n, c, i, t) {
  if (M(n))
    return new RegExp(
      n.source,
      "g" + n.flags.replace(/[gy]/g, "")
    );
  if (n == null)
    return null;
  const e = t(String(n));
  if (e === "")
    return null;
  if (c)
    return new RegExp(m(e), i);
  try {
    return new RegExp(e, i);
  } catch {
    return new RegExp(m(e), i);
  }
}
function M(n) {
  return Object.prototype.toString.call(n) === "[object RegExp]";
}
function p(n, c) {
  const i = n.charCodeAt(c), t = n.charCodeAt(c + 1);
  return i >= 55296 && i <= 56319 && t >= 56320 && t <= 57343;
}
function m(n) {
  return n.replace(/[-[\]/{}()*+?.\\^$|]/g, "\\$&");
}
function z({
  autoEscape: n,
  caseSensitive: c = !1,
  findChunks: i = I,
  sanitize: t = E,
  searchWords: e,
  textToHighlight: s
}) {
  return s = String(s ?? ""), e = e ?? [], k({
    chunksToHighlight: b({
      chunks: i({
        // Only an explicit false disables escaping (untyped callers may pass e.g. null)
        autoEscape: n !== !1,
        caseSensitive: c,
        sanitize: t,
        searchWords: e,
        textToHighlight: s
      })
    }),
    totalLength: s.length
  });
}
export {
  b as combineChunks,
  k as fillInChunks,
  z as findAll,
  I as findChunks
};
//# sourceMappingURL=highlight-words-core.js.map
