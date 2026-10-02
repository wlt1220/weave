#!/usr/bin/env python3
"""Weave demo video renderer: 100% code, numpy + PIL, zero assets.

Usage: python3 render.py chapters.json
chapters.json: [{"scene": "title", "dur": 12.0, ...}, ...]
Writes frames/00001.png … and prints total frames.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
BG = (10, 14, 20)
FG = (230, 237, 243)
GREEN = (126, 231, 135)
BLUE = (121, 192, 255)
ORANGE = (255, 166, 87)
DIM = (139, 148, 158)
TERM_BG = (13, 17, 23)

FD = "/usr/share/fonts/truetype/dejavu/"
F_TITLE = ImageFont.truetype(FD + "DejaVuSans-Bold.ttf", 150)
F_H1 = ImageFont.truetype(FD + "DejaVuSans-Bold.ttf", 72)
F_H2 = ImageFont.truetype(FD + "DejaVuSans-Bold.ttf", 54)
F_BODY = ImageFont.truetype(FD + "DejaVuSans.ttf", 44)
F_SMALL = ImageFont.truetype(FD + "DejaVuSans.ttf", 34)
F_MONO = ImageFont.truetype(FD + "DejaVuSansMono.ttf", 28)
F_MONO_B = ImageFont.truetype(FD + "DejaVuSansMono-Bold.ttf", 28)


def canvas():
    return Image.new("RGB", (W, H), BG)


def centered(d, y, text, font, fill=FG):
    bb = d.textbbox((0, 0), text, font=font)
    d.text(((W - (bb[2] - bb[0])) / 2, y), text, font=font, fill=fill)


def fit_font(text, max_w, size_start=54, name="DejaVuSans-Bold.ttf"):
    size = size_start
    while size > 20:
        f = ImageFont.truetype(FD + name, size)
        bb = f.getbbox(text)
        if bb[2] - bb[0] <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(FD + name, 20)


def wrap(text, font, max_w, d):
    words, lines, cur = text.split(" "), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    lines.append(cur)
    return lines


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def fade_in(t, dur=0.8):
    return min(1.0, t / dur)


# ---------------- scenes ----------------

def s_title(t, dur, **kw):
    img, d = canvas(), None
    img_d = ImageDraw.Draw(img)
    a = fade_in(t)
    # subtle animated glow behind title
    pulse = 0.5 + 0.5 * math.sin(t * 1.2)
    glow = int(20 + 14 * pulse)
    img_d.ellipse([W/2-320, 300, W/2+320, 620], fill=(16, 26+glow//3, 22))
    centered(img_d, 380, "WEAVE", F_TITLE, FG)
    img_d2 = ImageDraw.Draw(img, "RGBA")
    img_d2.text((0, 0), "", fill=(0, 0, 0, 0))
    centered(img_d, 580, "Version Control for the Agent Century", F_H2, GREEN)
    centered(img_d, 700, "github.com/wlt1220/weave", F_BODY, DIM)
    if t > dur - 1.5:
        k = 1 - (t - (dur - 1.5)) / 1.5
        black = Image.new("RGB", (W, H), (0, 0, 0))
        img = Image.blend(img, black, max(0.0, min(1.0, 1 - k)))
    return np.asarray(img)


PROBLEM_LINES = [
    (2.0, "Git was built in 2005 — for humans mailing patches.", FG),
    (8.0, "Agents don't mail patches.", GREEN),
    (14.0, "They write code at machine speed.", GREEN),
    (20.0, "100,000 agents. One repo. At the same time.", ORANGE),
]


def s_problem(t, dur, **kw):
    img = canvas()
    d = ImageDraw.Draw(img)
    y = 200
    for at, text, col in PROBLEM_LINES:
        if t >= at:
            a = fade_in(t - at, 0.6)
            # fade via overlay blend is expensive; just draw (fast enough)
            d.text((180, y), text, font=F_H2, fill=col)
            y += 110
    # tangled branches animation in lower half
    if t > 26:
        k = ease((t - 26) / 6)
        import random
        rnd = random.Random(42)
        for i in range(14):
            x0 = 180 + i * 120
            pts = [(x0, 780)]
            x, yy = x0, 780
            for s in range(6):
                x += rnd.uniform(-90, 90) * k
                yy += 34
                pts.append((x, yy))
            d.line(pts, fill=(60 + i * 8, 90, 130), width=3)
        d.text((180, 1000), "branches  x  pull requests  x  merge conflicts",
               font=F_SMALL, fill=DIM)
    return np.asarray(img)


REFRAME_CARDS = [
    ("INTENT, not diff", "goal · plan · ops · verification · rationale", GREEN),
    ("STREAMS, not branches", "agents publish — the system integrates", BLUE),
    ("NEGOTIATE, don't conflict", "semantic merge · versioned decisions", ORANGE),
]


def s_reframe(t, dur, **kw):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((150, 110), "Version control as event sourcing", font=F_H1, fill=FG)
    # intent log -> fold -> repo diagram
    if t > 2:
        d.text((150, 250), "INTENT LOG  (source of truth)", font=F_SMALL, fill=GREEN)
        intents = ["intent  charge: idempotency", "intent  refund: audit trail",
                   "intent  log: normalize", "intent  …"]
        for i, label in enumerate(intents):
            yy = 300 + i * 64
            d.rounded_rectangle([150, yy, 640, yy + 52], radius=10,
                                outline=GREEN, width=2)
            f = fit_font(label, 460, 28, "DejaVuSansMono.ttf")
            d.text((170, yy + 8), label, font=f, fill=FG)
        # arrow with label above
        ax0, ax1, ay = 700, 920, 460
        d.text((750, ay - 80), "fold", font=F_H2, fill=DIM)
        d.line([(ax0, ay), (ax1, ay)], fill=DIM, width=4)
        d.polygon([(ax1, ay - 14), (ax1 + 28, ay), (ax1, ay + 14)], fill=DIM)
        # repo box
        d.rounded_rectangle([980, 320, 1800, 600], radius=16, outline=BLUE, width=3)
        d.text((1040, 350), "REPO STATE", font=F_H2, fill=BLUE)
        d.text((1040, 440), "(materialized view)", font=F_BODY, fill=DIM)
        rf = fit_font("always consistent · always queryable", 700, 40)
        d.text((1040, 520), "always consistent · always queryable", font=rf, fill=FG)
    # principle cards
    cards = [
        ("INTENT, not diff", "goal · plan · ops · verification · rationale", GREEN),
        ("STREAMS, not branches", "agents publish — the system integrates", BLUE),
        ("NEGOTIATE, don't conflict", "semantic merge · versioned decisions", ORANGE),
    ]
    xs = [100, 681, 1262]
    for i, (title, sub, col) in enumerate(cards):
        at = 8 + i * 3
        if t >= at:
            x0 = xs[i]
            d.rounded_rectangle([x0, 700, x0 + 557, 700 + 230], radius=14,
                                outline=col, width=2)
            tf = fit_font(title, 497, 48)
            d.text((x0 + 30, 730), title, font=tf, fill=col)
            for j, ln in enumerate(wrap(sub, F_SMALL, 497, d)):
                d.text((x0 + 30, 820 + j * 44), ln, font=F_SMALL, fill=FG)
    return np.asarray(img)


ARCH_NODES = [
    (100, 420, 380, 210, "AGENTS", "publish intents", GREEN),
    (560, 420, 380, 210, "WORKERS", "validate · seal", BLUE),
    (1020, 420, 380, 210, "DURABLE OBJECT", "log · trunk · negotiate", ORANGE),
    (1480, 420, 340, 210, "ARTIFACTS", "git bridge", GREEN),
]


def s_arch(t, dur, **kw):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((150, 110), "Coordination plane", font=F_H1, fill=FG)
    d.text((150, 195), "strong ordering exactly where merge order matters — nowhere else",
           font=F_BODY, fill=DIM)
    for i, (x, y, w, h, title, sub, col) in enumerate(ARCH_NODES):
        at = 2 + i * 2.5
        if t >= at:
            d.rounded_rectangle([x, y, x + w, y + h], radius=16, outline=col, width=3)
            tf = fit_font(title, w - 40, 44)
            bb = d.textbbox((0, 0), title, font=tf)
            d.text((x + (w - (bb[2] - bb[0])) / 2, y + 36), title, font=tf, fill=col)
            sf = fit_font(sub, w - 40, 34, "DejaVuSans.ttf")
            bb2 = d.textbbox((0, 0), sub, font=sf)
            d.text((x + (w - (bb2[2] - bb2[0])) / 2, y + 130), sub, font=sf, fill=FG)
        if i > 0 and t >= at:
            x0 = ARCH_NODES[i-1][0] + ARCH_NODES[i-1][2]
            x1 = x
            yy = y + h / 2
            d.line([(x0, yy), (x1, yy)], fill=(60, 70, 85), width=3)
            pk = ((t - at) * 0.7) % 1.0
            px = x0 + (x1 - x0) * pk
            r = 10
            d.ellipse([px - r, yy - r, px + r, yy + r], fill=col)
    if t > 14:
        d.text((180, 720), "POST /v1/streams/:s/intents   →   sealed   →   integrated   →   mirrored to git",
               font=F_MONO, fill=DIM)
        d.text((180, 780), "no receipt, no merge  ·  negotiation winners fold  ·  rebase-and-retry drains pending",
               font=F_MONO, fill=DIM)
    return np.asarray(img)


def s_closing(t, dur, **kw):
    img = canvas()
    d = ImageDraw.Draw(img)
    a = fade_in(t)
    centered(d, 360, "Same ambition.", F_H1, FG)
    centered(d, 470, "Runs today.", F_H1, GREEN)
    if t > 3:
        centered(d, 640, "github.com/wlt1220/weave", F_H2, BLUE)
        centered(d, 730, "MIT licensed · built with Workers + Artifacts", F_BODY, DIM)
    if t > dur - 2:
        k = (t - (dur - 2)) / 2
        black = Image.new("RGB", (W, H), (0, 0, 0))
        img = Image.blend(img, black, max(0.0, min(1.0, k)))
    return np.asarray(img)


# ---------------- terminal ----------------

def load_term(path):
    with open(path) as f:
        return f.read()


def s_terminal(t, dur, cmd, text, highlights=(), **kw):
    """Type `cmd`, then reveal `text` fast; cycle highlight over key lines."""
    img = canvas()
    d = ImageDraw.Draw(img)
    # window
    x0, y0, x1, y1 = 120, 90, 1800, 990
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=TERM_BG,
                        outline=(48, 54, 65), width=2)
    d.rounded_rectangle([x0, y0, x1, y0 + 56], radius=18, fill=(22, 27, 36))
    d.rectangle([x0, y0 + 28, x1, y0 + 56], fill=(22, 27, 36))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([x0 + 28 + i * 32, y0 + 18, x0 + 48 + i * 32, y0 + 38], fill=c)
    d.text((x0 + 140, y0 + 12), "weave — agent terminal", font=F_SMALL, fill=DIM)

    tx, ty = x0 + 40, y0 + 90
    line_h = 38
    max_lines = (y1 - ty - 30) // line_h

    # type the command
    type_dur = len(cmd) / 28.0
    n_chars = min(len(cmd), int(t / type_dur * len(cmd))) if t < type_dur else len(cmd)
    d.text((tx, ty), "$ ", font=F_MONO_B, fill=GREEN)
    d.text((tx + 42, ty), cmd[:n_chars], font=F_MONO, fill=FG)
    if t < type_dur + 0.4 and (int(t * 3) % 2 == 0):
        cx = tx + 42 + d.textlength(cmd[:n_chars], font=F_MONO)
        d.rectangle([cx, ty + 4, cx + 16, ty + 32], fill=GREEN)
    ty += line_h

    if t > type_dur:
        ot = t - type_dur
        # reveal output fast; wrap long lines instead of truncating
        reveal_chars = int(ot * 2500)
        raw_lines = text[:reveal_chars].split("\n")
        shown = []
        for ln in raw_lines:
            while d.textlength(ln, font=F_MONO) > (x1 - tx - 60):
                cut = min(105, len(ln) - 1)
                while cut > 80 and ln[cut] not in (" ", ";", ","):
                    cut -= 1
                shown.append(ln[:cut])
                ln = "  " + ln[cut:].lstrip()
            shown.append(ln)
        # keep last max_lines
        if len(shown) > max_lines:
            shown = shown[-max_lines:]
        for i, line in enumerate(shown):
            col = FG
            ls = line.strip()
            if ls.startswith("→") or ls.startswith("✓"):
                col = GREEN
            elif "negotiation" in ls.lower() or "escalat" in ls.lower():
                col = ORANGE
            elif ls.startswith("---") or ls.startswith("==="):
                col = BLUE
            d.text((tx, ty + i * line_h), line, font=F_MONO, fill=col)
        # cycling highlight on key lines during hold
        if highlights and reveal_chars >= len(text):
            keys = [ln for ln in text.split("\n") if any(h in ln for h in highlights)]
            if keys:
                idx = int((ot - len(text) / 2500) / 4) % len(keys)
                target = keys[idx][:60]
                for i, line in enumerate(shown):
                    if target in line:
                        yy = ty + i * line_h - 4
                        d.rounded_rectangle([tx - 12, yy, x1 - 30, yy + line_h],
                                            radius=8, outline=ORANGE, width=2)
                        break
    return np.asarray(img)


def s_concurrency(t, dur, text, **kw):
    img = canvas()
    d = ImageDraw.Draw(img)
    # left: terminal replay (compact)
    x0, y0, x1, y1 = 80, 90, 1180, 990
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=TERM_BG,
                        outline=(48, 54, 65), width=2)
    tx, ty = x0 + 30, y0 + 70
    line_h = 34
    d.text((tx, ty), "$ python3 loadtest.py --agents 20 --intents 5", font=F_MONO, fill=FG)
    ty += line_h * 2
    reveal = int(t * 900)
    shown = text[:reveal].split("\n")[-22:]
    for i, line in enumerate(shown):
        col = GREEN if ("folded" in line or "100" in line) else FG
        d.text((tx, ty + i * line_h), line[:72], font=F_MONO, fill=col)
    # right: big counters
    cx = 1300
    ramp = ease(min(1.0, t / 12))
    d.text((cx, 140), "INTENTS", font=F_SMALL, fill=DIM)
    d.text((cx, 180), f"{int(100 * ramp)}", font=F_TITLE, fill=FG)
    d.text((cx, 390), "AGENTS", font=F_SMALL, fill=DIM)
    d.text((cx, 430), f"{int(20 * ramp)}", font=F_TITLE, fill=FG)
    d.text((cx, 640), "FOLDED", font=F_SMALL, fill=DIM)
    d.text((cx, 680), f"{int(100 * ramp)}", font=F_TITLE, fill=GREEN)
    d.text((cx, 870), "ERRORS", font=F_SMALL, fill=DIM)
    d.text((cx, 910), "0", font=F_TITLE, fill=FG)
    return np.asarray(img)


SCENES = {
    "title": s_title,
    "problem": s_problem,
    "reframe": s_reframe,
    "arch": s_arch,
    "closing": s_closing,
    "term_demo1": lambda t, dur, **kw: s_terminal(
        t, dur, cmd="weave demo", text=load_term("term_demo1.txt"),
        highlights=["disjoint cones", "negotiation opened", "escalating"]),
    "term_demo2": lambda t, dur, **kw: s_terminal(
        t, dur, cmd="weave demo-remote --stream demo", text=load_term("term_demo2.txt"),
        highlights=["integrated=True", "awaiting_verification", "negotiation="]),
    "term_why": lambda t, dur, **kw: s_terminal(
        t, dur, cmd="weave why payments.py", text=load_term("term_why.txt"),
        highlights=["rationale:", "verified: True"]),
    "concurrency": lambda t, dur, **kw: s_concurrency(t, dur, text=load_term("term_load.txt")),
}


def main():
    chapters = json.load(open(sys.argv[1]))
    outdir = Path("frames")
    outdir.mkdir(exist_ok=True)
    # clear old frames
    for p in outdir.glob("*.png"):
        p.unlink()
    n = 0
    total = 0
    for ch in chapters:
        fn = SCENES[ch["scene"]]
        dur = ch["dur"]
        frames = int(dur * FPS)
        print(f"scene {ch['scene']}: {dur:.1f}s = {frames} frames", flush=True)
        for f in range(frames):
            t = f / FPS
            arr = fn(t, dur)
            Image.fromarray(arr).save(outdir / f"{n:05d}.png")
            n += 1
        total += dur
    print(f"TOTAL {n} frames, {total:.1f}s")


if __name__ == "__main__":
    main()
