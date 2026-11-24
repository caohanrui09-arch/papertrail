// Stage84: verify the reason-label logic against retained real trajectories.
// Extracts the pure functions from research76/lab.js (no DOM needed) and replays
// the stage80-83 result files to check every produced code is labelled.
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'research76/lab.js'), 'utf8');
const start = script.indexOf('const REASON_TEXT={');
const end = script.indexOf('function decorateReasons(row)');
if (start < 0 || end < 0) throw new Error('reason block not found');

const factory = new Function(`${script.slice(start, end)}; return { reasonCode, reasonInfo, reasonsOf };`);
const { reasonCode, reasonInfo, reasonsOf } = factory();

const files = [
  'data/stage81-batch/result.json',
  'data/stage82-batch/result.json',
  'data/stage83-batch/result.json',
];

let runs = 0;
const seen = {};
const problems = [];
for (const rel of files) {
  const file = path.join(root, rel);
  if (!fs.existsSync(file)) continue;
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  for (const run of value.results || []) {
    runs += 1;
    const counts = reasonsOf(run);
    const expected = (run.metadata?.proposal_events || []).filter((e) => reasonCode(e.error)).length;
    const actual = Object.values(counts).reduce((n, v) => n + v, 0);
    if (actual !== expected) problems.push(`${rel} ${run.task_id}: counted ${actual} != proposals-with-errors ${expected}`);
    for (const [code, n] of Object.entries(counts)) {
      seen[code] = (seen[code] || 0) + n;
      const info = reasonInfo(code);
      if (!info || !info.label || info.label === '其他失败') problems.push(`${rel} ${run.task_id}: unlabelled code ${code}`);
    }
  }
}

console.log(JSON.stringify({ runs, codes: seen, problems }, null, 2));
process.exit(problems.length ? 1 : 0);
