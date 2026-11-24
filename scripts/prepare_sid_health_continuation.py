"""Freeze the precision-context correction and reuse existing beam outputs."""
import json
from pathlib import Path

from gsearch.quality_protocol import digest,save


def main() -> None:
    root=Path('reports/stage47');data=Path('data/stage47-health');target=root/'continuation-lock.json'
    if target.exists():raise FileExistsError('Continuation already frozen')
    reused={str(p):digest(p) for p in sorted(data.glob('*/history-probe.json'))}
    files=[Path('scripts/continue_sid_health_probe.py'),Path('scripts/prepare_sid_health_continuation.py'),
           Path('tests/test_sid_health_precision.py')]
    evidence=[root/'first-attempt.log',root/'numerical-diagnosis.log',data/'content-42/loss-diagnostic-first8.json']
    files.extend(p for p in evidence if p.exists());files.extend(Path(p) for p in reused)
    diagnosed=(data/'content-42/loss-diagnostic-first8.json').exists()
    save(target,{'frozen_before_continued_inference':True,'original_protocol_sha256':digest(root/'protocol.json'),
        'scope':'precision-context alignment only; weights, samples, decoder, conditions, FP32 diagnostics unchanged',
        'reason':'Native BF16-AMP CE and explicit FP32 CE differ slightly; same-AMP direct CE agrees with native model.loss',
        'replacement_check':'compare native model.loss to AMP unreduced CE mean, still absolute tolerance1e-4; FP32 analysis separately labelled',
        'reused_history_files':reused,'reused_beam_requests':64*len(reused),'total_unique_beam_request_cap':384,
        'numerical_diagnostic_forward_samples':8 if diagnosed else 0,
        'interrupted_teacher_samples_upper_bound':32 if (root/'first-attempt.log').exists() else 0,
        'failure_accounting':'Interrupted run lacks a saved batch index; conservatively retain upper bound32, plus the explicit8-sample diagnosis; do not hide retry overhead',
        'optimizer_updates':0,'files':{str(p):digest(p) for p in sorted(files)}})
    print({'continuation':'frozen','reused_beam_requests':64*len(reused),'sha256':digest(target)},flush=True)


if __name__=='__main__':main()
