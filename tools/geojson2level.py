#!/usr/bin/env python3
"""Робить файл рівня FindShape з будь-якого GeoJSON.

Двіжок гри не знає про географію — він читає лише назви й багатокутники.
Цей скрипт — місток: бере GeoJSON, проєктує (Меркатор), обрізає по вікну,
спрощує лінії і пише levels/<назва>.json у форматі:

    [ { "name": "Іспанія", "polygons": [ [[x,y], [x,y], ...], ... ] } ]

Приклад:
    python3 tools/geojson2level.py ne_110m_admin_0_countries.geojson \\
        --window -25 45 34 72 --continent Europe --name-field NAME_UK \\
        --out levels/europe.json
"""

import argparse
import json
import math
import sys


def mercator(lon, lat, win, size):
    """Проєкція Меркатора у пікселі полотна size у межах вікна win."""
    lon0, lon1, lat0, lat1 = win
    width, height = size

    def y_of(deg):
        deg = max(-85.0, min(85.0, deg))
        return math.log(math.tan(math.pi / 4 + math.radians(deg) / 2))

    y_top, y_bottom = y_of(lat1), y_of(lat0)
    x = (lon - lon0) / (lon1 - lon0) * width
    y = (y_top - y_of(lat)) / (y_top - y_bottom) * height
    return (x, y)


def clip_rect(points, box):
    """Sutherland–Hodgman: лишає частину багатокутника всередині прямокутника."""
    x0, y0, x1, y1 = box
    out = list(points)
    for edge in range(4):
        if not out:
            return []
        inp, out = out, []

        def inside(p):
            return (p[0] >= x0, p[0] <= x1, p[1] >= y0, p[1] <= y1)[edge]

        def crossing(a, b):
            if edge < 2:
                xe = x0 if edge == 0 else x1
                t = (xe - a[0]) / (b[0] - a[0])
                return (xe, a[1] + t * (b[1] - a[1]))
            ye = y0 if edge == 2 else y1
            t = (ye - a[1]) / (b[1] - a[1])
            return (a[0] + t * (b[0] - a[0]), ye)

        prev = inp[-1]
        for cur in inp:
            if inside(cur):
                if not inside(prev):
                    out.append(crossing(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(crossing(prev, cur))
            prev = cur
    return out


def simplify(points, eps):
    """Дуглас–Пекер: викидає точки, які майже лежать на прямій."""
    if len(points) < 3:
        return points

    def dist_to_line(p, a, b):
        if a == b:
            return math.dist(p, a)
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))

    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = dist_to_line(points[i], points[0], points[-1])
        if d > worst:
            worst, index = d, i
    if worst > eps:
        return simplify(points[: index + 1], eps)[:-1] + simplify(points[index:], eps)
    return [points[0], points[-1]]


def ring_area(points):
    if len(points) < 3:
        return 0.0
    s = sum(points[i][0] * points[i - 1][1] - points[i - 1][0] * points[i][1]
            for i in range(len(points)))
    return abs(s) / 2


def outer_rings(geometry):
    """Зовнішні кільця: Polygon → одне, MultiPolygon → по одному на шматок."""
    kind = geometry["type"]
    if kind == "Polygon":
        return [geometry["coordinates"][0]]
    if kind == "MultiPolygon":
        return [part[0] for part in geometry["coordinates"]]
    return []


def split_at_antimeridian(ring):
    """Розриває кільце там, де воно перестрибує через 180-й меридіан."""
    chunks, current = [], []
    for point in ring:
        if current and abs(point[0] - current[-1][0]) > 180:
            chunks.append(current)
            current = []
        current.append(point)
    if current:
        chunks.append(current)
    return chunks


def dumps_level(shapes, per_line=6):
    """JSON, у якому точки згруповані по кілька в рядок — щоб файл читався очима."""
    def num(v):
        return f"{v:g}"

    out = ["["]
    for si, shape in enumerate(shapes):
        out.append("  {")
        out.append(f'    "name": {json.dumps(shape["name"], ensure_ascii=False)},')
        out.append('    "polygons": [')
        for pi, polygon in enumerate(shape["polygons"]):
            points = [f"[{num(x)}, {num(y)}]" for x, y in polygon]
            rows = [", ".join(points[i:i + per_line])
                    for i in range(0, len(points), per_line)]
            body = ",\n        ".join(rows)
            tail = "," if pi < len(shape["polygons"]) - 1 else ""
            out.append(f"      [ {body} ]{tail}")
        out.append("    ]")
        out.append("  }" + ("," if si < len(shapes) - 1 else ""))
    out.append("]")
    return "\n".join(out) + "\n"


def build(args):
    with open(args.geojson, encoding="utf-8") as fh:
        data = json.load(fh)

    win = tuple(args.window)
    size = (args.width, args.height)
    canvas = args.width * args.height
    shapes, skipped = [], []

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if args.continent and props.get("CONTINENT") != args.continent:
            continue
        if args.skip and props.get(args.name_field) in args.skip:
            continue
        name = props.get(args.name_field)
        if not name:
            continue

        polygons = []
        for ring in outer_rings(feature.get("geometry") or {}):
            for chunk in split_at_antimeridian(ring):
                projected = [mercator(lon, lat, win, size) for lon, lat, *_ in chunk]
                clipped = clip_rect(projected, (0, 0, args.width, args.height))
                if len(clipped) < 4:
                    continue
                if ring_area(clipped) < canvas * args.min_area:
                    continue
                reduced = simplify(clipped, args.epsilon)
                if len(reduced) < 4:
                    continue
                polygons.append([[round(x, 1), round(y, 1)] for x, y in reduced])

        if polygons:
            shapes.append({"name": name, "polygons": polygons})
        else:
            skipped.append(name)

    shapes.sort(key=lambda s: s["name"])
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(dumps_level(shapes))

    points = sum(len(p) for s in shapes for p in s["polygons"])
    parts = sum(len(s["polygons"]) for s in shapes)
    print(f"{args.out}: фігур={len(shapes)} багатокутників={parts} точок={points}")
    if skipped:
        print(f"  замалі або поза вікном: {', '.join(sorted(skipped))}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("geojson", help="вхідний GeoJSON")
    parser.add_argument("--out", required=True, help="куди писати файл рівня")
    parser.add_argument("--window", nargs=4, type=float, required=True,
                        metavar=("LON0", "LON1", "LAT0", "LAT1"),
                        help="вікно карти: захід схід південь північ")
    parser.add_argument("--continent", help="фільтр по властивості CONTINENT")
    parser.add_argument("--name-field", default="NAME_UK", help="звідки брати назву")
    parser.add_argument("--skip", nargs="*", default=[], help="назви, які викинути")
    parser.add_argument("--width", type=float, default=1000.0)
    parser.add_argument("--height", type=float, default=760.0)
    parser.add_argument("--epsilon", type=float, default=0.8,
                        help="спрощення ліній, пікселі")
    parser.add_argument("--min-area", type=float, default=0.0004,
                        help="мінімальна площа шматка, частка полотна")
    sys.exit(build(parser.parse_args()))


if __name__ == "__main__":
    main()
