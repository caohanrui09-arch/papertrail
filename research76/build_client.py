"""Concatenate local classic display adapters; no dynamic evaluation or new framework."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    names=['task-report.js','workspace-core.js','task-export-ui.js']
    (ROOT/'workspace.js').write_text('\n'.join((ROOT/name).read_text(encoding='utf8') for name in names)+'\n',encoding='utf8')
if __name__=='__main__':main()
