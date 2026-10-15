"""Optional authenticated SOC satellite routes; no API key reaches clients."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import os
import secrets
import time

from aiohttp import web

from argus.satellite_workspace import SatelliteWorkspace, DEFAULT_QUESTION
from argus.satellite_scan import CoastalScan


def install(app, require, body):
    root = os.environ.get('ARGUS_SATELLITE_ROOT')
    workspace = SatelliteWorkspace(root) if root else None
    scanner = CoastalScan(workspace) if workspace else None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='argus-satellite')
    jobs = {}
    running = set()
    last_request = {}

    def access(request):
        require(request, 'evidence.share')
        if workspace is None:
            raise web.HTTPServiceUnavailable(text='Satellite analysis is not configured on this host')
        return request['user']['id']

    async def status(request):
        require(request, 'evidence.share')
        if workspace is None:
            return web.json_response({'enabled': False, 'configured': False, 'automatic': False})
        result = await asyncio.to_thread(workspace.status)
        return web.json_response({'enabled': True, **result})

    async def scenes(request):
        access(request)
        result = await asyncio.to_thread(workspace.list_scenes)
        return web.json_response({'scenes': result})

    async def contacts(request):
        access(request)
        return web.json_response({'contacts': await asyncio.to_thread(workspace.contacts)})

    async def scan(request):
        access(request)
        require(request, admin=True)
        data = await body(request)
        if set(data) != {'action'} or data['action'] not in {'start', 'stop'}:
            raise ValueError('Choose start or stop; scan limits and credentials are host-managed')
        function = scanner.start if data['action'] == 'start' else scanner.stop
        return web.json_response(await asyncio.to_thread(function))

    async def crop(request):
        access(request)
        identifier = request.match_info['identifier']
        def read():
            return {'scene': workspace.scene(identifier),
                    'image_base64': base64.b64encode(workspace.image(identifier)).decode()}
        return web.json_response(await asyncio.to_thread(read))

    async def review(request):
        access(request)
        result = await asyncio.to_thread(workspace.review, request.match_info['identifier'])
        return web.json_response(result)

    async def submit(request):
        user = access(request)
        if running:
            raise web.HTTPConflict(text='A satellite job is already running on the host; try again after it finishes')
        now = time.monotonic()
        if now-last_request.get(user, -100) < 2:
            raise web.HTTPTooManyRequests(text='Wait two seconds before submitting another satellite job')
        data = await body(request)
        action = data.get('action')
        if action == 'search':
            sensor = data.get('sensor')
            area = data.get('bbox')
            start, end = data.get('start'), data.get('end')
            function = lambda: workspace.search(sensor, area, start, end)
        elif action == 'prepare':
            function = lambda: workspace.prepare(data.get('product_id'), data.get('bbox'))
        elif action == 'analyse':
            function = lambda: workspace.analyse(data.get('identifier'), data.get('question', DEFAULT_QUESTION))
        elif action == 'history':
            function = lambda: workspace.history(data.get('identifier'))
        else:
            raise ValueError('Unknown satellite job action')
        # Never accept URLs, host filesystem paths, credentials, model overrides,
        # arbitrary prompts longer than 500 chars, or budget changes from clients.
        last_request[user] = now
        for key in list(last_request):
            if now-last_request[key] > 600:
                last_request.pop(key)
        for key, job in list(jobs.items()):
            if now-job['created'] > 900 and key not in running:
                jobs.pop(key)
        if len(jobs) >= 32:
            raise web.HTTPTooManyRequests(text='Job result limit reached; wait for old results to expire')
        identifier = secrets.token_hex(16)
        jobs[identifier] = {'owner': user, 'created': now, 'status': 'running'}
        running.add(identifier)
        async def execute():
            try:
                result = await asyncio.get_running_loop().run_in_executor(executor, function)
                jobs[identifier].update(status='complete', result=result)
            except ValueError as error:
                jobs[identifier].update(status='failed', error=str(error)[:300])
            except Exception:
                # Do not leak archive paths, provider credentials or raw payloads.
                jobs[identifier].update(status='failed', error='Satellite job failed; check the host data and configuration')
            finally:
                running.discard(identifier)
        task = asyncio.create_task(execute())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return web.json_response({'job_id': identifier}, status=202)

    async def job(request):
        user = access(request)
        value = jobs.get(request.match_info['identifier'])
        if value is None or value['owner'] != user:
            raise web.HTTPNotFound(text='Satellite job not found')
        return web.json_response({k: v for k, v in value.items() if k not in {'owner', 'created'}})

    tasks = set()
    async def lifecycle(application):
        try:
            if scanner:
                try:
                    await asyncio.to_thread(scanner.resume)
                except (ValueError, OSError, ImportError):
                    pass  # Status/host controls remain available to recover.
            yield
        finally:
            if scanner:
                scanner.stop(suspend=True)
                if scanner.thread:
                    await asyncio.to_thread(scanner.thread.join, 45)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            executor.shutdown(wait=False, cancel_futures=True)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/v1/satellite/status', status)
    app.router.add_get('/v1/satellite/scenes', scenes)
    app.router.add_get('/v1/satellite/contacts', contacts)
    app.router.add_post('/v1/satellite/scan', scan)
    app.router.add_get('/v1/satellite/scenes/{identifier}/image', crop)
    app.router.add_get('/v1/satellite/scenes/{identifier}/review', review)
    app.router.add_post('/v1/satellite/jobs', submit)
    app.router.add_get('/v1/satellite/jobs/{identifier}', job)
