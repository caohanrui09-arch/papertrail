"""Source-frozen CPU prefix baseline versus two archived model budgets."""
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

from gsearch.quality_protocol import digest,save
from gsearch.sid_prefix_prior import ROOT,DATA,read,fit_prefix_counts,context_prior,query_prefix
from gsearch.sid_prior_probe import prior_nll


def json_rows(path: Path):
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():yield json.loads(line)


def main() -> None:
    if ROOT.exists() or DATA.exists():raise FileExistsError('Preserve any prior stage51 attempt')
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_prior_probe'],check=True)
    ROOT.mkdir(parents=True);DATA.mkdir(parents=True)
    runs=read(Path('reports/stage50/protocol.json'))['models']
    files=[Path('reports/stage50/final-validation.json'),Path('reports/stage50/summary.json'),
        Path('data/stage50-health/prefixes.json'),Path('data/stage50-health/prefix-exposure.json'),
        Path('data/stage50-health/position-priors.json'),Path('gsearch/sid_prior_probe.py'),Path('gsearch/sid_prefix_prior.py'),
        Path('scripts/compare_sid_prefix_prior.py'),Path('scripts/validate_sid_prefix_prior.py'),Path('tests/test_sid_prefix_prior.py')]
    for arm in ['content','shuffled']:
        files.extend([Path('data/stage48-budget')/(arm+'.ordered.jsonl'),Path('data/stage45-sft')/(arm+'.tokens.json')])
    for run in runs:files.extend(Path('data/stage50-health')/run/name for name in ['reference128-rescored.json','position-loss.json'])
    protocol={'frozen_before_stage51_computation':True,'scope':'source-only posthoc health comparison, not ranking or independent quality evaluation',
        'prior_receipt_sha256':'4cdb8b98db5a983b05536b1fd50cc426db7cf3852adbec381a405274e9f56483',
        'training_labels':'exact first4096 frozen ordered raw-token labels, both SID arms; no user history in prior',
        'prefix':'all previous true target SID tokens, excluding current/future tokens',
        'smoothing':'Laplace alpha1 over full position codebook64/64/64/11/1, matching stored model position-conditional NLL',
        'unseen_prefix':'uniform over same full position codebook; no marginal backoff or catalog-child restriction',
        'sample_reuse':'unchanged32 strict training prefixes;32 users;16 events in4096,16 not; selected events retained in baseline training counts, no leave-one-out',
        'methods':['position4096_prior','prefix4096_prior','model128_archived','model512_archived'],
        'primary':'mean NLL of3 semantic positions on same32 samples, lower better; identity/EOS separate',
        'groups':['original event exposure','target paper exposure','history lengths1/20'],
        'decision':'if no512 run has semantic mean NLL lower than its matching prefix prior by>1e-12, close current budget-escalation route; otherwise describe mixed evidence and defer training, no personalization claim',
        'information_limit':'prefix prior sees gold previous SID as teacher forcing does, but no encoder history; model128 has1024 labels versus prior/model5124096; training-prefix diagnostic only',
        'forbidden':['training','model load or forward','new generation','dev or full tuning replay','old asset edits','new packages','website changes','RL'],
        'files':{str(p):digest(p) for p in sorted(set(files))}}
    assert digest(files[0])==protocol['prior_receipt_sha256']
    save(ROOT/'protocol.json',protocol)
    started=time.perf_counter();prefixes=read(Path('data/stage50-health/prefixes.json'))
    metadata={r['sample_id']:r for r in read(Path('data/stage50-health/prefix-exposure.json'))}
    marginal=read(Path('data/stage50-health/position-priors.json'));queries={};tables={}
    positions=['semantic1','semantic2','semantic3','identity','eos']
    for arm in ['content','shuffled']:
        labels=[r['labels'] for r in json_rows(Path('data/stage48-budget')/(arm+'.ordered.jsonl'))]
        assert len(labels)==4096
        allowed=[r['allowed_ids'] for r in marginal[arm]['4096']]
        tables[arm]=fit_prefix_counts(labels,allowed)
        save(DATA/(arm+'.prefix-counts.json'),tables[arm])
        empty=context_prior(tables[arm][0],[])
        assert empty==marginal[arm]['4096'][0]
        mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'));query_rows=[]
        for sample in prefixes:
            tokens=mapping[sample['target_doc_id']];sid=sample['sample_id']
            for pos,token in enumerate(tokens):
                answer=query_prefix(tables[arm][pos],tokens[:pos],token)
                query_rows.append({'sample_id':sid,'position_index':pos,'position':positions[pos],
                    'prefix_ids':tokens[:pos],'target_token_id':token,'marginal_nll':prior_nll(marginal[arm]['4096'][pos],token),
                    'prefix_nll':answer['nll'],'uniform_nll':math.log(len(allowed[pos])),
                    **{k:v for k,v in answer.items() if k!='nll'},'history_length':sample['history_length'],**metadata[sid]})
        queries[arm]={(r['sample_id'],r['position_index']):r for r in query_rows}
        with (DATA/(arm+'.queries.jsonl')).open('x',encoding='utf-8',newline='\n') as handle:
            for row in query_rows:handle.write(json.dumps(row,separators=(',',':'))+'\n')
    groups=['all','event:first1024','event:not_selected4096','history1','history20',
            'paper:first1024','paper:added1025to4096','paper:not_labelled4096']
    all_rows=[];summary={}
    for run in runs:
        arm=run.split('-')[0]
        old=read(Path('data/stage50-health')/run/'reference128-rescored.json')['samples']
        new=read(Path('data/stage50-health')/run/'position-loss.json')['samples']
        assert [r['sample_id'] for r in old]==[r['sample_id'] for r in new]==[r['sample_id'] for r in prefixes]
        records=[]
        for a,b in zip(old,new):
            for pos,(left,right) in enumerate(zip(a['positions'],b['positions'])):
                query=queries[arm][(a['sample_id'],pos)]
                assert left['target_token_id']==right['target_token_id']==query['target_token_id']
                assert abs(left['label4096_position_prior_nll']-query['marginal_nll'])<1e-12
                assert abs(right['label4096_position_prior_nll']-query['marginal_nll'])<1e-12
                records.append({**query,'model128_nll':left['position_conditional_nll'],'model512_nll':right['position_conditional_nll']})
        with (DATA/(run+'.comparison.jsonl')).open('x',encoding='utf-8',newline='\n') as handle:
            for row in records:handle.write(json.dumps(row,separators=(',',':'))+'\n')
        for group in groups:
            subset=[r for r in records if group=='all' or group=='event:'+r['event_exposure'] or group=='paper:'+r['target_paper_exposure'] or group=='history'+str(r['history_length'])]
            for name in ['semantic_mean',*positions]:
                chosen=[r for r in subset if (name=='semantic_mean' and r['position_index']<3) or r['position']==name]
                if not chosen:continue
                means={field:statistics.mean(r[field] for r in chosen) for field in ['marginal_nll','prefix_nll','model128_nll','model512_nll','uniform_nll']}
                row={'run':run,'group':group,'position':name,'samples':len({r['sample_id'] for r in chosen}),'token_records':len(chosen),
                    **means,'unseen_prefix_records':sum(not r['context_seen'] for r in chosen),
                    'model512_minus_prefix_nll':means['model512_nll']-means['prefix_nll']}
                all_rows.append(row)
                if group=='all' and name=='semantic_mean':summary[run]=row
        print({'compared':run,'semantic':summary[run]},flush=True)
    with (ROOT/'four-method-comparison.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(all_rows[0]));writer.writeheader();writer.writerows(all_rows)
    beats=[run for run,r in summary.items() if r['model512_nll']<r['prefix_nll']-1e-12]
    decision={'status':'current_budget_escalation_route_closed' if not beats else 'diagnosis_complete_mixed_evidence_training_deferred',
        'all_six_primary_comparisons':summary,'model512_runs_beating_prefix_prior':beats,'closure_condition_met':not beats,
        'training_branch':'closed_for_current_design' if not beats else 'deferred','new_training_started':False,
        'new_decode_or_model_forward':False,'rl_started':False,'dev_evaluated':False,'default_changed':False,
        'personalization_proven':False,'default':'existing content recommendation',
        'next':'archive evidence and resume wording; reopen only with a separately justified hypothesis and frozen design, not more steps by default'}
    save(ROOT/'decision.json',decision)
    save(ROOT/'comparison.json',{'protocol_sha256':digest(ROOT/'protocol.json'),'summary':summary,
        'unique_prefix_queries':320,'referenced_model_token_losses':1920,'wide_comparison_records':960,
        'aggregated_rows':len(all_rows),'unchanged_strict_prefixes':32,'seconds':time.perf_counter()-started,
        'no_model_load_fit_forward_generate':True,'decision':decision})
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    print({'comparison':'complete','beats_prefix':beats,'decision':decision['status'],'seconds':time.perf_counter()-started},flush=True)


if __name__=='__main__':main()
