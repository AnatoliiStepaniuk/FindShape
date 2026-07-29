#!/usr/bin/env python3
"""Читає SVG і віддає контури як прості багатокутники.

Потрібен, бо фігури рівнів беруться з готових векторних малюнків, а не
вигадуються: криві Безьє тут розбиваються на відрізки, трансформації
застосовуються, і на виході — те, що вміє формат рівня: списки точок.

Використання:
    from svg_paths import load_polygons
    for shape in load_polygons("face.svg"):
        shape["id"], shape["fill"], shape["polygons"]
"""

import math
import re
import xml.etree.ElementTree as ET

NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
COMMAND = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]")


# ---------- трансформації (матриця 2x3) ----------

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(text):
    matrix = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(t) for t in NUMBER.findall(args)]
        if name == "translate":
            step = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            step = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix":
            step = tuple(v[:6])
        elif name == "rotate":
            a = math.radians(v[0])
            step = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                step = multiply(multiply((1, 0, 0, 1, v[1], v[2]), step),
                                (1, 0, 0, 1, -v[1], -v[2]))
        else:
            continue
        matrix = multiply(matrix, step)
    return matrix


# ---------- розбір даних шляху ----------

def tokenize(data):
    pos, out = 0, []
    while pos < len(data):
        ch = data[pos]
        if COMMAND.match(ch):
            out.append(ch)
            pos += 1
        elif ch in " ,\n\r\t":
            pos += 1
        else:
            m = NUMBER.match(data, pos)
            if not m:
                pos += 1
                continue
            out.append(float(m.group()))
            pos = m.end()
    return out


def cubic(p0, p1, p2, p3, steps):
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        points.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                       u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return points


def arc(p0, rx, ry, rotation, large, sweep, p1, steps):
    """Еліптична дуга SVG → відрізки (за формулами зі специфікації)."""
    if p0 == p1 or rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(rotation)
    dx2, dy2 = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = math.cos(phi) * dx2 + math.sin(phi) * dy2
    y1 = -math.sin(phi) * dx2 + math.cos(phi) * dy2
    rx, ry = abs(rx), abs(ry)
    scale = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = math.cos(phi) * cx1 - math.sin(phi) * cy1 + (p0[0] + p1[0]) / 2
    cy = math.sin(phi) * cx1 + math.cos(phi) * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        det = ux * vy - uy * vx
        return math.atan2(det, dot)

    start = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= math.tau
    elif sweep and delta < 0:
        delta += math.tau

    points = []
    for i in range(1, steps + 1):
        a = start + delta * i / steps
        x = math.cos(phi) * rx * math.cos(a) - math.sin(phi) * ry * math.sin(a) + cx
        y = math.sin(phi) * rx * math.cos(a) + math.cos(phi) * ry * math.sin(a) + cy
        points.append((x, y))
    return points


