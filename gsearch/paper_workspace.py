"""Add verified preview metadata only; original search and preference routes stay intact."""
from datetime import datetime
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .topic_gallery import create_app as gallery_app
from .metadata_fetch import upstream


def create_app():
    app = gallery_app()
    engine = app.state.personal_catalog.engine
    parser = upstream()
    parsed = {}
    for raw_path in {row['provenance']['raw_path'] for row in engine.by_id.values()}:
        parsed.update({item.entry_id.rsplit('/', 1)[-1]: item for item in parser._feed.parse(Path(raw_path).read_bytes()).results})
    previews = {}
    for doc, row in engine.by_id.items():
        original = engine.paper(doc)  # Existing raw-hash-verified reader.
        submitted = datetime.fromisoformat(row['published_at'])
        assert parsed[doc + 'v1'].published == submitted
        # Exact prefix of the original abstract. Ellipsis is presentation, never source text.
        end = min(420, len(original['abstract']))
        if end < len(original['abstract']):
            boundary = original['abstract'].rfind(' ', 280, end)
            if boundary >= 280:
                end = boundary
        previews[doc] = {'doc_id': doc, 'version_key': original['version_key'], 'title': original['title'],
                         'source_url': original['source_url'], 'source_name': 'arXiv',
                         'published_at': row['published_at'], 'submitted_year': submitted.year,
                         'date_kind': 'arxiv_first_submission', 'available_at': row['available_at'],
                         'abstract_excerpt': original['abstract'][:end], 'excerpt_truncated': end < len(original['abstract']),
                         'source_verified': original['source_verified']}

    @app.get('/api/paper-previews')
    def paper_previews():
        return {'catalog_key': app.state.personal_catalog.catalog_key, 'count': len(previews), 'papers': previews,
                'scope': '原v1摘要前缀；年份为arXiv首次提交年份；不改变检索与推荐排名'}

    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'name', None) != 'topic-gallery']
    app.mount('/', StaticFiles(directory='web/papertrail-v38/dist', html=True), name='paper-workspace')
    return app


if __name__ == '__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        uvicorn.run(create_app(), host='127.0.0.1', port=8780, access_log=False, ws='none')
