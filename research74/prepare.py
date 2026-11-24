"""Create a versioned presentation surface without changing frozen experiments."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = ROOT/'reports/stage74'
    report.mkdir(parents=True, exist_ok=True)
    (ROOT/'.cache/stage74').mkdir(parents=True, exist_ok=True)
    baseline = {}
    for stage in (71, 72, 73):
        frozen = json.loads((ROOT/f'reports/stage{stage}/final-validation.json').read_text(encoding='utf8'))
        hashes = frozen['files'] if 'files' in frozen else frozen['sha256'] if 'sha256' in frozen else frozen['file_sha256']
        for name, expected in hashes.items():
            if name in ('project-agent.cmd', 'papertrail-workbench.cmd'):
                continue
            actual = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            assert actual == expected, name
            baseline[name] = actual
    for path in (ROOT/'data/stage73-evaluation').rglob('*'):
        if path.is_file() and ('agent-runs' in path.parts or 'inputs' in path.parts or path.name in ('protocol.json', 'labeling-lock.json', 'runtime.json')):
            baseline[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = report/'before.json'
    if output.exists():
        assert json.loads(output.read_text(encoding='utf8')) == baseline, 'Baseline changed'
    else:
        output.write_text(json.dumps(baseline, indent=2), encoding='utf8')
    copies = {
        'research73/server.py': [('research73', 'research74'), ('research72/candidate-ui.js', 'research74/candidate-ui.js'), ('research72/lab.js', 'research74/lab.js')],
        'research73/control.py': [('research73', 'research74')],
        'research73/activate.py': [("('research72.control','stop'),('research73.control','start')", "('research73.control','stop'),('research74.control','start')")],
        'research73/candidate_routes.py': [('research73.diagnostics', 'research74.diagnostics')],
        'research73/diagnostics.py': [('data/stage73-evaluation/diagnostics', 'data/stage74-diagnostics')],
        'research73/site.py': [('research73/evaluation.', 'research74/evaluation.')],
        'research73/lab.html': [],
        'research73/evaluation.html': [],
        'research73/evaluation.js': [],
        'research72/candidate-ui.js': [],
        'research72/lab.js': [],
        'research73/browser_helpers.cjs': [('stage73', 'stage74')],
        'research73/http_regression.py': [('reports/stage73', 'reports/stage74')],
    }
    for source, replacements in copies.items():
        dest = ROOT/'research74'/Path(source).name
        assert not dest.exists(), str(dest)
        value = (ROOT/source).read_text(encoding='utf8')
        for old, new in replacements:
            value = value.replace(old, new)
        dest.write_text(value, encoding='utf8')
    print(json.dumps({'verified_frozen_files': len(baseline), 'new_adapters': len(copies)}))


if __name__ == '__main__':
    main()
