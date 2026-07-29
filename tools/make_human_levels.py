#!/usr/bin/env python3
"""Малює рівні «Body» і «Face» — людину спереду й обличчя.

Тут немає жодного зовнішнього джерела даних: фігури рахуються формулами.
Парні частини (очі, вуха, руки, ноги) — це одна фігура з двох багатокутників,
бо в форматі рівня ідентифікатор фігури — її назва.

    python3 tools/make_human_levels.py
"""

import json
import math
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "levels")


def ellipse(cx, cy, rx, ry, steps=28, start=0.0, end=math.tau):
    span = end - start
    return [[round(cx + rx * math.cos(start + span * i / steps), 1),
             round(cy + ry * math.sin(start + span * i / steps), 1)]
            for i in range(steps + (0 if span >= math.tau - 1e-9 else 1))]


def capsule(x0, y0, x1, y1, width, steps=10):
    """Витягнута фігура з круглими кінцями — рука, нога, палець."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    r = width / 2
    points = []
    for i in range(steps + 1):                       # півколо навколо кінця (x1, y1)
        a = math.pi * i / steps
        points.append((x1 + nx * r * math.cos(a) + ux * r * math.sin(a),
                       y1 + ny * r * math.cos(a) + uy * r * math.sin(a)))
    for i in range(steps + 1):                       # і назад навколо кінця (x0, y0)
        a = math.pi * i / steps
        points.append((x0 - nx * r * math.cos(a) - ux * r * math.sin(a),
                       y0 - ny * r * math.cos(a) - uy * r * math.sin(a)))
    return [[round(x, 1), round(y, 1)] for x, y in points]


def mirror(polygon, axis):
    return [[round(2 * axis - x, 1), y] for x, y in reversed(polygon)]


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


def body():
    """Людина спереду; вісь симетрії — x = 300."""
    axis = 300

    upper_arm = capsule(214, 242, 196, 348, 34)
    forearm = capsule(193, 376, 184, 452, 29)
    elbow = ellipse(195, 362, 20, 18)
    hand = ellipse(180, 480, 21, 29)
    shoulder = ellipse(241, 219, 38, 27)

    thigh = capsule(278, 540, 272, 688, 46)
    shin = capsule(268, 738, 262, 838, 36)
    knee = ellipse(270, 712, 24, 23)
    foot = [[240, 846], [286, 846], [290, 874], [216, 874], [220, 858]]

    return [
        {"name": "Head", "polygons": [ellipse(axis, 100, 48, 60)]},
        {"name": "Neck", "polygons": [[[282, 152], [318, 152], [322, 198], [278, 198]]]},
        {"name": "Shoulder", "polygons": [shoulder, mirror(shoulder, axis)]},
        {"name": "Chest", "polygons": [[[240, 198], [360, 198], [368, 290], [364, 340],
                                        [236, 340], [232, 290]]]},
        {"name": "Belly", "polygons": [[[236, 340], [364, 340], [352, 468], [338, 520],
                                        [262, 520], [248, 468]]]},
        {"name": "Arm", "polygons": [upper_arm, forearm,
                                     mirror(upper_arm, axis), mirror(forearm, axis)]},
        {"name": "Elbow", "polygons": [elbow, mirror(elbow, axis)]},
        {"name": "Hand", "polygons": [hand, mirror(hand, axis)]},
        {"name": "Leg", "polygons": [thigh, shin, mirror(thigh, axis), mirror(shin, axis)]},
        {"name": "Knee", "polygons": [knee, mirror(knee, axis)]},
        {"name": "Foot", "polygons": [foot, mirror(foot, axis)]},
    ]


def face():
    """Обличчя анфас. Велике «Face» лежить під низом, деталі — поверх нього:
    двіжок сам малює дрібніші фігури вище, тому клік завжди влучає у деталь."""
    axis = 300
    cy, rx, ry = 380, 175, 225

    hair_outer = ellipse(axis, cy - 6, rx + 8, ry + 12, steps=24,
                         start=math.pi * 1.06, end=math.pi * 1.94)
    hair = hair_outer + [[452, 292], [420, 258], [366, 242], [300, 254],
                         [234, 242], [180, 258], [148, 292]]

    forehead = ellipse(axis, 300, 118, 52)
    cheek = ellipse(222, 452, 62, 52)
    eye = ellipse(238, 362, 36, 21)
    brow = [[198, 316], [238, 296], [280, 312], [278, 332], [238, 314], [200, 334]]
    ear = ellipse(126, 392, 22, 44)

    return [
        {"name": "Face", "polygons": [ellipse(axis, cy, rx, ry, steps=36)]},
        {"name": "Hair", "polygons": [hair]},
        {"name": "Forehead", "polygons": [forehead]},
        {"name": "Eyebrow", "polygons": [brow, mirror(brow, axis)]},
        {"name": "Eye", "polygons": [eye, mirror(eye, axis)]},
        {"name": "Nose", "polygons": [[[300, 372], [318, 440], [326, 462], [300, 472],
                                       [274, 462], [282, 440]]]},
        {"name": "Mouth", "polygons": [ellipse(axis, 532, 54, 21)]},
        {"name": "Cheek", "polygons": [cheek, mirror(cheek, axis)]},
        {"name": "Chin", "polygons": [ellipse(axis, 572, 66, 34)]},
        {"name": "Ear", "polygons": [ear, mirror(ear, axis)]},
    ]


def main():
    for name, shapes in (("body", body()), ("face", face())):
        path = os.path.join(OUT_DIR, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dumps_level(shapes))
        points = sum(len(p) for s in shapes for p in s["polygons"])
        print(f"{path}: фігур={len(shapes)} точок={points}")


if __name__ == "__main__":
    main()
