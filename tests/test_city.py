import copy
import json
import threading
import time
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.engine import Manager, simulate, command, Cancelled, csv_report
from backend.model import validate, shortest, digest
from backend.tools import DependencyError, executable, versions


@pytest.fixture
def data():
    return json.loads(Path('backend/demo.json').read_text())


@pytest.fixture
def real_tools():
    # Missing system packages are a failure, never a skipped integration test.
    return versions()


def wait(manager, ident):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = manager.get(ident)
        if job['status'] in ('completed', 'failed', 'cancelled'):
            return job
        time.sleep(0.05)
    pytest.fail('Výpočet nedokončen v testovacím limitu')


def test_validation_and_direction(data):
    assert validate(data) == data
    assert shortest(data, 'most')[0] == ['prijezd', 'sever', 'objizdka', 'jih', 'nemocnice']
    assert shortest(data, 'prijezd') == ([], None)
    mutations = [lambda d: d['nodes'][1].update(x=0,y=0),
                 lambda d: d['edges'][0].update(target='missing'),
                 lambda d: d['edges'][0].update(speed=float('nan')),
                 lambda d: d.update(bus_departures=[120,0]),
                 lambda d: d.update(timezone='Unknown/Nowhere'),
                 lambda d: d['edges'][0].update(source='a',target='w')]
    for mutate in mutations:
        broken = copy.deepcopy(data); mutate(broken)
        with pytest.raises(ValueError):
            validate(broken)


def test_real_sumo_closure_and_reproducibility(data, tmp_path, real_tools):
    event = threading.Event()
    first = simulate(data, 'most', 17, 0.5, tmp_path/'first', event)
    second = simulate(data, 'most', 17, 0.5, tmp_path/'second', event)
    assert first == second
    assert first['completed'] > 0
    assert first['travel_s'] > 0
    assert first['edge_entries'].get('most',0) == 0
    assert first['edge_entries']['objizdka'] > 0
    baseline = simulate(data, None, 17, 0.5, tmp_path/'baseline', event)
    assert baseline['edge_entries']['most'] > 0
    assert first['hospital_freeflow_s'] > baseline['hospital_freeflow_s']
    assert first['completed'] + first['unfinished'] == 90 + len(data['bus_departures'])


def test_unreachable_is_not_zero(data, tmp_path):
    result = simulate(data, 'prijezd', 1, 1, tmp_path, threading.Event())
    assert result['hospital_freeflow_s'] is None
    assert result['travel_s'] is None
    assert result['unreachable'] == data['cars'] + len(data['bus_departures'])
    assert result['completed'] == 0


def test_completed_provenance_and_snapshot(data, tmp_path, real_tools):
    manager = Manager(tmp_path)
    try:
        before = digest(data)
        submitted = manager.submit(data,'most',[8],0.5)
        data['cars'] = 0
        job = wait(manager, submitted['id'])
        assert job['status'] == 'completed', job['error']
        assert job['input_sha256'] == before
        assert job['dataset']['cars'] == 180
        assert job['sumo_version'] == real_tools['sumo_version']
        assert len(job['scenario_sha256']) == 64
        assert 'variant' in csv_report(job)
        assert json.loads((tmp_path/job['id']/'job.json').read_text()) == job
    finally:
        manager.close()


def test_cancel_never_completed(data, tmp_path):
    manager = Manager(tmp_path)
    try:
        with manager.lock:
            job = manager.submit(data,'most',[1,2,3],1.5)
            manager.cancel(job['id'])
            with pytest.raises(ValueError):
                manager.submit(data,'most',[9],1)
        final = wait(manager, job['id'])
        assert final['status'] == 'cancelled'
        assert final['results'] == []
    finally:
        manager.close()


def test_cancel_running_process(tmp_path):
    event = threading.Event()
    timer = threading.Timer(0.2, event.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(Cancelled):
            command(['/usr/bin/sleep', '20'], tmp_path, event)
        assert time.monotonic() - start < 5
    finally:
        timer.cancel()


def test_failure_never_completed(data, tmp_path, monkeypatch):
    reached = threading.Event()
    def fail(*args, **kwargs):
        reached.set()
        raise RuntimeError('Testovaný pád simulátoru')
    # This unit test isolates the worker state machine, not the SUMO installation.
    # Real tool/version execution remains covered above without mocks.
    monkeypatch.setattr('backend.engine.versions', lambda: {})
    monkeypatch.setattr('backend.engine.simulate', fail)
    manager = Manager(tmp_path)
    try:
        job = wait(manager, manager.submit(data,'most',[1],1)['id'])
        assert reached.is_set()
        assert job['status'] == 'failed'
        assert job['results'] == []
        assert 'Testovaný pád' in job['error']
    finally:
        manager.close()


def test_missing_sumo_is_actionable_and_failed(data, tmp_path, monkeypatch):
    monkeypatch.setenv('CITY_SUMO_BIN', str(tmp_path/'missing'))
    with pytest.raises(DependencyError, match='apt-get install -y sumo'):
        executable('sumo')
    manager = Manager(tmp_path)
    try:
        job = wait(manager, manager.submit(data,'most',[1],1)['id'])
        assert job['status'] == 'failed'
        assert job['results'] == []
        assert 'Chybí spustitelný nástroj sumo' in job['error']
    finally:
        manager.close()


def test_custom_binary_directory(tmp_path, monkeypatch):
    binary = tmp_path/'netconvert'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    monkeypatch.setenv('CITY_SUMO_BIN', str(tmp_path))
    assert executable('netconvert') == str(binary.resolve())
    binary.chmod(0o644)
    with pytest.raises(DependencyError):
        executable('netconvert')


def test_restart_recovers_cancelling(tmp_path):
    ident = uuid4().hex
    folder = tmp_path/ident; folder.mkdir()
    (folder/'job.json').write_text(json.dumps({'id':ident,'status':'cancelling','results':[]}))
    manager = Manager(tmp_path)
    try:
        assert manager.get(ident)['status'] == 'failed'
    finally:
        manager.close()


def test_api_auth_limits_import(data, tmp_path):
    app = create_app(tmp_path, 'local-test-token')
    with TestClient(app) as client:
        assert client.get('/health').status_code == 401
        client.headers['X-City-Token'] = 'local-test-token'
        assert client.get('/dataset').json()['cars'] == 180
        assert client.put('/dataset', content='x'*262145).status_code == 413
        invalid = copy.deepcopy(data); invalid['bus_departures'] = [-1]
        assert client.put('/dataset', json=invalid).status_code == 422
        assert client.post('/jobs', json={'closed':'missing','seeds':[1],'factor':1}).status_code == 422
        assert client.post('/jobs', json={'closed':'most','seeds':[1,1],'factor':1}).status_code == 422
        assert client.put('/dataset', json=data).status_code == 200
        assert client.get('/jobs/unknown').status_code == 404
