"""Seal frozen-model health evidence and verify the complete prior receipt chain."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest, save

ROOT = Path('reports/stage47')
DATA = Path('data/stage47-health')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_files(files):
    for name, expected in files.items():
        assert digest(Path(name)) == expected, name


def test_log(name, count):
    text = (ROOT / name).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    assert re.search(rf'Ran {count} tests in ', text), name
    assert re.search(r'\nOK\s*$', text) and 'FAILED' not in text, name


def main():
    old = [
        ('reports/stage45/final-validation-v2.json', '2e7bf16a10f196f42cde8ce2bd75055f3e611951b3ecbbcef73d91d879bf0949', 303),
        ('reports/stage46/final-validation.json', 'dbf11f3f9a9012b510b616211ecd4332af90b1b151052b8b0b2e4395f1ae2142', 38),
    ]
    for path, expected, count in old:
        assert digest(Path(path)) == expected, path
        previous = read(path)
        assert len(previous['files']) == count
        verify_files(previous['files'])
    protocol = read(ROOT / 'protocol.json')
    lock = read(ROOT / 'continuation-lock.json')
    assert digest(ROOT / 'protocol.json') == lock['original_protocol_sha256']
    verify_files(protocol['files'])
    verify_files(lock['files'])
    target = ROOT / 'final-validation.json'
    if target.exists():
        receipt = read(target)
        assert receipt['status'] == 'passed'
        verify_files(receipt['files'])
        print({'verified_existing': True, 'health_assets': len(receipt['files']),
               'prior_assets_unchanged': 341, 'sha256': digest(target)})
        return
    test_log('data-tests.log', 7)
    test_log('continued-tensor-tests.log', 12)
    validation = read(ROOT / 'validation.json')
    assert validation['status'] == 'passed'
    checks = {'profiles_source_and_same_length_permutation': 32, 'strict_prefix_sources': 32,
              'beam_requests': 384, 'legal_intermediate_prefixes': 19200,
              'native_ancestry_links': 19200, 'token_position_records': 960,
              'native_amp_mean_checks': 24, 'weight_digests_unchanged': 6}
    for key, expected in checks.items():
        assert validation[key] == expected, key
    assert validation['no_reinference_or_optimization_in_validation']
    execution = read(ROOT / 'execution.json')
    assert execution['status'] == 'complete' and execution['optimizer_updates'] == 0
    assert execution['protocol_sha256'] == digest(ROOT / 'protocol.json')
    assert execution['continuation_lock_sha256'] == digest(ROOT / 'continuation-lock.json')
    assert execution['beam_requests'] == 384 == execution['new_beam_requests_in_continuation'] + execution['reused_beam_requests']
    assert execution['reused_beam_requests'] == lock['reused_beam_requests']
    assert execution['successful_teacher_forced_samples'] == 192
    assert execution['numerical_diagnostic_forward_samples'] == lock['numerical_diagnostic_forward_samples']
    assert execution['interrupted_first_attempt_teacher_samples_upper_bound'] == lock['interrupted_teacher_samples_upper_bound']
    assert execution['teacher_forward_attempt_samples_upper_bound'] == 192 + lock['numerical_diagnostic_forward_samples'] + lock['interrupted_teacher_samples_upper_bound']
    assert len(execution['costs']) == 6
    for row in execution['costs']:
        assert row['in_memory_weights_before_sha256'] == row['in_memory_weights_after_sha256']
        assert row['all_gradients_none'] and row['all_parameters_frozen']
        assert row['gpu_reserved_peak_bytes'] <= protocol['resource_caps']['gpu_reserved_gib'] * 2**30
        assert row['process_peak_bytes'] <= protocol['resource_caps']['process_peak_gib'] * 2**30
    decision = read(ROOT / 'decision.json')
    assert not any(decision[k] for k in ['training_started', 'rl_started', 'dev_evaluated'])
    git = shutil.which('git')
    if git is None:
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists(): git = str(bundled)
    assert git, 'Git needed for private-path verification'
    private = [DATA / 'profiles.json', DATA / 'prefixes.json', DATA / 'paired-observations.csv']
    ignored = subprocess.run([git, 'check-ignore', *map(str, private)], check=True, capture_output=True, text=True)
    assert len(ignored.stdout.splitlines()) == len(private)
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    checks.update({'distinct_tests_passed': 19, 'prior_assets_unchanged': 341,
                   'optimizer_updates': 0, 'private_outputs_git_ignored': True,
                   'teacher_attempt_sample_upper_bound': execution['teacher_forward_attempt_samples_upper_bound'],
                   'full_logits_retained': False, 'new_training_started': False})
    paths = [Path('gsearch/sid_health_data.py'), Path('gsearch/sid_health_probe.py'),
             Path('docs/SID_HEALTH_PROBE_V47.md'), Path('reports/阶段47_冻结模型历史与损失探针.md')]
    paths.extend(Path('scripts').glob('*sid_health*.py'))
    paths.extend(Path('tests').glob('test_sid_health*.py'))
    paths.extend(p for p in ROOT.rglob('*') if p.is_file() and p != target)
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    files = {str(p): digest(p) for p in sorted(set(paths))}
    save(target, {'status': 'passed', 'scope': 'local frozen-model diagnostic; private derivatives not redistributable',
                  'checks': checks, 'files': files})
    print({'status': 'passed', 'health_assets': len(files), 'prior_assets_unchanged': 341,
           'sha256': digest(target), 'checks': checks})


if __name__ == '__main__':
    main()
