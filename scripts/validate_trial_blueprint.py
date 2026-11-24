"""Validate deployment structure against Render's current published schema; no deployment."""
import hashlib
import json
from pathlib import Path
import urllib.request
import yaml
import jsonschema

ROOT=Path(__file__).resolve().parents[1]
url='https://render.com/schema/render.yaml.json'
with urllib.request.urlopen(url,timeout=30) as response: raw=response.read()
schema=json.loads(raw)
value=yaml.safe_load((ROOT/'deploy/stage39/render.yaml').read_text(encoding='utf-8'))
validator=jsonschema.validators.validator_for(schema)(schema)
errors=[{'path':list(error.path),'message':error.message} for error in validator.iter_errors(value)]
(ROOT/'.cache/stage39/render-schema.json').write_bytes(raw)
result={'status':'passed' if not errors else 'failed','schema_url':url,'schema_sha256':hashlib.sha256(raw).hexdigest(),
        'errors':errors,'scope':'published JSON Schema structure only; no platform/account-aware validation or resource creation'}
(ROOT/'reports/stage39/blueprint-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(result)
if errors:raise SystemExit(1)
