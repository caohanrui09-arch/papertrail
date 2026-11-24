"""Replace machine-specific absolute paths in publishable text files.

- old project root -> <repo>
- C:\\Users\\<name> -> <home>
Reports, data, cache and the personal resume docs are left untouched.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {'.cache', 'data', 'runs', '__pycache__', 'reports'}
TEXT = {'.md', '.cmd', '.txt', '.py', '.js', '.mjs', '.cjs', '.json', '.html', '.css', '.in', '.lock'}
OLD_ROOT = re.compile(r'C:\\Users\\[A-Za-z0-9_.-]+\\Documents\\ChatGPT\\搜广推\\generative-search-agent', re.I)
HOME = re.compile(r'C:\\Users\\[A-Za-z0-9_.-]+', re.I)


def main() -> None:
    changed = {}
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(part in EXCLUDE for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT:
            continue
        try:
            text = path.read_text(encoding='utf8')
        except (UnicodeDecodeError, OSError):
            continue
        original = text
        text = OLD_ROOT.sub('<repo>', text)
        text = HOME.sub('<home>', text)
        if text != original:
            path.write_text(text, encoding='utf8')
            changed[path.relative_to(ROOT).as_posix()] = original.count('C:\\Users') - text.count('C:\\Users')
    print(f'files changed: {len(changed)}')
    for name, count in sorted(changed.items(), key=lambda kv: -kv[1])[:15]:
        print(f'  {count:>3}  {name}')


if __name__ == '__main__':
    main()
