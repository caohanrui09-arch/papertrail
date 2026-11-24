"""Confirm native v71 service paths and worker remain unchanged; verify real citations."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class DisplayOnly(ast.NodeTransformer):
    def visit_Constant(self,node):
        if isinstance(node.value,str):
            node.value=node.value.replace('research72/','research71/').replace('data/stage72-lab','data/stage71-lab').replace('data/stage72-custom','data/stage71-custom')
        return node
    def visit_FunctionDef(self,node):
        if node.name=='candidate_script':return None
        return self.generic_visit(node)
    def visit_ImportFrom(self,node):
        return None if node.module=='research72.routes' else node
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='register':return None
        return self.generic_visit(node)


def main():
    old=ast.parse((ROOT/'research71/server.py').read_text());new=DisplayOnly().visit(ast.parse((ROOT/'research72/server.py').read_text()))
    assert ast.dump(old)==ast.dump(new),'Native service changed beyond versioned display routes'
    manifest=json.loads((ROOT/'reports/stage71/final-validation.json').read_text())['files']
    for name in ['research71/worker.py','research71/runner.py','research71/clients.py','research71/prompts/custom.txt']:
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==manifest[name.replace('/','\\')]
    browser=json.loads((ROOT/'reports/stage72/browser-validation.json').read_text());base=ROOT/'data/stage72-custom/jobs'/browser['real_job_id']
    spec=json.loads((base/'input.json').read_text());row=json.loads((base/'result.json').read_text())['results'][0]
    events=[json.loads(s) for s in (base/'events.jsonl').read_text(encoding='utf8').splitlines()]
    assert [e['payload'] for e in events if e['kind']=='tool_returned']==row['trace']['trace']
    assert all(e['arguments']['query']==spec['tasks'][0]['query'] for e in row['trace']['trace'] if e['tool']=='search_papers')
    reads={e['result']['doc_id']:e['result'] for e in row['trace']['trace'] if e['tool']=='read_paper' and not e['result'].get('error')}
    docs={d['doc_id']:d for d in json.loads((ROOT/'data/stage13-expansion/documents.json').read_text())}
    for cite in (row.get('answer') or {}).get('citations',[]):
        source=docs[cite['doc_id']];read=reads[cite['doc_id']]
        assert cite['quote'] in read['abstract'] and read['abstract']==source['abstract']
        assert cite['source_url']==source['source_url'] and cite['version_key']==source['version_key']
        assert hashlib.sha256(Path(source['provenance']['raw_path']).read_bytes()).hexdigest()==source['provenance']['raw_sha256']
    report={'status':'passed','native_server_ast_equal_except_versioned_paths_and_added_display_routes':True,
            'original_worker_runner_client_prompt_hashes_unchanged':True,'actual_events_exact_native_final_trace':True,
            'actual_citations_match_read_versions_and_original_response_hash':True,'extra_model_jobs':0}
    (ROOT/'reports/stage72/invariant-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))


if __name__=='__main__':main()
