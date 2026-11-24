// Render the real reason-summary code from research76/lab.js against a real failing
// trajectory, using a minimal DOM shim, and write a static HTML preview.
// Evidence only: the lab page runs the same functions inside the browser.
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const lab = fs.readFileSync(path.join(root, 'research76/lab.js'), 'utf8');
const start = lab.indexOf('const REASON_TEXT={');
const end = lab.indexOf('function renderTimeline(row)');
if (start < 0 || end < 0) throw new Error('reason code block not found');

// --- minimal DOM -------------------------------------------------------------
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.className = ''; this.dataset = {};
    this.title = ''; this._text = ''; this.parent = null;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  append(...nodes) { for (const n of nodes) { n.parent = this; this.children.push(n); } }
  prepend(node) { node.parent = this; this.children.unshift(node); }
  remove() {
    if (this.parent) { this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  }
  matches(selector) {
    return selector.split('.').filter(Boolean).every((cls) => this.className.split(/\s+/).includes(cls));
  }
  walk() {
    const out = [];
    for (const child of this.children) out.push(child, ...child.walk());
    return out;
  }
  querySelector(selector) { return this.walk().find((n) => n.matches(selector)) || null; }
  querySelectorAll(selector) { return this.walk().filter((n) => n.matches(selector)); }
}

const document = { createElement: (tag) => new Node(tag) };
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
};

const host = new Node('div');
const $ = (id) => (id === 'timeline' ? host : null);
const factory = new Function('$', 'el', 'document',
  `${lab.slice(start, end)}; return { decorateReasons };`);
const { decorateReasons } = factory($, el, document);

// --- real failing run (stage82 batch, e73-empty, run 3) -----------------------
const batch = JSON.parse(fs.readFileSync(path.join(root, 'data/stage82-batch/result.json'), 'utf8'));
const run = batch.results[3];
const row = {
  trace: {
    trace: [
      { tool: 'search_papers', attempt: 1, result: { papers: [] } },
      { tool: 'finalize', attempt: 2, result: { error: 'Check final_check failed with error: reason=final_citation_count action=final_answer expected exactly 0 citation(s) for intent=search with returned=0; got 2 | attempts=1/6 rejected=0' } },
      { tool: 'search_papers', attempt: 3, result: { error: 'Unknown tool search_papers, should be one of: final_answer.' } },
    ],
  },
  metadata: { proposal_events: run.metadata.proposal_events },
};
for (const attempt of [1, 2, 3]) {
  const item = el('li', '', 'event ' + (attempt === 2 || attempt === 3 ? 'failed' : ''));
  item.dataset.attempt = String(attempt);
  item.append(el('div', '', 'event-head'));
  host.append(item);
}
decorateReasons(row);

// --- serialise ---------------------------------------------------------------
const escape = (value) => String(value).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function serialize(node) {
  if (typeof node === 'string') return escape(node);
  const attrs = [`class="${node.className}"`];
  if (node.dataset.reason) attrs.push(`data-reason="${node.dataset.reason}"`);
  if (node.title) attrs.push(`title="${escape(node.title)}"`);
  const inner = node.children.length ? node.children.map(serialize).join('') : escape(node._text);
  return `<${node.tag} ${attrs.join(' ')}>${inner}</${node.tag}>`;
}
const body = serialize(host);
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>失败原因渲染预览 · stage84</title>
<link rel="stylesheet" href="../../research76/workspace.css">
<body style="max-width:900px;margin:40px auto;font:14px/1.7 system-ui,sans-serif;color:#333">
<h1 style="font-size:20px">失败原因渲染预览（真实 e73-empty 轨迹）</h1>
<p style="color:#666;font-size:12px">由 research76/lab.js 的 decorateReasons() 真实执行生成，使用同一份 workspace.css；用于核对徽标与汇总条。</p>
${body}
</body></html>`;
const out = path.join(root, 'reports/stage84/reason-summary-preview.html');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, html);
console.log(JSON.stringify({
  written: out,
  failed_proposals: row.metadata.proposal_events.filter((e) => e.error).length,
  summary_html: body.slice(0, 320),
}, null, 2));
