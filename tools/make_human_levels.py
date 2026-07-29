#!/usr/bin/env python3
"""Робить рівні «Body» і «Face» зі справжніх векторних малюнків.

Контури не вигадуються: беруться з SVG (public domain, джерела в README) і
розрізаються на названі частини площинами. Парні частини — око, вухо, рука,
нога — це одна фігура з кількох багатокутників, бо ідентифікатор фігури у
форматі рівня — її назва.

    python3 tools/make_human_levels.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_paths import area, load_polygons, simplify   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS = os.path.join(os.path.dirname(HERE), "levels")


# ---------- різання ----------

def half_plane(x0, y0, x1, y1, keep_left=True):
    """Півплощина по прямій через дві точки; keep_left — з якого боку лишаємо."""
    a, b = y1 - y0, x0 - x1
    c = -(a * x0 + b * y0)
    return (a, b, c) if keep_left else (-a, -b, -c)


def below(y):
    return (0.0, 1.0, -y)          # y <= межа


def above(y):
    return (0.0, -1.0, y)          # y >= межа


def left_of(x):
    return (1.0, 0.0, -x)          # x <= межа


def right_of(x):
    return (-1.0, 0.0, x)          # x >= межа


def clip(polygon, planes):
    """Sutherland–Hodgman: лишає частину контуру всередині опуклої області."""
    out = list(polygon)
    for a, b, c in planes:
        if not out:
            return []
        inp, out = out, []

        def side(p):
            return a * p[0] + b * p[1] + c

        prev = inp[-1]
        prev_in = side(prev) <= 0
        for cur in inp:
            cur_in = side(cur) <= 0
            if cur_in != prev_in:
                t = side(prev) / (side(prev) - side(cur))
                out.append((prev[0] + t * (cur[0] - prev[0]),
                            prev[1] + t * (cur[1] - prev[1])))
            if cur_in:
                out.append(cur)
            prev, prev_in = cur, cur_in
    return out


def carve(outline, parts, eps, min_area):
    """parts: [(назва, [півплощини, ...]), ...] → фігури рівня."""
    shapes = {}
    for name, planes in parts:
        piece = clip(outline, planes)
        if len(piece) < 4 or area(piece) < min_area:
            continue
        piece = simplify(piece, eps)
        if len(piece) > 3:
            shapes.setdefault(name, []).append(piece)
    return [{"name": name, "polygons": polys} for name, polys in shapes.items()]


def normalize(shapes, height=1000.0):
    """Зсуває до нуля й масштабує, щоб числа у файлі були людські."""
    points = [p for s in shapes for poly in s["polygons"] for p in poly]
    x0 = min(p[0] for p in points)
    y0 = min(p[1] for p in points)
    y1 = max(p[1] for p in points)
    k = height / (y1 - y0)
    for shape in shapes:
        shape["polygons"] = [[[round((x - x0) * k, 1), round((y - y0) * k, 1)] for x, y in poly]
                             for poly in shape["polygons"]]
    return shapes


def dumps_level(shapes, per_line=6):
    out = ["["]
    for si, shape in enumerate(shapes):
        out.append("  {")
        out.append(f'    "name": {json.dumps(shape["name"], ensure_ascii=False)},')
        out.append('    "polygons": [')
        for pi, polygon in enumerate(shape["polygons"]):
            points = [f"[{x:g}, {y:g}]" for x, y in polygon]
            rows = [", ".join(points[i:i + per_line]) for i in range(0, len(points), per_line)]
            tail = "," if pi < len(shape["polygons"]) - 1 else ""
            out.append("      [ " + ",\n        ".join(rows) + f" ]{tail}")
        out.append("    ]")
        out.append("  }" + ("," if si < len(shapes) - 1 else ""))
    out.append("]")
    return "\n".join(out) + "\n"


# ---------- рівень «Body» ----------

def build_body():
    """Силует людини → 11 частин.

    Числа зняті з самого контуру горизонтальними промірами: пахва ≈ 750,
    лікоть 880–980, зап'ясток ≈ 1170, розкрок ≈ 1270, коліно 1570–1670,
    щиколотка ≈ 2040. Вісь симетрії x = 487.
    """
    source = os.path.join(HERE, "source-human-body.svg")
    outline = max(load_polygons(source)[0]["polygons"], key=area)

    axis = 487.0
    torso = 298.0                                     # бік грудей
    gap = 260.0                                       # порожнеча між рукою й тулубом
    hip_left = half_plane(298, 760, 240, 1270, keep_left=False)    # тулуб донизу звужується
    hip_right = half_plane(2 * axis - 298, 760, 2 * axis - 240, 1270, keep_left=True)

    def mirrored(planes):
        return [(-a, b, c + a * 2 * axis) for a, b, c in planes]

    parts = [
        ("Head", [below(300)]),
        ("Neck", [above(300), below(400)]),
        ("Chest", [above(400), below(760), right_of(torso), left_of(2 * axis - torso)]),
        ("Belly", [above(760), below(1270), hip_left, hip_right]),
    ]
    for name, planes in (
        ("Shoulder", [above(400), below(620), left_of(torso)]),
        ("Arm", [above(620), below(880), left_of(torso)]),
        ("Elbow", [above(880), below(980), left_of(gap)]),
        ("Arm", [above(980), below(1170), left_of(gap)]),
        # below(1400) — щоб у смугу кисті не потрапила ступня того ж боку
        ("Hand", [above(1170), below(1400), left_of(gap)]),
        # right_of(220) відрізає кисть: без нього вона потрапляє у смугу стегна
        # і різалка зшиває два окремі шматки перемичкою через увесь малюнок
        ("Leg", [above(1270), below(1570), left_of(axis), right_of(220)]),
        ("Knee", [above(1570), below(1670), left_of(axis), right_of(220)]),
        ("Leg", [above(1670), below(2040), left_of(axis), right_of(220)]),
        ("Foot", [above(2040), left_of(axis), right_of(220)]),
    ):
        parts.append((name, planes))
        parts.append((name, mirrored(planes)))

    return normalize(carve(outline, parts, eps=1.6, min_area=200), height=1000)


# ---------- рівень «Face» ----------

# Малюнок обличчя складається з окремих шляхів; ось хто є хто (порядок у файлі).
# Беремо лише ті шматки волосся, які в малюнку видно: зовнішню масу і чубчик.
# Решта (пасма за обличчям, відблиски) в оригіналі сховані під обличчям, а гра
# малює кожен багатокутник повністю — вони вилізли б плямами поверх щік.
FACE_PARTS = {
    0: "Hair", 12: "Hair",
    5: "Face",
    6: "Nose",
    7: "Eyebrow", 8: "Eyebrow",
    9: "Eye", 10: "Eye",
    11: "Mouth",
}
FACE_EARS = 4          # обидва вуха одним шляхом, здебільшого сховані за обличчям


def build_face():
    """Обличчя дитини → 7 частин. Вуха доводиться відрізати по краю обличчя:
    у малюнку вони лежать під ним, а гра малює кожну фігуру повністю."""
    source = os.path.join(HERE, "source-human-face.svg")
    elements = load_polygons(source, steps=10)
    if len(elements) != 17:
        raise SystemExit(f"очікував 17 елементів у {source}, а там {len(elements)}")

    shapes = {}
    for index, name in FACE_PARTS.items():
        for polygon in elements[index]["polygons"]:
            if area(polygon) > 8:
                shapes.setdefault(name, []).append(simplify(polygon, 0.25))

    # край обличчя на висоті вух — майже пряма, тому вистачає однієї площини
    ears = elements[FACE_EARS]["polygons"][0]
    for planes in ([half_plane(17.6, 66, 22.2, 98, keep_left=True)],
                   [half_plane(109.9, 66, 105.2, 98, keep_left=False)]):
        piece = clip(ears, planes)
        if len(piece) > 3:
            shapes.setdefault("Ear", []).append(simplify(piece, 0.25))

    return normalize([{"name": n, "polygons": p} for n, p in shapes.items()], height=1000)


def write(name, shapes):
    path = os.path.join(LEVELS, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps_level(shapes))
    parts = sum(len(s["polygons"]) for s in shapes)
    points = sum(len(p) for s in shapes for p in s["polygons"])
    print(f"{path}: фігур={len(shapes)} багатокутників={parts} точок={points}")
    print("  " + ", ".join(f"{s['name']}×{len(s['polygons'])}" for s in shapes))


def main():
    write("body", build_body())
    write("face", build_face())


if __name__ == "__main__":
    main()