def path_to_polygons(data, steps=12):
    """Дані атрибута d → список замкнених контурів."""
    tokens = tokenize(data)
    polygons, current = [], []
    pos = 0
    cursor = (0.0, 0.0)
    start = (0.0, 0.0)
    command = None
    last_control = None

    def flush():
        nonlocal current
        if len(current) > 2:
            polygons.append(current)
        current = []

    while pos < len(tokens):
        token = tokens[pos]
        if isinstance(token, str):
            command = token
            pos += 1
            if command in "Zz":
                flush()
                cursor = start
                continue
        elif command in "Mm":
            command = "L" if command == "M" else "l"
        relative = command.islower()
        upper = command.upper()

        def take(n):
            nonlocal pos
            values = tokens[pos:pos + n]
            pos += n
            return values

        if upper == "M":
            x, y = take(2)
            cursor = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
            flush()
            current = [cursor]
            start = cursor
        elif upper in ("L", "T"):
            x, y = take(2)
            cursor = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
            current.append(cursor)
        elif upper == "H":
            x = take(1)[0]
            cursor = (cursor[0] + x, cursor[1]) if relative else (x, cursor[1])
            current.append(cursor)
        elif upper == "V":
            y = take(1)[0]
            cursor = (cursor[0], cursor[1] + y) if relative else (cursor[0], y)
            current.append(cursor)
        elif upper in ("C", "S", "Q"):
            if upper == "C":
                x1, y1, x2, y2, x, y = take(6)
            elif upper == "S":
                x2, y2, x, y = take(4)
                base = last_control or cursor
                x1, y1 = (2 * cursor[0] - base[0], 2 * cursor[1] - base[1])
                if relative:
                    x1, y1 = x1 - cursor[0], y1 - cursor[1]
            else:
                x1, y1, x, y = take(4)
                x2, y2 = x1, y1                       # квадратична як вироджена кубічна
            if relative:
                p1 = (cursor[0] + x1, cursor[1] + y1)
                p2 = (cursor[0] + x2, cursor[1] + y2)
                end = (cursor[0] + x, cursor[1] + y)
            else:
                p1, p2, end = (x1, y1), (x2, y2), (x, y)
            current.extend(cubic(cursor, p1, p2, end, steps))
            last_control, cursor = p2, end
            continue
        elif upper == "A":
            rx, ry, rot, large, sweep, x, y = take(7)
            end = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
            current.extend(arc(cursor, rx, ry, rot, int(large), int(sweep), end, steps))
            cursor = end
        else:
            pos += 1
            continue
        last_control = None

    flush()
    return polygons


# ---------- цілий файл ----------

def load_polygons(path, steps=12):
    """Список фігур файлу: id, заливка і контури у координатах документа."""
    tree = ET.parse(path)
    shapes = []

    def walk(node, matrix):
        matrix = multiply(matrix, parse_transform(node.get("transform")))
        tag = node.tag.split("}")[-1]
        if tag == "path" and node.get("d"):
            polygons = [[apply(matrix, x, y) for x, y in poly]
                        for poly in path_to_polygons(node.get("d"), steps)]
            shapes.append({"id": node.get("id") or "", "fill": fill_of(node), "polygons": polygons})
        elif tag in ("circle", "ellipse"):
            cx, cy = float(node.get("cx", 0)), float(node.get("cy", 0))
            if tag == "circle":
                rx = ry = float(node.get("r", 0))
            else:
                rx, ry = float(node.get("rx", 0)), float(node.get("ry", 0))
            poly = [apply(matrix, cx + rx * math.cos(t * math.tau / 40),
                          cy + ry * math.sin(t * math.tau / 40)) for t in range(40)]
            shapes.append({"id": node.get("id") or "", "fill": fill_of(node), "polygons": [poly]})
        elif tag == "rect":
            x, y = float(node.get("x", 0)), float(node.get("y", 0))
            w, h = float(node.get("width", 0)), float(node.get("height", 0))
            poly = [apply(matrix, *p) for p in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
            shapes.append({"id": node.get("id") or "", "fill": fill_of(node), "polygons": [poly]})
        for child in node:
            walk(child, matrix)

    walk(tree.getroot(), IDENTITY)
    return shapes


def fill_of(node):
    style = node.get("style") or ""
    match = re.search(r"fill\s*:\s*([^;]+)", style)
    return (match.group(1) if match else node.get("fill") or "").strip()


def area(polygon):
    return abs(sum(polygon[i][0] * polygon[i - 1][1] - polygon[i - 1][0] * polygon[i][1]
                   for i in range(len(polygon)))) / 2


def simplify(points, eps):
    """Дуглас–Пекер: прибирає точки, які майже лежать на прямій."""
    if len(points) < 3:
        return points

    def distance(p, a, b):
        if a == b:
            return math.dist(p, a)
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))

    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = distance(points[i], points[0], points[-1])
        if d > worst:
            worst, index = d, i
    if worst > eps:
        return simplify(points[:index + 1], eps)[:-1] + simplify(points[index:], eps)
    return [points[0], points[-1]]
