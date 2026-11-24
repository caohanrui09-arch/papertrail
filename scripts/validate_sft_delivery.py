"""Stage45 final audit and immutable local-only delivery receipt."""
import json
from pathlib import Path
import re
import subprocess

from gsearch.quality_protocol import digest,save

ROOT=Path('reports/stage45')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    final=ROOT/'final-validation.json'
    if final.exists():
        receipt=read(final)
        for path,expected in receipt['files'].items():
            assert digest(Path(path))==expected,path
        print({'verified_existing':True,'assets':len(receipt['files']),'sha256':digest(final)})
        return
    lock=read(ROOT/'run-lock.json');checks={};inherited=[]
    for path,expected in lock['files'].items():assert digest(Path(path))==expected,path
    for stage in [43,44]:
        old=read(Path(f'reports/stage{stage}/final-validation.json'))
        entries={path:expected for group in old.values() if isinstance(group,dict)
                 for path,expected in group.items() if isinstance(expected,str) and len(expected)==64}
        assert entries
        for path,expected in entries.items():assert digest(Path(path))==expected,path
        inherited.extend(Path(path) for path in entries)
        inherited.append(Path(f'reports/stage{stage}/final-validation.json'))
        checks['stage'+str(stage)+'_assets_unchanged']=len(entries)
    scores=read(ROOT/'tuning-results.json')
    assert len(scores['all_comparisons'])==9
    for name,result in scores['all_comparisons'].items():
        assert result['events']==46352 and result['users']==3571
        assert result['valid_slot_rate']==1 and result['duplicate_slot_rate']==0
        detail=read(ROOT/(name+'.tuning.score.json'))
        assert detail['original_metric_source_sha256']==digest(Path('gsearch/supervision.py'))
        assert detail['scoring_lock_sha256']==digest(ROOT/'scoring-lock.json')
    checks['nine_full_denominator_evaluations']=True
    checks['all_predictions_valid_unique_slots']=True
    mappings={a:read(Path('data/stage45-sft')/(a+'.tokens.json')) for a in ['content','shuffled']}
    raw_profiles={r['user_key']:r for r in map(json.loads,Path('data/stage44-supervision/profiles.jsonl').read_text().splitlines())}
    traces=0;timings=[]
    for seed in [42,2024,3407]:
        initial=[]
        for arm in ['content','shuffled']:
            run=Path('runs/stage45')/(arm+'-'+str(seed));meta=read(run/'training.json')
            assert meta['optimizer_updates']==128 and meta['samples']==1024 and meta['supervised_tokens']==5120
            assert meta['observed_exact_order'] is True and meta['run_lock_sha256']==digest(ROOT/'run-lock.json')
            assert meta['completed_unix']-meta['elapsed_seconds']>lock['frozen_unix']
            assert digest(run/'final/model.safetensors')==meta['model_sha256']
            initial.append(meta['initial_embedding_sha256']);timings.append(meta['elapsed_seconds'])
            raw=read(run/'raw-user-decoding.json')
            for user,trace in raw.items():
                assert len(trace['doc_ids'])==10 and len(set(trace['doc_ids']))==10
                assert not set(trace['doc_ids']).intersection(raw_profiles.get(user,{}).get('seen_doc_ids',[]))
                if not trace['fallback']:
                    assert trace['token_ids']==[mappings[arm][d] for d in trace['doc_ids']]
                    assert all(tokens[-1]==1 and len(tokens)==5 for tokens in trace['token_ids'])
                    traces+=1
        assert initial[0]==initial[1]
    checks.update(six_run_exact_budget_and_order=True,three_seed_initializations_paired=True,
                  original_token_decoding_profiles_verified=traces,training_seconds=sum(timings),
                  no_dev_prediction_or_scoring=not list(Path('runs/stage45').rglob('*dev*')))
    assert checks['no_dev_prediction_or_scoring']
    before=read(Path('.cache/stage44/gpu-packages-before-stage45.json'))
    after=read(ROOT/'gpu-packages-after.json')
    assert before==after
    checks['shared_cuda_packages_unchanged']=len(before)
    for kind,expected in [('cpu',57),('web',26)]:
        packages=read(ROOT/(kind+'-packages-after.json'))
        assert len(packages)==expected
        normalize=lambda name:re.sub(r'[-_.]+','-',name).lower()
        actual={normalize(row['name']):row['version'] for row in packages}
        requirement=Path('reports/stage17/requirements-win-cpu.lock') if kind=='cpu' else Path('deploy/stage43/requirements.lock')
        matched=0
        for line in requirement.read_text(encoding='utf-8-sig').splitlines():
            match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^ ;]+)',line.strip().rstrip('\\').strip())
            if match:
                assert actual[normalize(match[1])]==match[2]
                matched+=1
        assert matched>20
        checks[kind+'_package_count_and_locked_versions']={'installed':expected,'locked_entries_checked':matched}
    probe=subprocess.run(['git','check-ignore','data/stage45-sft/content.train.tokens.jsonl','runs/stage45/content-42/final/model.safetensors'],capture_output=True,text=True)
    assert probe.returncode==0 and len(probe.stdout.splitlines())==2
    checks['private_data_and_models_git_ignored']=True
    assert read(ROOT/'data-validation.json')['status']=='passed'
    assert read(ROOT/'preflight.json')['passed']
    assert read(ROOT/'real-scoring-equivalence.json')['status']=='passed'
    checks['real_scoring_equivalence_comparisons']=len(read(ROOT/'real-scoring-equivalence.json')['comparisons'])
    save(ROOT/'release-validation.json',{'status':'passed','checks':checks,
        'scope':'local licensed research delivery, not a public redistribution bundle',
        'sft_completed':True,'rl_started':False,'website_changed':False,'fresh_test':False})
    paths=[Path('gsearch/sid_sft.py'),Path('tests/test_sid_sft.py')]+inherited
    paths.extend(Path('scripts').glob('*sid_sft.py'))
    paths.append(Path('scripts/validate_sft_delivery.py'))
    paths.append(Path('scripts/freeze_sft_baselines.py'))
    paths.extend([Path('gsearch/sid_scoring.py'),Path('tests/test_sid_scoring.py'),
                  Path('scripts/score_sid_sft_fast.py'),Path('scripts/validate_sid_scoring.py')])
    paths.extend(p for p in ROOT.iterdir() if p.is_file() and p.name!='final-validation.json')
    paths.extend(p for p in Path('data/stage45-sft').rglob('*') if p.is_file())
    paths.extend(p for p in Path('runs/stage45').rglob('*') if p.is_file())
    paths.extend([Path('docs/SID_SFT_V45.md'),Path('reports/阶段45_SID与受控SFT试验.md')])
    unique={str(p):digest(p) for p in sorted(set(paths))}
    save(final,{'status':'passed','scope':'local-only research; no public data/model distribution',
        'checks':checks,'files':unique})
    print({'status':'passed','assets':len(unique),'receipt_sha256':digest(final),'checks':checks})


if __name__=='__main__':main()
