import html
import json
import os
import secrets
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from .engine import Manager, csv_report
from .model import canonical, validate
from .tools import versions


def create_app(root, token):
    manager = Manager(root)
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            manager.close()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager
    dataset_path = Path(root) / 'dataset.json'
    app.state.dataset = validate(json.loads((dataset_path if dataset_path.exists() else Path(__file__).with_name('demo.json')).read_text()))

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if not secrets.compare_digest(request.headers.get('X-City-Token', ''), token):
            return Response('Unauthorized', status_code=401)
        if request.method in ('PUT', 'POST'):
            total, chunks = 0, []
            async for chunk in request.stream():
                total += len(chunk)
                if total > 262144:
                    return Response('Limit těla je 256 KiB', status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        return await call_next(request)

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.get('/dataset')
    def get_dataset():
        return app.state.dataset

    @app.put('/dataset')
    async def put_dataset(request: Request):
        try:
            data = validate(await request.json())
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from None
        tmp = dataset_path.with_suffix('.tmp')
        tmp.write_text(canonical(data), encoding='utf8'); tmp.replace(dataset_path)
        app.state.dataset = data
        return data

    @app.post('/jobs')
    async def start(request: Request):
        try:
            body = await request.json()
            closed, seeds, factor = body['closed'], body['seeds'], body['factor']
            if not isinstance(closed, str) or closed not in {e['id'] for e in app.state.dataset['edges']}:
                raise ValueError('Neznámý úsek')
            if not isinstance(seeds, list) or not 1 <= len(seeds) <= 3 or any(type(s) is not int or not 0 <= s <= 1000000 for s in seeds) or len(set(seeds)) != len(seeds):
                raise ValueError('Zadejte 1–3 různá celočíselná semínka 0–1000000')
            if type(factor) not in (float, int) or not 0.5 <= factor <= 1.5:
                raise ValueError('Násobek poptávky musí být 0.5–1.5')
            return manager.submit(app.state.dataset, closed, seeds, factor)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    def lookup(ident):
        try:
            return manager.get(ident)
        except KeyError:
            raise HTTPException(404, 'Běh neexistuje') from None

    @app.get('/jobs/{ident}')
    def job(ident: str):
        return lookup(ident)

    @app.post('/jobs/{ident}/cancel')
    def cancel(ident: str):
        lookup(ident)
        return manager.cancel(ident)

    @app.get('/jobs/{ident}/export/{fmt}')
    def export(ident: str, fmt: str):
        job = lookup(ident)
        if job['status'] != 'completed':
            raise HTTPException(409, 'Běh není dokončen')
        if fmt == 'csv':
            return Response(csv_report(job), media_type='text/csv; charset=utf-8')
        if fmt != 'html':
            raise HTTPException(404)
        report = '<!doctype html><html lang="cs"><meta charset="utf-8"><title>CITY FORGE</title><h1>CITY FORGE — nekalibrovaná demonstrace</h1><p>Uzavírka: 0–900 s. Nemocnice: volná cesta bez kolon, přednosti a výjezdu posádky. Není určeno pro operační rozhodování. Rozptyl semínek není interval spolehlivosti. Průměry jízd a stání zahrnují jen dokončená vozidla.</p><pre>' + html.escape(json.dumps(job, ensure_ascii=False, indent=2)) + '</pre></html>'
        return Response(report, media_type='text/html; charset=utf-8')
    return app


if __name__ == '__main__':
    import uvicorn
    token = os.environ.get('CITY_TOKEN')
    if not token:
        raise SystemExit('Chybí lokální autentizační token')
    # Fail before advertising readiness; desktop displays the installation remedy.
    try:
        versions()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    application = create_app(os.environ['CITY_DATA'], token)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0)); sock.listen(128)
    print('CITY_PORT=' + str(sock.getsockname()[1]), flush=True)
    try:
        uvicorn.Server(uvicorn.Config(application, log_level='warning')).run(sockets=[sock])
    finally:
        application.state.manager.close()
        sock.close()
