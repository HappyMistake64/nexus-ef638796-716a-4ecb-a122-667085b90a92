import hashlib
import heapq
import json
import math
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODEL = 'city-forge-sumo-0.1.2'
HORIZON = 900


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Datová sada musí být objekt')
    for key in ('name', 'source', 'license', 'valid_on', 'timezone', 'crs'):
        if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 200:
            raise ValueError('Chybí metadata: ' + key)
    date.fromisoformat(data['valid_on'])
    try:
        ZoneInfo(data['timezone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Neplatné časové pásmo') from None
    if data['crs'] != 'LOCAL_METRES':
        raise ValueError('Pilot podporuje pouze LOCAL_METRES')
    nodes, edges = data.get('nodes'), data.get('edges')
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 100:
        raise ValueError('Počet uzlů musí být 2–100')
    if not isinstance(edges, list) or not 1 <= len(edges) <= 250:
        raise ValueError('Počet úseků musí být 1–250')
    def ident(value):
        return isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', value)
    def number(v, lo, hi):
        return type(v) in (int, float) and math.isfinite(v) and lo <= v <= hi
    ids, positions = set(), set()
    for n in nodes:
        if not isinstance(n, dict) or not ident(n.get('id')) or n['id'] in ids:
            raise ValueError('Neplatné nebo duplicitní ID uzlu')
        if not number(n.get('x'), -10000, 10000) or not number(n.get('y'), -10000, 10000):
            raise ValueError('Neplatné souřadnice')
        pos = (n['x'], n['y'])
        if pos in positions:
            raise ValueError('Dva uzly mají stejné souřadnice')
        ids.add(n['id']); positions.add(pos)
    seen, directions = set(), set()
    by_id = {n['id']: n for n in nodes}
    for e in edges:
        if not isinstance(e, dict) or not ident(e.get('id')) or e['id'] in seen:
            raise ValueError('Neplatné nebo duplicitní ID úseku')
        if not ident(e.get('source')) or not ident(e.get('target')) or e['source'] not in ids or e['target'] not in ids or e['source'] == e['target']:
            raise ValueError('Neplatný směr nebo konec úseku')
        direction = (e['source'], e['target'])
        if direction in directions:
            raise ValueError('Duplicitní orientovaný úsek')
        a, b = by_id[e['source']], by_id[e['target']]
        if math.hypot(a['x']-b['x'], a['y']-b['y']) < 20:
            raise ValueError('Úsek musí mít alespoň 20 metrů')
        if not number(e.get('speed'), 2, 35):
            raise ValueError('Rychlost musí být 2–35 m/s')
        seen.add(e['id']); directions.add(direction)
    if not ident(data.get('origin')) or not ident(data.get('hospital')) or data['origin'] not in ids or data['hospital'] not in ids or data['origin'] == data['hospital']:
        raise ValueError('Neplatný počátek nebo nemocnice')
    if type(data.get('cars')) is not int or not 0 <= data['cars'] <= 600:
        raise ValueError('Poptávka musí být 0–600 vozidel')
    buses = data.get('bus_departures')
    if not isinstance(buses, list) or len(buses) > 40 or any(not number(t, 0, 899) for t in buses):
        raise ValueError('Neplatné odjezdy autobusů')
    if buses != sorted(set(buses)):
        raise ValueError('Odjezdy musí být jedinečné a seřazené')
    if not shortest(data, None)[0]:
        raise ValueError('Nemocnice není ve výchozí síti dosažitelná')
    reached = {data['origin']}
    for _ in nodes:
        reached.update([e['target'] for e in edges if e['source'] in reached])
    if reached != ids:
        raise ValueError('Síť obsahuje nedosažitelné uzly')
    return json.loads(canonical(data))


def shortest(data, closed):
    nodes = {n['id']: n for n in data['nodes']}
    queue = [(0.0, data['origin'], [])]
    visited = set()
    while queue:
        cost, node, route = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == data['hospital']:
            return route, cost
        for e in data['edges']:
            if e['source'] != node or e['id'] == closed:
                continue
            a, b = nodes[node], nodes[e['target']]
            length = math.hypot(a['x']-b['x'], a['y']-b['y'])
            heapq.heappush(queue, (cost + length/e['speed'], e['target'], route + [e['id']]))
    return [], None
