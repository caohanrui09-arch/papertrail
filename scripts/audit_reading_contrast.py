"""Compute contrast from explicit browser-computed text/background samples."""
import json
from pathlib import Path
from gsearch.quality_protocol import save


def luminance(channels: list[float]) -> float:
    values = [v / 255 for v in channels]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def main() -> None:
    path = Path('data/stage34-ui/computed-colors.json')
    samples = json.loads(path.read_text(encoding='utf-8'))
    assert len(samples) >= 20
    measured = []
    for row in samples:
        foreground = luminance(row['foreground'])
        background = luminance(row['background'])
        ratio = (max(foreground, background) + .05) / (min(foreground, background) + .05)
        measured.append({**row, 'contrast_ratio': ratio, 'threshold': 4.5, 'passed': ratio >= 4.5})
    save(Path('reports/stage34/contrast-validation.json'), {
        'status': 'passed' if all(row['passed'] for row in measured) else 'failed',
        'sample_count': len(measured), 'minimum_ratio': min(row['contrast_ratio'] for row in measured),
        'samples': measured, 'scope': 'sampled enabled workbench text only, not a whole-site WCAG conformance audit',
        'source': 'https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html',
    })
    assert all(row['passed'] for row in measured), [row['selector'] for row in measured if not row['passed']]
    print(json.dumps({'status': 'passed', 'samples': len(measured), 'minimum_ratio': min(row['contrast_ratio'] for row in measured)}))


if __name__ == '__main__':
    main()
