"""Create a new editable UI version without overwriting sealed stage23 files."""
from pathlib import Path
import shutil


def main():
    target = Path('web/papertrail-v24/dist')
    if target.exists():
        raise ValueError('Version already exists')
    shutil.copytree('web/papertrail/dist', target)
    source = Path('gsearch/workbench_service.py').read_text(encoding='utf-8')
    source = source.replace("web/papertrail/dist", "web/papertrail-v24/dist").replace('data/stage23-web', 'data/stage24-personal')
    source = source.replace('default=8767', 'default=8768')
    Path('gsearch/personal_workbench.py').write_text(source, encoding='utf-8')
    source = Path('scripts/workbench_control.py').read_text(encoding='utf-8')
    source = source.replace('stage23', 'stage24').replace('8767', '8768').replace('gsearch.workbench_service', 'gsearch.personal_workbench')
    Path('scripts/personal_workbench_control.py').write_text(source, encoding='utf-8')
    source = Path('workbench.cmd').read_text().replace('scripts.workbench_control', 'scripts.personal_workbench_control')
    Path('personal-workbench.cmd').write_text(source)


if __name__ == '__main__':
    main()
