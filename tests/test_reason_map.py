"""Every reason code the state machine emits must have a readable label in the timeline."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def emitted_codes() -> set[str]:
    source = (ROOT / 'gsearch/state_constraints.py').read_text(encoding='utf8')
    codes = set(re.findall(r"_reject\('([a-z_]+)'", source))
    codes.update(re.findall(r"return \('([a-z_]+)'", source))
    codes.update(re.findall(r"return '([a-z_]+)'", source))
    codes.update(re.findall(r"return '([a-z_]+)'", source))
    # dynamic f-string code: f'{name}_already_used'
    codes.update({'search_papers_already_used', 'recommend_papers_already_used'})
    return codes


def mapped_codes() -> set[str]:
    script = (ROOT / 'research76/lab.js').read_text(encoding='utf8')
    block = re.search(r'const REASON_TEXT=\{(.*?)\n\};', script, re.S)
    if not block:
        raise AssertionError('REASON_TEXT map not found in lab.js')
    return set(re.findall(r'^([a-z_]+):\[', block.group(1), re.M))


class ReasonMapTests(unittest.TestCase):
    def test_every_emitted_code_has_a_label(self):
        missing = sorted(emitted_codes() - mapped_codes())
        self.assertEqual(missing, [], f'unlabelled reason codes: {missing}')

    def test_timeline_calls_the_decorator(self):
        script = (ROOT / 'research76/lab.js').read_text(encoding='utf8')
        self.assertIn('decorateReasons(row);', script)

    def test_summary_block_is_prepended(self):
        script = (ROOT / 'research76/lab.js').read_text(encoding='utf8')
        self.assertIn('host.prepend(box)', script)
        css = (ROOT / 'research76/workspace.css').read_text(encoding='utf8')
        self.assertIn('.reason-summary', css)
        self.assertIn('.reason-chip', css)


if __name__ == '__main__':
    unittest.main()
