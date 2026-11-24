"""Fetch licence text and model-card licence fields for the two compared models."""
import urllib.request

MODELS = {
    'Qwen2.5-1.5B-Instruct': ('Qwen/Qwen2.5-1.5B-Instruct', '989aa7980e4cf806f80c7fef2b1adb7bc71aa306'),
    'Qwen2.5-3B-Instruct': ('Qwen/Qwen2.5-3B-Instruct', 'aa8e72537993ba99e69dfaafa59ed015b17504d1'),
}


def read(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


for name, (repo, rev) in MODELS.items():
    licence = read(f'https://huggingface.co/{repo}/raw/{rev}/LICENSE')
    card = read(f'https://huggingface.co/{repo}/raw/{rev}/README.md')
    fields = [line.strip() for line in card.splitlines() if line.lower().startswith('license')]
    print(f'--- {name} @ {rev[:12]}')
    print('  header   :', licence[:90].replace('\n', ' '))
    print('  apache2  :', 'Apache License' in licence and 'Version 2.0' in licence)
    print('  research :', 'RESEARCH LICENSE' in licence.upper())
    print('  card     :', fields)
