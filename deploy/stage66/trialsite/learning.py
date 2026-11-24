"""Read-only, source-bound editorial paths over the unchanged trial catalog."""
import json
import os
from pathlib import Path
from typing import Literal

from fastapi.staticfiles import StaticFiles
from .app import create_app as base_app, main as base_main

ROOT=Path(__file__).resolve().parents[1]


def create_app(settings=None):
    app=base_app(settings)
    catalog=app.state.catalog
    definitions=json.loads((ROOT/'learning-paths.json').read_text(encoding='utf-8'))
    results={}
    for topic,path in definitions['paths'].items():
        papers=[]
        if len(path['papers'])!=3 or len({r['doc_id'] for r in path['papers']})!=3:
            raise ValueError('Three distinct path papers required')
        for position,step in enumerate(path['papers'],1):
            original=catalog.read(step['doc_id'])
            if not step['evidence'] or step['evidence'] not in original['abstract']:
                raise ValueError('Editorial evidence is not an exact original abstract span: '+step['doc_id'])
            papers.append({**catalog.paper(step['doc_id']),'rank':position,'review':None,
                'learning':{k:v for k,v in step.items() if k!='doc_id'}|{'position':position}})
        results[topic]={'papers':papers,'query':path['title'],'topic':topic,'history':[],'review_applies':False,
            'guide':{k:v for k,v in path.items() if k!='papers'}|{'scope':definitions['scope'],'topic':topic},
            'catalog_key':catalog.catalog_key,'message':'编辑建议顺序，可跳读；收藏后可到“我的推荐”继续探索。打开摘要不记作已读。',
            'trace':[{'tool':'编辑阅读路径','selection':'editorial_original_abstract','topic':topic,
                      'ordered_ids':[p['doc_id'] for p in papers],'source_verified':True,
                      'automatic_difficulty_score':False,'used_for_search_or_recommendation_ranking':False}]}
    app.state.learning_paths=results
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'name',None)!='trial-web' and getattr(r,'path',None)!='/api/health']

    @app.get('/api/health')
    def health():
        return {'status':'ready','catalog':len(catalog.catalog),'llm_enabled':False,'release':'stage40',
                'instance_id':os.environ.get('PAPERTRAIL_INSTANCE','manual')}

    @app.get('/api/learning-path/{topic}')
    def learning_path(topic:Literal['generative','cold','bias']):
        return results[topic]

    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='learning-web')
    return app


if __name__=='__main__':
    base_main(factory=create_app)
