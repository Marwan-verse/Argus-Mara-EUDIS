"""Display-only geographic helpers; never used for alert calculations."""

import unicodedata


def search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold()
                   if not unicodedata.combining(c))


def find_ports(ports, query='', country='All countries', visible=None):
    tokens = search_text(query).split()
    matches = []
    for index, (number, name, lat, lon, code) in enumerate(ports):
        if country != 'All countries' and code != country:
            continue
        if visible is not None and index not in visible:
            continue
        text = search_text(f'{name} {code} {number}')
        if all(token in text for token in tokens):
            matches.append(index)
    return sorted(matches, key=lambda i: (search_text(ports[i][1]), ports[i][0]))


def coordinates(lat, lon):
    return f'{abs(lat):.4f}°{"N" if lat >= 0 else "S"}, {abs(lon):.4f}°{"E" if lon >= 0 else "W"}'


def route_name(cable, index):
    name = cable.get('name', '').strip()
    return name if name and name != 'Unnamed cable' else f'Unnamed route {index + 1:03d}'


def geographic_extent(points):
    """Minimal circular longitude extent, including routes across the date line."""
    lats, lons = zip(*points)
    ordered = sorted(lon % 360 for lon in lons)
    gaps = [(ordered[(i + 1) % len(ordered)] + (360 if i == len(ordered) - 1 else 0)
             - lon, i) for i, lon in enumerate(ordered)]
    gap, index = max(gaps)
    west = ordered[(index + 1) % len(ordered)]
    span = 360 - gap
    center_lon = ((west + span / 2 + 180) % 360) - 180
    return ((min(lats) + max(lats)) / 2, center_lon), max(lats) - min(lats), span
