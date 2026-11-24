"""Create independently owned launchers and an explicit link to annotation UI."""
from pathlib import Path


def main():
    target=Path('scripts/annotation_workbench_control.py')
    if target.exists():raise ValueError('Versioned launcher already prepared')
    target.write_text(Path('scripts/personal_workbench_control.py').read_text(encoding='utf-8')
        .replace('stage24','stage26').replace('8768','8769').replace('gsearch.personal_workbench','gsearch.annotation_workbench'),encoding='utf-8')
    Path('annotation-workbench.cmd').write_text(Path('personal-workbench.cmd').read_text().replace('scripts.personal_workbench_control','scripts.annotation_workbench_control'))
    target=Path('web/papertrail-v26/dist/app.mjs')
    source=target.read_text(encoding='utf-8')
    old='onClick=${showQuality}><${Icon} name="Check"/>人工评价准备</button>'
    assert old in source
    source=source.replace(old,"onClick=${()=>{location.href='/label';}}><${Icon} name=\"Check\"/>需求确认与盲标<span class=\"small-count\">9</span></button>")
    target.write_text(source,encoding='utf-8')


if __name__=='__main__':main()
