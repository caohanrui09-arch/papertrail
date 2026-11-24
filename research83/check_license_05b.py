"""Fetch licence fields for the local 0.5B ladder point (local weights, remote licence text)."""
import json
import urllib.request

REPO = 'Qwen/Qwen2.5-0.5B-Instruct'
REV = '7ae557604adf67be50417f59c2c2f167def9a775'


def read(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


licence = read(f'https://huggingface.co/{REPO}/raw/{REV}/LICENSE')
card = read(f'https://huggingface.co/{REPO}/raw/{REV}/README.md')
fields = [line.strip() for line in card.splitlines() if line.lower().startswith('license')]
print(json.dumps({'repo': REPO, 'revision': REV,
                  'apache2': 'Apache License' in licence and 'Version 2.0' in licence,
                  'research_licence': 'RESEARCH LICENSE' in licence.upper(),
                  'card': fields}, ensure_ascii=False))
