"""Final acceptance includes test-log success, preserving every initial asset."""
import json
from pathlib import Path
import re

from gsearch.quality_protocol import digest,save

ROOT=Path('reports/stage45')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    target=ROOT/'final-validation-v2.json'
    if target.exists():
        receipt=read(target)
        for path,expected in receipt['files'].items():assert digest(Path(path))==expected,path
        print({'verified_existing':True,'assets':len(receipt['files']),'sha256':digest(target)})
        return
    previous=read(ROOT/'final-validation.json')
    for path,expected in previous['files'].items():assert digest(Path(path))==expected,path
    corrected=read(ROOT/'packaging-correction.json')
    assert corrected['initial_receipt_sha256']==digest(ROOT/'final-validation.json')
    assert corrected['tests_passed']==10
    for path,count in [(ROOT/'tests.log',18),(ROOT/'frozen-evaluation-tests.log',20),
                       (ROOT/'scoring-equivalence-tests-v2.log',10)]:
        text=path.read_text(encoding='utf-8-sig')
        assert re.search(r'Ran '+str(count)+r' tests? in ',text)
        assert re.search(r'\nOK\s*$',text) and 'FAILED' not in text
    assert read(ROOT/'real-scoring-equivalence.json')['status']=='passed'
    checks=dict(previous['checks'])
    checks.update(boundary_and_equivalence_tests_passed=48,original_298_assets_preserved=True,
                  initial_packaging_failure_preserved_and_corrected=True)
    files=dict(previous['files'])
    for path in [ROOT/'final-validation.json',ROOT/'packaging-correction.json',ROOT/'scoring-equivalence-tests-v2.log',
                 Path('scripts/validate_sft_delivery_v2.py'),Path('docs/SID_SFT_V45_DELIVERY_ADDENDUM.md')]:
        files[str(path)]=digest(path)
    save(target,{'status':'passed','scope':'local research only; corrected final acceptance',
        'supersedes_receipt_sha256':digest(ROOT/'final-validation.json'),'checks':checks,'files':files})
    print({'status':'passed','assets':len(files),'sha256':digest(target),'tests_passed':48,
           'all_model_data_predictions_and_scores_unchanged':True})


if __name__=='__main__':main()
