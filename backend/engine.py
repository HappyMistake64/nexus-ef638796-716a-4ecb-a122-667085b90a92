import csv
import io
import json
import os
import random
import re
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from .model import MODEL, HORIZON, canonical, digest, shortest
from .tools import executable, versions


class Cancelled(Exception):
    pass


def command(args, folder, cancel, timeout=50):
    if cancel.is_set():
        raise Cancelled()
    target = executable(args[0]) if args[0] in ('sumo', 'netconvert') else args[0]
    argv = [executable('prlimit'), '--as=1610612736', '--cpu=45', '--fsize=33554432', '--', target, *args[1:]]
    with open(folder / 'process.log', 'ab') as log:
        proc = subprocess.Popen(argv, cwd=folder, stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if cancel.wait(0.05):
                    raise Cancelled()
                if time.monotonic() > deadline:
                    raise RuntimeError('Překročen limit času procesu')
            if cancel.is_set():
                raise Cancelled()
            if proc.returncode:
                tail = (folder / 'process.log').read_text(errors='replace')[-2000:]
                raise RuntimeError('SUMO/netconvert selhal: ' + tail)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()


def xmlwrite(path, root):
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def simulate(data, closed, seed, factor, folder, cancel):
    if cancel.is_set():
        raise Cancelled()
    folder.mkdir(parents=True, exist_ok=True)
    route, hospital = shortest(data, closed)
    rng = random.Random(seed)
    departures = [(rng.uniform(0, 600), 'car', f'c{i}') for i in range(round(data['cars']*factor))]
    departures += [(t, 'bus', f'b{i}') for i, t in enumerate(data['bus_departures'])]
    departures.sort()
    requested = len(departures)
    if not route:
        return {'travel_s': None, 'bus_s': None, 'waiting_s': None, 'max_queue_m': None,
                'completed': 0, 'unreachable': requested, 'unfinished': 0,
                'hospital_freeflow_s': None, 'edge_entries': {}, 'route': []}
    nodes = ET.Element('nodes')
    for n in data['nodes']:
        ET.SubElement(nodes, 'node', id=n['id'], x=str(n['x']), y=str(n['y']), type='priority')
    edges = ET.Element('edges')
    for e in data['edges']:
        ET.SubElement(edges, 'edge', id=e['id'], **{'from': e['source'], 'to': e['target']},
                      speed=str(e['speed']), numLanes='1', priority='1')
    xmlwrite(folder / 'nodes.xml', nodes); xmlwrite(folder / 'edges.xml', edges)
    command(['netconvert', '--node-files', 'nodes.xml', '--edge-files', 'edges.xml',
             '--output-file', 'net.xml', '--no-turnarounds', 'true'], folder, cancel)
    routes = ET.Element('routes')
    ET.SubElement(routes, 'vType', id='car', vClass='passenger', sigma='0.5')
    ET.SubElement(routes, 'vType', id='bus', vClass='bus', length='12', accel='1.2', sigma='0.5')
    ET.SubElement(routes, 'route', id='chosen', edges=' '.join(route))
    for depart, kind, ident in departures:
        ET.SubElement(routes, 'vehicle', id=ident, type=kind, route='chosen',
                      depart=f'{depart:.3f}', departLane='best', departSpeed='0')
    xmlwrite(folder / 'routes.xml', routes)
    additional = ET.Element('additional')
    ET.SubElement(additional, 'edgeData', id='counts', file='edges-out.xml', begin='0', end=str(HORIZON))
    xmlwrite(folder / 'additional.xml', additional)
    command(['sumo', '--net-file', 'net.xml', '--route-files', 'routes.xml',
             '--additional-files', 'additional.xml', '--seed', str(seed), '--end', str(HORIZON),
             '--tripinfo-output', 'trips.xml', '--queue-output', 'queues.xml',
             '--time-to-teleport', '-1', '--no-step-log', 'true',
             '--duration-log.disable', 'true', '--xml-validation', 'never'], folder, cancel)
    trips = list(ET.parse(folder / 'trips.xml').getroot())
    cars = [float(t.attrib['duration']) for t in trips if t.attrib.get('vType') == 'car']
    buses = [float(t.attrib['duration']) for t in trips if t.attrib.get('vType') == 'bus']
    waits = [float(t.attrib['waitingTime']) for t in trips]
    queues = [float(l.attrib['queueing_length']) for l in ET.parse(folder / 'queues.xml').iter('lane')]
    entries = {e.attrib['id']: int(e.attrib.get('entered', '0')) + int(e.attrib.get('departed', '0'))
               for e in ET.parse(folder / 'edges-out.xml').iter('edge')}
    if closed and entries.get(closed, 0):
        raise RuntimeError('Porušení invariantu: průjezd uzavřeným úsekem')
    mean = lambda values: sum(values)/len(values) if values else None
    return {'travel_s': mean(cars), 'bus_s': mean(buses), 'waiting_s': mean(waits),
            'max_queue_m': max(queues, default=0), 'completed': len(trips), 'unreachable': 0,
            'unfinished': requested-len(trips), 'hospital_freeflow_s': hospital,
            'edge_entries': entries, 'route': route}


class Manager:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        self.jobs, self.events = {}, {}
        for path in self.root.glob('*/job.json'):
            try:
                job = json.loads(path.read_text())
                if not re.fullmatch('[a-f0-9]{32}', job['id']) or path.parent.name != job['id']:
                    continue
                if job['status'] in ('running', 'queued', 'cancelling'):
                    job.update(status='failed', error='Předchozí proces byl přerušen', results=[])
                    self.save(job)
                self.jobs[job['id']] = job
            except (ValueError, KeyError, TypeError, OSError):
                continue

    def save(self, job):
        folder = self.root / job['id']; folder.mkdir(exist_ok=True)
        tmp = folder / 'job.tmp'
        tmp.write_text(canonical(job), encoding='utf8')
        tmp.replace(folder / 'job.json')

    def submit(self, data, closed, seeds, factor):
        with self.lock:
            if len(self.jobs) >= 20:
                raise ValueError('Limit 20 uložených běhů. Při zavřené aplikaci archivujte datový adresář.')
            if any(j['status'] in ('queued', 'running', 'cancelling') for j in self.jobs.values()):
                raise ValueError('Již probíhá výpočet nebo jeho rušení')
            ident = uuid4().hex
            snapshot = json.loads(canonical(data))
            job = {'id': ident, 'status': 'queued', 'dataset': snapshot, 'input_sha256': digest(snapshot),
                   'model': MODEL, 'closed': closed, 'seeds': list(seeds), 'factor': factor,
                   'horizon_s': HORIZON, 'results': [], 'error': None}
            self.jobs[ident] = job; self.events[ident] = threading.Event(); self.save(job)
            self.pool.submit(self.work, ident)
            return self.get(ident)

    def get(self, ident):
        with self.lock:
            return json.loads(canonical(self.jobs[ident]))

    def cancel(self, ident):
        with self.lock:
            job = self.jobs[ident]
            if job['status'] in ('queued', 'running'):
                self.events[ident].set()
                job['status'] = 'cancelling'; self.save(job)
            return self.get(ident)

    def work(self, ident):
        job, event = self.jobs[ident], self.events[ident]
        try:
            with self.lock:
                if event.is_set():
                    raise Cancelled()
                job['status'] = 'running'; self.save(job)
            tool_versions = versions()
            results = []
            for seed in job['seeds']:
                pair = {'seed': seed}
                for label, closed in [('baseline', None), ('variant', job['closed'])]:
                    pair[label] = simulate(job['dataset'], closed, seed, job['factor'], self.root/ident/f'{seed}-{label}', event)
                results.append(pair)
            with self.lock:
                if event.is_set():
                    raise Cancelled()
                job.update(status='completed', results=results, **tool_versions)
                job['scenario_sha256'] = digest({k: job[k] for k in ('input_sha256', 'model', 'closed', 'seeds', 'factor', 'horizon_s', 'sumo_version', 'netconvert_version', 'prlimit_version')})
                self.save(job)
        except Exception as exc:
            with self.lock:
                job.update(status='cancelled' if isinstance(exc, Cancelled) else 'failed',
                           error=None if isinstance(exc, Cancelled) else str(exc), results=[])
                self.save(job)

    def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True)


def csv_report(job):
    stream = io.StringIO(); writer = csv.writer(stream)
    keys = ['travel_s', 'bus_s', 'waiting_s', 'max_queue_m', 'completed', 'unreachable', 'unfinished', 'hospital_freeflow_s']
    writer.writerow(['input_sha256', 'scenario_sha256', 'seed', 'scenario'] + keys)
    for pair in job['results']:
        for label in ('baseline', 'variant'):
            writer.writerow([job['input_sha256'], job['scenario_sha256'], pair['seed'], label] + [pair[label][k] for k in keys])
    return stream.getvalue()
