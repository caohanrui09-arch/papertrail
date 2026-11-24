"""Small stdlib contracts for the fixed SID budget comparison, no trainer rewrite."""
from pathlib import Path
import json

ROOT = Path('reports/stage48')
DATA = Path('data/stage48-budget')
RUNS = Path('runs/stage48')
SEEDS = [42, 2024, 3407]
ARMS = ['content', 'shuffled']


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require_reference(logs: list[dict], reference: list[dict]) -> int:
    actual = {r['step']: r for r in logs if 'loss' in r and r['step'] <= 128}
    expected = {r['step']: r for r in reference if 'loss' in r and r['step'] <= 128}
    if set(actual) != set(expected) or len(actual) != 8:
        raise ValueError('Missing 128-step reference loss observations')
    for step, row in expected.items():
        for key in ['loss', 'grad_norm', 'learning_rate']:
            if actual[step][key] != row[key]:
                raise ValueError(f'Reference mismatch at {step}:{key}')
    return len(actual)


def verify_seen_order(observed: list[int], total: int) -> None:
    if observed != list(range(total)):
        raise ValueError('Training stream duplicated, shuffled or incomplete')


def check_resources(measured: dict, seconds: float, caps: dict) -> None:
    if measured['gpu_reserved_bytes'] >= caps['gpu_reserved_gib'] * 2**30:
        raise MemoryError('GPU resource cap')
    if measured['process_peak_bytes'] >= caps['process_peak_gib'] * 2**30:
        raise MemoryError('Process resource cap')
    if seconds > caps['per_run_training_seconds']:
        raise TimeoutError('Training time cap')
