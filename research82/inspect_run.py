"""Print one stage82 run step by step (read-only) to explain a failure."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
value = json.loads((ROOT / 'data/stage82-batch/result.json').read_text(encoding='utf8'))
index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
result = value['results'][index]

print(f"task={result['task_id']} complete={result['completed_protocol']} "
      f"charged={result['metadata']['charged_application_attempts']} seconds={result['seconds']:.1f}")
print(f"llm_usage={result['metadata']['llm_usage']}")
for step in result['metadata']['steps']:
    error = (step.get('error') or {}).get('type') or ''
    message = (step.get('error') or {}).get('message') or ''
    output = step.get('model_output') or ''
    calls = step.get('tool_calls') or []
    print(f"\n--- step {step.get('step_number')} error={error} calls={len(calls)}")
    if output:
        print('  output: ' + output.replace('\n', ' ⏎ ')[:400])
    if message:
        print('  error : ' + message.replace('\n', ' ')[:300])
    for call in calls:
        print(f"  call  : {call}")
