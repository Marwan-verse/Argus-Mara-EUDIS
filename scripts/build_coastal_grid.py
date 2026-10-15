"""Reproduce the Irish coastal pilot grid from bundled public-domain geometry."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    path = ROOT/'ui/assets/coastline.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    # The first country polygons include the Republic AND Northern Ireland.
    # Removing shared edges is essential: the land border is not coastline.
    rings = [r for r in source['rings'] if min(p[0] for p in r) > -12 and
             max(p[0] for p in r) < -5 and min(p[1] for p in r) > 51 and max(p[1] for p in r) < 55.5]
    edges = Counter(tuple(sorted((tuple(a), tuple(b)))) for r in rings for a, b in zip(r, r[1:]))
    shared = sum(v == 2 for v in edges.values())
    if shared < 100:
        raise ValueError('Irish border topology changed; inspect geometry before rebuilding')
    xscale, yscale, size, belt = 111.32*math.cos(math.radians(53.3)), 111.32, 8., 40.
    cells = set()
    for (a, b), count in edges.items():
        if count != 1:
            continue
        ax, ay, bx, by = a[0]*xscale, a[1]*yscale, b[0]*xscale, b[1]*yscale
        steps = max(1, math.ceil(math.hypot(ax-bx, ay-by)/2))
        for k in range(steps+1):
            x, y = ax+(bx-ax)*k/steps, ay+(by-ay)*k/steps
            for i in range(math.floor((x-belt)/size), math.floor((x+belt)/size)+1):
                for j in range(math.floor((y-belt)/size), math.floor((y+belt)/size)+1):
                    dx, dy = max(i*size-x, 0, x-(i+1)*size), max(j*size-y, 0, y-(j+1)*size)
                    if math.hypot(dx, dy) <= belt+2:
                        cells.add((i, j))
    return {'version': 2, 'label': 'assumption', 'cell_km': size, 'coastal_belt_km': belt,
            'scope': 'Coast of the island of Ireland, including Northern Ireland and represented islands; approximately 40 km coastal belt, not the whole EEZ',
            'source': source['source'], 'licence': source['licence'], 'source_url': source['source_url'],
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'removed_shared_border_edges': shared,
            'caveat': 'Planning grid from simplified display geometry, approximately 2 km buffer tolerance; not for navigation. Cells include land; image quality masks select water.',
            'tiles': [{'id': f'IE-{i}-{j}', 'bbox': [round(i*size/xscale, 6), round(j*size/yscale, 6),
                       round((i+1)*size/xscale, 6), round((j+1)*size/yscale, 6)]} for i, j in sorted(cells)]}


if __name__ == '__main__':
    value = build()
    (ROOT/'argus/coastal_grid.json').write_text(json.dumps(value, separators=(',', ':'))+'\n', encoding='utf-8')
    print(f"{len(value['tiles'])} coastal cells; {value['removed_shared_border_edges']} shared border edges removed")
