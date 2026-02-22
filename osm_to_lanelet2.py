#!/usr/bin/env python3
"""
osm_to_lanelet2.py
Convert raw OpenStreetMap highway data to Lanelet2 format (OSM XML).

Usage:
    python3 osm_to_lanelet2.py map_files/map.osm map_files/raw_lanelet2.osm

The output can then be:
    1. Imported into Vector Map Builder for refinement
    2. Processed with remove_lat_lon.py before loading into Autoware
"""

import xml.etree.ElementTree as ET
import math
import sys
from collections import defaultdict

# Half-width (meters) from road centerline to each lane boundary
HALF_WIDTHS = {
    'motorway': 3.75,    'motorway_link': 3.5,
    'trunk': 3.5,        'trunk_link': 3.25,
    'primary': 3.25,     'primary_link': 3.0,
    'secondary': 3.0,    'secondary_link': 2.75,
    'tertiary': 3.0,     'tertiary_link': 2.75,
    'residential': 2.75, 'living_street': 2.5,
    'service': 2.5,      'unclassified': 3.0,
    'road': 3.0,
    'footway': 1.5,      'cycleway': 1.5,
    'path': 1.5,         'pedestrian': 2.0,
    'steps': 1.0,
}

DEFAULT_SPEED = {
    'motorway': '130',   'trunk': '100',
    'primary': '90',     'secondary': '70',
    'tertiary': '50',    'residential': '30',
    'service': '20',     'living_street': '10',
    'unclassified': '50','road': '50',
}

VEHICLE_ROADS = {
    'motorway', 'motorway_link', 'trunk', 'trunk_link',
    'primary', 'primary_link', 'secondary', 'secondary_link',
    'tertiary', 'tertiary_link', 'residential', 'living_street',
    'service', 'unclassified', 'road',
}


def get_tags(elem):
    return {t.get('k'): t.get('v') for t in elem.findall('tag')}


def latlon_to_xy(lat, lon, origin_lat, origin_lon):
    """Equirectangular projection to local metres."""
    R = 6371000.0
    x = (lon - origin_lon) * math.pi / 180.0 * R * math.cos(math.radians(origin_lat))
    y = (lat - origin_lat) * math.pi / 180.0 * R
    return x, y


def xy_to_latlon(x, y, origin_lat, origin_lon):
    R = 6371000.0
    lat = origin_lat + (y / R) * (180.0 / math.pi)
    lon = origin_lon + (x / (R * math.cos(math.radians(origin_lat)))) * (180.0 / math.pi)
    return lat, lon


def normalize(dx, dy):
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-10 else (0.0, 1.0)


def left_perp(dx, dy):
    """Unit vector 90° to the left of the travel direction."""
    return normalize(-dy, dx)


def compute_perps(xy_coords):
    """
    For each node compute the average left-perpendicular unit vector,
    smoothed at corners by averaging adjacent segment directions.
    """
    n = len(xy_coords)
    perps = []
    for i in range(n):
        dirs = []
        if i > 0:
            dx = xy_coords[i][0] - xy_coords[i-1][0]
            dy = xy_coords[i][1] - xy_coords[i-1][1]
            dirs.append(normalize(dx, dy))
        if i < n - 1:
            dx = xy_coords[i+1][0] - xy_coords[i][0]
            dy = xy_coords[i+1][1] - xy_coords[i][1]
            dirs.append(normalize(dx, dy))
        avg_dx = sum(d[0] for d in dirs) / len(dirs)
        avg_dy = sum(d[1] for d in dirs) / len(dirs)
        avg_dx, avg_dy = normalize(avg_dx, avg_dy)
        perps.append(left_perp(avg_dx, avg_dy))
    return perps


