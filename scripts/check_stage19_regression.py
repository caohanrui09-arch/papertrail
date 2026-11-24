"""Run the complete existing suite once and preserve its private transcript."""
import contextlib
from pathlib import Path
import unittest
from .prepare_stage19_tasks import save


def main() -> None:
    log = Path('.cache/stage19/regression-tests.log')
    output = Path('reports/stage19/regression-validation.json')
    if log.exists() or output.exists(): raise ValueError('Preserve prior verification attempt')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w', encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    save(output, {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'passed': result.wasSuccessful(), 'log_private': str(log)})
    if not result.wasSuccessful(): raise ValueError('Regression failed; see preserved private log')
    print(f'{result.testsRun} tests passed', flush=True)


if __name__ == '__main__': main()