def convert(input_file, output_file):
    tree = ET.parse(input_file)
    root = tree.getroot()

    # Determine map centre for local projection
    bounds = root.find('bounds')
    if bounds is not None:
        origin_lat = (float(bounds.get('minlat')) + float(bounds.get('maxlat'))) / 2
        origin_lon = (float(bounds.get('minlon')) + float(bounds.get('maxlon'))) / 2
    else:
        first = root.find('node')
        origin_lat = float(first.get('lat'))
        origin_lon = float(first.get('lon'))

    # Index all OSM nodes
    osm_nodes = {}
    for node in root.findall('node'):
        nid = node.get('id')
        lat, lon = float(node.get('lat')), float(node.get('lon'))
        x, y = latlon_to_xy(lat, lon, origin_lat, origin_lon)
        osm_nodes[nid] = (lat, lon, x, y)

    # Collect highway ways
    highway_ways = []
    for way in root.findall('way'):
        tags = get_tags(way)
        hw = tags.get('highway', '')
        if hw not in HALF_WIDTHS:
            continue
        refs = [nd.get('ref') for nd in way.findall('nd') if nd.get('ref') in osm_nodes]
        if len(refs) < 2:
            continue
        highway_ways.append({
            'id':      way.get('id'),
            'highway': hw,
            'refs':    refs,
            'oneway':  tags.get('oneway', 'no') in ('yes', '1', 'true'),
            'speed':   tags.get('maxspeed', DEFAULT_SPEED.get(hw, '50')),
            'name':    tags.get('name', ''),
        })

    print(f"Found {len(highway_ways)} highway ways to convert.")

    # ── Phase 1: pre-compute perpendiculars ───────────────────────────────────
    for hw in highway_ways:
        xy = [(osm_nodes[r][2], osm_nodes[r][3]) for r in hw['refs']]
        hw['xy']     = xy
        hw['perps']  = compute_perps(xy)
        hw['half_w'] = HALF_WIDTHS[hw['highway']]

    # ── Phase 2: find OSM nodes shared between way endpoints ─────────────────
    # endpoint_info[osm_ref] = [(perp_x, perp_y, half_w), ...]
    endpoint_info = defaultdict(list)
    for hw in highway_ways:
        refs = hw['refs']
        for pos in (0, len(refs) - 1):
            px, py = hw['perps'][pos]
            endpoint_info[refs[pos]].append((px, py, hw['half_w']))

    # ── Phase 3: build output XML ─────────────────────────────────────────────
    out = ET.Element('osm', version='0.6', generator='osm_to_lanelet2.py')
    if bounds is not None:
        ET.SubElement(out, 'bounds',
                      minlat=bounds.get('minlat'), minlon=bounds.get('minlon'),
                      maxlat=bounds.get('maxlat'), maxlon=bounds.get('maxlon'))

    _nid = [-1]
    _wid = [-1]
    _rid = [-1]

    def add_node(lat, lon):
        nid = _nid[0]; _nid[0] -= 1
        ET.SubElement(out, 'node', id=str(nid), visible='true',
                      lat=f'{lat:.8f}', lon=f'{lon:.8f}', ele='0')
        return nid

    def add_way(node_ids, tags):
        wid = _wid[0]; _wid[0] -= 1
        e = ET.SubElement(out, 'way', id=str(wid), visible='true')
        for nid in node_ids:
            ET.SubElement(e, 'nd', ref=str(nid))
        for k, v in tags.items():
            ET.SubElement(e, 'tag', k=k, v=v)
        return wid

    def add_relation(members, tags):
        rid = _rid[0]; _rid[0] -= 1
        e = ET.SubElement(out, 'relation', id=str(rid), visible='true')
        for mtype, mref, mrole in members:
            ET.SubElement(e, 'member', type=mtype, ref=str(mref), role=mrole)
        for k, v in tags.items():
            ET.SubElement(e, 'tag', k=k, v=v)
        return rid

    # ── Phase 4: pre-create shared boundary nodes at junction endpoints ───────
    # For every OSM node that is a first/last node in 2+ ways, create ONE set
    # of left/centre/right Lanelet2 nodes (averaged perpendicular).  Any way
    # that uses this OSM node as an endpoint will reference the same Lanelet2
    # node IDs, making Lanelet2 treat those lanelets as connected.
    #
    # shared[osm_ref] = {'left': nid, 'centre': nid, 'right': nid}
    shared = {}
    for osm_ref, infos in endpoint_info.items():
        if len(infos) < 2:
            continue
        # Average perpendiculars from all touching ways
        avg_px = sum(i[0] for i in infos) / len(infos)
        avg_py = sum(i[1] for i in infos) / len(infos)
        avg_px, avg_py = normalize(avg_px, avg_py)
        avg_hw = sum(i[2] for i in infos) / len(infos)

        x, y = osm_nodes[osm_ref][2], osm_nodes[osm_ref][3]
        shared[osm_ref] = {
            'left':   add_node(*xy_to_latlon(x + avg_px * avg_hw,
                                             y + avg_py * avg_hw,
                                             origin_lat, origin_lon)),
            'centre': add_node(*xy_to_latlon(x, y, origin_lat, origin_lon)),
            'right':  add_node(*xy_to_latlon(x - avg_px * avg_hw,
                                             y - avg_py * avg_hw,
                                             origin_lat, origin_lon)),
        }

    # ── Phase 5: create boundary nodes and lanelets for each way ─────────────
    lanelets_created = 0

    for hw in highway_ways:
        hw_type = hw['highway']
        half_w  = hw['half_w']
        refs    = hw['refs']
        xy      = hw['xy']
        perps   = hw['perps']
        n       = len(refs)

        is_vehicle = hw_type in VEHICLE_ROADS
        solid_tags  = {'type': 'line_thin', 'subtype': 'solid' if is_vehicle else 'dashed'}
        dashed_tags = {'type': 'line_thin', 'subtype': 'dashed'}

        speed = hw['speed']
        if not str(speed).rstrip(' mph km/h').isdigit():
            speed = DEFAULT_SPEED.get(hw_type, '50')

        rel_tags = {
            'type':                   'lanelet',
            'subtype':                'road' if is_vehicle else 'walkway',
            'speed_limit':            str(speed),
            'location':               'urban',
            'participant:vehicle':    'yes' if is_vehicle else 'no',
            'participant:pedestrian': 'yes' if not is_vehicle else 'no',
        }
        if hw['name']:
            rel_tags['name'] = hw['name']

        def boundary_node(i, side):
            """Return Lanelet2 node ID for position i, reusing shared nodes at endpoints."""
            osm_ref = refs[i]
            if (i == 0 or i == n - 1) and osm_ref in shared:
                return shared[osm_ref][side]
            x, y = xy[i]
            px, py = perps[i]
            if side == 'left':
                return add_node(*xy_to_latlon(x + px * half_w, y + py * half_w,
                                              origin_lat, origin_lon))
            elif side == 'right':
                return add_node(*xy_to_latlon(x - px * half_w, y - py * half_w,
                                              origin_lat, origin_lon))
            else:  # centre
                return add_node(*xy_to_latlon(x, y, origin_lat, origin_lon))

        if hw['oneway']:
            left_ids  = [boundary_node(i, 'left')  for i in range(n)]
            right_ids = [boundary_node(i, 'right') for i in range(n)]

            lw = add_way(left_ids,  solid_tags)
            rw = add_way(right_ids, solid_tags)
            add_relation([('way', lw, 'left'), ('way', rw, 'right')],
                         {**rel_tags, 'one_way': 'yes'})
            lanelets_created += 1

        else:
            left_ids   = [boundary_node(i, 'left')   for i in range(n)]
            centre_ids = [boundary_node(i, 'centre') for i in range(n)]
            right_ids  = [boundary_node(i, 'right')  for i in range(n)]

            # Forward lanelet
            add_relation([('way', add_way(left_ids,   solid_tags),  'left'),
                          ('way', add_way(centre_ids, dashed_tags), 'right')],
                         rel_tags)

            # Reverse lanelet (reversed node order so direction is opposite)
            add_relation([('way', add_way(list(reversed(centre_ids)), dashed_tags), 'left'),
                          ('way', add_way(list(reversed(right_ids)),  solid_tags),  'right')],
                         rel_tags)

            lanelets_created += 2

    ET.indent(out, space='  ')
    ET.ElementTree(out).write(output_file, encoding='unicode', xml_declaration=True)

    print(f"Created {lanelets_created} lanelets.")
    print(f"Output: {output_file}")
    print()
    print("Next steps:")
    print("  1. Import the output into Vector Map Builder to inspect & refine")
    print("  2. Run:  python3 remove_lat_lon.py map_files/raw_lanelet2.osm map_files/lanelet2_map.osm")
    print("  3. Import lanelet2_map.osm into Autoware")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 osm_to_lanelet2.py <input.osm> <output.osm>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
