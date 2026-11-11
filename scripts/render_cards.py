"""Render the profile story cards and embed WOFF fonts via fontTools.subset."""

import base64
import hashlib
import html
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "profile.json"
DATA_PATH = ROOT / "data" / "contributions.json"
OUT_DIR = ROOT / "cards"
README_PATH = ROOT / "README.md"
PREVIEW_PATH = ROOT / "preview.html"
FONT_DIR = ROOT / "assets" / "fonts"

FONT_SPECS = {
    ("Instrument Serif", 400, "normal"): ("InstrumentSerif-Regular.ttf", None),
    ("Instrument Serif", 400, "italic"): ("InstrumentSerif-Italic.ttf", None),
    ("Geist", 400, "normal"): ("Geist.ttf", {"wght": 400}),
    ("Geist", 500, "normal"): ("Geist.ttf", {"wght": 500}),
    ("Geist", 600, "normal"): ("Geist.ttf", {"wght": 600}),
    ("Geist Mono", 400, "normal"): ("GeistMono.ttf", {"wght": 400}),
    ("Geist Mono", 500, "normal"): ("GeistMono.ttf", {"wght": 500}),
    ("Newsreader", 400, "normal"): ("Newsreader.ttf", {"wght": 400, "opsz": 18}),
    ("Newsreader", 400, "italic"): ("Newsreader-Italic.ttf", {"wght": 400, "opsz": 18}),
    ("Newsreader", 500, "normal"): ("Newsreader.ttf", {"wght": 500, "opsz": 18}),
}

FONT_URLS = {
    "InstrumentSerif-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf",
    "InstrumentSerif-Italic.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf",
    "Geist.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/geist/Geist%5Bwght%5D.ttf",
    "GeistMono.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/geistmono/GeistMono%5Bwght%5D.ttf",
    "Newsreader.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/newsreader/Newsreader%5Bopsz,wght%5D.ttf",
    "Newsreader-Italic.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/newsreader/Newsreader-Italic%5Bopsz,wght%5D.ttf",
}

PAPER = "#F3F3F1"
PAPER_2 = "#EBEBE7"
INK = "#111111"
INK_SOFT = "#3A3A3C"
MUTED = "#6E6E73"
SOFT = "#8E8E93"
RULE = "#DCDCD7"
RULE_SOFT = "#E6E6E1"
ACCENT = "#2F55FF"
ACCENT_SOFT = "#C8D3FF"
WHITE = "#FFFFFF"

BASE_CSS = """
text{font-family:'Geist',ui-sans-serif,system-ui,-apple-system,sans-serif;font-variant-ligatures:none}
.serif{font-family:'Instrument Serif',Georgia,serif}
.body{font-family:'Newsreader',Georgia,'Times New Roman',serif}
.mono{font-family:'Geist Mono','SF Mono',ui-monospace,monospace}
.rise{opacity:0;transform:translateY(10px);animation:rise .7s cubic-bezier(.16,.84,.28,1) forwards;animation-delay:calc(var(--d,0s))}
@keyframes rise{to{opacity:1;transform:translateY(0)}}
.fade{opacity:0;animation:fade .6s ease forwards;animation-delay:calc(var(--d,0s))}
@keyframes fade{to{opacity:1}}
.settle{opacity:0;transform:translateY(12px) scale(.985);animation:settle .85s cubic-bezier(.16,.84,.28,1) forwards;animation-delay:calc(var(--d,0s))}
@keyframes settle{to{opacity:1;transform:translateY(0) scale(1)}}
.grow{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .7s cubic-bezier(.16,.84,.28,1) forwards;animation-delay:calc(var(--d,0s))}
@keyframes grow{to{transform:scaleY(1)}}
.growx{transform-box:fill-box;transform-origin:left;transform:scaleX(0);animation:growx .7s cubic-bezier(.16,.84,.28,1) forwards;animation-delay:calc(var(--d,0s))}
@keyframes growx{to{transform:scaleX(1)}}
.pulse{animation:pulse 4.2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
@media (prefers-reduced-motion: reduce){
  .rise,.fade,.settle,.grow,.growx,.pulse{animation:none!important;opacity:1!important;transform:none!important}
}
"""

_font_cache = {}


def num(value):
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def esc(value):
    return html.escape(str(value), quote=True)


def fmt_int(value):
    return f"{int(value):,}"


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def rect(x, y, w, h, fill, rx=0, stroke=None, sw=1, opacity=None, cls=None, style=None, children=""):
    attrs = [f'x="{num(x)}"', f'y="{num(y)}"', f'width="{num(w)}"', f'height="{num(h)}"', f'fill="{fill}"']
    if rx:
        attrs.append(f'rx="{num(rx)}"')
    if stroke:
        attrs.append(f'stroke="{stroke}"')
        attrs.append(f'stroke-width="{num(sw)}"')
    if opacity is not None:
        attrs.append(f'opacity="{num(opacity)}"')
    if cls:
        attrs.append(f'class="{cls}"')
    if style:
        attrs.append(f'style="{style}"')
    inner = f">{children}</rect>" if children else "/>"
    return f'<rect {" ".join(attrs)}{inner}'


def circle(cx, cy, r, fill, stroke=None, sw=1, opacity=None, cls=None, style=None):
    attrs = [f'cx="{num(cx)}"', f'cy="{num(cy)}"', f'r="{num(r)}"', f'fill="{fill}"']
    if stroke:
        attrs.append(f'stroke="{stroke}"')
        attrs.append(f'stroke-width="{num(sw)}"')
    if opacity is not None:
        attrs.append(f'opacity="{num(opacity)}"')
    if cls:
        attrs.append(f'class="{cls}"')
    if style:
        attrs.append(f'style="{style}"')
    return f'<circle {" ".join(attrs)}/>'


def line(x1, y1, x2, y2, stroke, sw=1, opacity=None, dash=None, cls=None, style=None):
    attrs = [f'x1="{num(x1)}"', f'y1="{num(y1)}"', f'x2="{num(x2)}"', f'y2="{num(y2)}"', f'stroke="{stroke}"', f'stroke-width="{num(sw)}"']
    if opacity is not None:
        attrs.append(f'opacity="{num(opacity)}"')
    if dash:
        attrs.append(f'stroke-dasharray="{dash}"')
    if cls:
        attrs.append(f'class="{cls}"')
    if style:
        attrs.append(f'style="{style}"')
    return f'<line {" ".join(attrs)}/>'


_metrics_cache = {}


def text_width(value, font, size, weight=400, italic=False, ls=0.0):
    family, resolved, style = font_target(font, weight, italic)
    key = (family, resolved, style)
    if key not in _metrics_cache:
        try:
            from fontTools.ttLib import TTFont
            from fontTools.varLib.instancer import instantiateVariableFont
        except ModuleNotFoundError:
            raise SystemExit("fontTools is required. Run: pip install -r requirements.txt")
        filename, axes = FONT_SPECS[key]
        measured = TTFont(str(FONT_DIR / filename))
        if axes:
            measured = instantiateVariableFont(measured, axes)
        _metrics_cache[key] = (measured.getBestCmap(), measured["head"].unitsPerEm, measured["hmtx"])
    cmap, upem, hmtx = _metrics_cache[key]
    total = 0
    for char in str(value):
        glyph = cmap.get(ord(char)) or cmap.get(ord(" "))
        total += hmtx.metrics[glyph][0]
    return total * size / upem + ls * len(str(value))


def wrap_pixels(value, max_width, font, size, max_lines, weight=400, italic=False, ls=0.0):
    words = str(value).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or text_width(candidate, font, size, weight, italic, ls) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip(" .,")
        while last and text_width(f"{last}…", font, size, weight, italic, ls) > max_width:
            last = last[:-1].rstrip(" .,")
        lines[-1] = f"{last}…" if last else "…"
    return lines


def ensure_fonts():
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in FONT_URLS.items():
        font_path = FONT_DIR / filename
        if font_path.exists():
            continue
        print(f"Downloading {filename}", file=sys.stderr)
        request = urllib.request.Request(url, headers={"User-Agent": "theanugrahh-profile-cards"})
        with urllib.request.urlopen(request, timeout=30) as response:
            font_path.write_bytes(response.read())


def font_target(font, weight, italic=False):
    if font == "serif":
        return ("Instrument Serif", 400, "italic" if italic else "normal")
    if font == "body":
        return ("Newsreader", 500 if weight >= 500 else 400, "italic" if italic else "normal")
    if font == "mono":
        return ("Geist Mono", 500 if weight >= 500 else 400, "normal")
    return ("Geist", 600 if weight >= 600 else 500 if weight >= 500 else 400, "normal")


def subset_font(family, weight, style, chars):
    key = (family, weight, style, "".join(sorted(chars)))
    if key in _font_cache:
        return _font_cache[key]
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ModuleNotFoundError:
        raise SystemExit("fontTools is required. Run: pip install -r requirements.txt")
    filename, axes = FONT_SPECS[(family, weight, style)]
    font = TTFont(str(FONT_DIR / filename))
    if axes:
        font = instantiateVariableFont(font, axes)
    options = subset.Options()
    options.flavor = "woff"
    options.desubroutinize = True
    options.layout_features = ["kern", "liga", "clig", "calt"]
    options.notdef_outline = True
    options.drop_tables += ["DSIG"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    font.flavor = "woff"
    buffer = io.BytesIO()
    font.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    _font_cache[key] = encoded
    return encoded


def font_css(fonts, chars):
    faces = []
    for family, weight, style in sorted(fonts):
        data = subset_font(family, weight, style, chars)
        faces.append(
            f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
            f"src:url(data:font/woff;base64,{data}) format('woff');}}"
        )
    return "".join(faces)


class Card:
    def __init__(self, width, height, label, base=0.0, static=False):
        self.width = width
        self.height = height
        self.label = label
        self.base = base
        self.static = static
        self.parts = []
        self.chars = set(" 0123456789")
        self.fonts = set()

    def add(self, markup):
        self.parts.append(markup)
        return markup

    def text(self, x, y, value, size=12, fill=INK_SOFT, weight=400, font="sans", anchor="start", ls=None, opacity=None, italic=False):
        self.chars.update(str(value))
        family, resolved, style = font_target(font, weight, italic)
        self.fonts.add((family, resolved, style))
        attrs = [f'x="{num(x)}"', f'y="{num(y)}"', f'font-size="{num(size)}"', f'fill="{fill}"', f'font-weight="{resolved}"']
        if style != "normal":
            attrs.append(f'font-style="{style}"')
        if font == "serif":
            attrs.append('class="serif"')
        elif font == "body":
            attrs.append('class="body"')
        elif font == "mono":
            attrs.append('class="mono"')
        if anchor != "start":
            attrs.append(f'text-anchor="{anchor}"')
        if ls is not None:
            attrs.append(f'letter-spacing="{num(ls)}"')
        if opacity is not None:
            attrs.append(f'opacity="{num(opacity)}"')
        return f'<text {" ".join(attrs)}>{esc(value)}</text>'

    def wrap(self, content, cls="rise", d=0.0, style=None):
        if self.static:
            return content
        inline = f"--d:{num(d)}s"
        if style:
            inline += f";{style}"
        return f'<g class="{cls}" style="{inline}">{content}</g>'

    def render(self, extra_css=""):
        font = font_css(self.fonts, self.chars)
        base_style = "" if self.static else f' style="--base:{num(self.base)}s"'
        body = "\n".join(self.parts)
        title = f"<title>{esc(self.label)}</title>" if self.label else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{esc(self.label)}"{base_style}>\n'
            f"{title}\n<style>{BASE_CSS}{font}{extra_css}</style>\n"
            f"{body}\n</svg>\n"
        )


def image_data(path):
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = ROOT / file_path
    if not file_path.exists():
        return None
    suffix = file_path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"


def kicker(card, x, y, value, d=0.0, live=False):
    content = rect(x, y - 7, 5, 5, ACCENT, cls="pulse" if live and not card.static else None)
    content += card.text(x + 14, y, value.upper(), size=9.5, fill=MUTED, weight=500, font="mono", ls=2.1)
    return card.wrap(content, d=d)


def paragraph(card, x, y, value, width_px, size=14, leading=22, max_lines=6, fill=INK_SOFT, font="body"):
    content = ""
    for index, line_value in enumerate(wrap_pixels(value, width_px, font, size, max_lines)):
        content += card.text(x, y + index * leading, line_value, size=size, fill=fill, font=font)
    return content


def fmt_two(value):
    number = int(value or 0)
    return f"{number:02d}" if number < 100 else str(number)


def fmt_short_date(value):
    if not value:
        return "n/a"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b").upper().lstrip("0")
    except ValueError:
        return "n/a"


def truncate(value, limit):
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


LANGUAGE_PALETTE = [ACCENT, "#6280FF", "#94A8FF", ACCENT_SOFT, "#DCDCD7", "#C9C9C4"]


def language_color(index, name):
    if name == "Other":
        return RULE
    return LANGUAGE_PALETTE[index % len(LANGUAGE_PALETTE)]


def stat_box(card, x, y, w, h, value, label, d=0.0):
    box = rect(x, y, w, h, PAPER_2, rx=10)
    card.add(card.wrap(box, cls="fade", d=d))
    card.add(card.wrap(card.text(x + 14, y + 40, value, size=27, fill=INK, font="serif", ls=-0.4), cls="settle", d=d + 0.04))
    card.add(card.wrap(card.text(x + 14, y + 64, label.upper(), size=8.4, fill=MUTED, font="mono", ls=1.2), cls="fade", d=d + 0.08))


def render_link_card(profile, kind, static):
    links = profile["links"]
    if kind == "email":
        label, value, description = "EMAIL", links["email"], "Email Anugrah"
    else:
        label, value, description = "LINKEDIN", "in/anugrahkrishnaasreejith", "LinkedIn"
    card = Card(380, 48, description, 0.0, static)
    card.add(rect(0, 0, 380, 48, PAPER_2, rx=10, stroke=RULE_SOFT))
    card.add(circle(16, 24, 3, ACCENT))
    card.add(card.text(28, 28, label, size=9.2, fill=ACCENT, font="mono", ls=1.4))
    card.add(card.text(364, 28, value, size=12.5, fill=INK, font="body", anchor="end"))
    return card.render()


def render_hero(profile, data, static):
    card = Card(880, 380, f"{profile['display_name']}, {profile['role']}", 0.0, static)
    card.add(rect(0, 0, 880, 380, PAPER, rx=14))

    card.add(kicker(card, 56, 54, profile["role"], d=0.02))
    availability = (profile.get("availability") or profile.get("status") or "").upper()
    card.add(card.wrap(card.text(824, 54, availability, size=9, fill=SOFT, font="mono", anchor="end", ls=1.7), cls="fade", d=0.08))

    name_lines = profile.get("name_lines") or [profile["display_name"]]
    first = name_lines[0]
    second = name_lines[1] if len(name_lines) > 1 else ""
    card.add(card.wrap(card.text(56, 168, first, size=78, fill=INK, font="serif", ls=-1.1), d=0.12))
    if second:
        card.add(card.wrap(card.text(56, 238, second, size=68, fill=INK, font="serif", ls=-1.2, italic=True), d=0.22))

    tagline = ""
    for index, value in enumerate(wrap_pixels(profile["tagline"], 560, "body", 18, 2)):
        tagline += card.text(56, 285 + index * 25, value, size=18, fill=INK_SOFT, font="body")
    card.add(card.wrap(tagline, d=0.32))

    card.add(card.wrap(line(56, 336, 824, 336, RULE), cls="fade", d=0.4))
    bottom_left = circle(60, 354, 3, ACCENT)
    bottom_left += card.text(72, 358, (profile.get("focus") or "AI/ML engineer in training").upper(), size=9, fill=MUTED, font="mono", ls=1.5)
    card.add(card.wrap(bottom_left, cls="fade", d=0.46))
    now = (profile.get("currently") or "").upper()
    if now:
        card.add(card.wrap(card.text(824, 358, f"NOW · {now}", size=9, fill=MUTED, font="mono", anchor="end", ls=1.4), cls="fade", d=0.52))

    portrait = profile.get("portrait")
    if portrait:
        encoded = image_data(portrait)
        if encoded:
            card.add(card.wrap(rect(640, 70, 180, 180, PAPER_2, rx=18), cls="fade", d=0.18))
            card.add(
                card.wrap(
                    f'<image href="{encoded}" x="640" y="70" width="180" height="180" '
                    'preserveAspectRatio="xMidYMid slice" clip-path="url(#portraitClip)"/>',
                    cls="settle",
                    d=0.2,
                )
            )
            card.add(card.wrap(rect(640.5, 70.5, 179, 179, "none", rx=17.5, stroke=RULE), cls="fade", d=0.26))
            # The clip path is declared after use, which is valid SVG and keeps the markup flat.
            card.parts.insert(1, '<defs><clipPath id="portraitClip"><rect x="640" y="70" width="180" height="180" rx="18"/></clipPath></defs>')
        else:
            print(f"warning: portrait not found at {portrait}", file=sys.stderr)

    return card.render()


def render_story(profile, data, static):
    story = profile.get("story") or {}
    card = Card(880, 420, "The point: building systems that make real impact", 0.5, static)
    card.add(rect(0, 0, 880, 420, PAPER, rx=14))

    card.add(kicker(card, 56, 50, story.get("kicker") or "The point", d=0.02))
    card.add(card.wrap(card.text(56, 116, story.get("headline") or "I build systems that make real impact.", size=44, fill=INK, font="serif", ls=-0.7), d=0.1))
    card.add(card.wrap(line(56, 142, 824, 142, RULE), cls="fade", d=0.18))

    lead = story.get("lead") or ""
    if lead:
        card.add(card.wrap(paragraph(card, 56, 186, lead, 760, size=19, leading=28, max_lines=3, fill=INK), d=0.22))

    card.add(card.wrap(line(56, 264, 824, 264, RULE_SOFT), cls="fade", d=0.3))
    card.add(card.wrap(card.text(56, 288, "HOW I WORK", size=10, fill=MUTED, font="mono", ls=1.8), cls="fade", d=0.34))

    principles = story.get("principles") or []
    box_w, box_gap = 248, 16
    for index, item in enumerate(principles[:3]):
        x = 56 + index * (box_w + box_gap)
        y = 310
        card.add(card.wrap(rect(x, y, box_w, 86, PAPER_2, rx=10, stroke=RULE_SOFT), cls="fade", d=0.38 + index * 0.05))
        card.add(card.wrap(card.text(x + 14, y + 24, f"0{index + 1} · {item.get('label', '').upper()}", size=8.6, fill=ACCENT, font="mono", ls=1.4), cls="fade", d=0.42 + index * 0.05))
        card.add(card.wrap(paragraph(card, x + 14, y + 48, item.get("text", ""), 218, size=14, leading=19, max_lines=2, fill=INK_SOFT), cls="fade", d=0.46 + index * 0.05))

    return card.render()


def render_middle(profile, data, static):
    middle = profile.get("middle") or {}
    card = Card(880, 340, "The unglamorous middle", 0.7, static)
    card.add(rect(0, 0, 880, 340, PAPER, rx=14))

    card.add(kicker(card, 56, 50, middle.get("kicker") or "The part that matters", d=0.02))
    card.add(card.wrap(card.text(56, 116, middle.get("headline") or "I care about the unglamorous middle.", size=44, fill=INK, font="serif", ls=-0.7), d=0.1))
    card.add(card.wrap(line(56, 142, 824, 142, RULE), cls="fade", d=0.18))
    card.add(card.wrap(paragraph(card, 56, 186, middle.get("body") or "", 760, size=17.5, leading=26, max_lines=5, fill=INK_SOFT), d=0.24))

    return card.render()


def render_flow(profile, data, static):
    flow = profile.get("flow") or {}
    card = Card(880, 520, "The flow from problem to impact", 0.85, static)
    card.add(rect(0, 0, 880, 520, PAPER, rx=14))

    card.add(kicker(card, 56, 50, flow.get("kicker") or "The flow", d=0.02))
    card.add(card.wrap(card.text(56, 112, flow.get("headline") or "Start with the problem.", size=33, fill=INK, font="serif", ls=-0.5), d=0.1))
    card.add(card.wrap(line(56, 138, 824, 138, RULE), cls="fade", d=0.18))

    steps = flow.get("steps") or []
    box_w, box_h, box_gap, col_gap = 376, 120, 16, 16
    positions = [(56, 168), (56 + box_w + col_gap, 168), (56 + box_w + col_gap, 306), (56, 306)]
    for index, item in enumerate(steps[:4]):
        x, y = positions[index]
        card.add(card.wrap(rect(x, y, box_w, box_h, PAPER_2, rx=10, stroke=RULE_SOFT), cls="fade", d=0.24 + index * 0.05))
        card.add(card.wrap(card.text(x + 16, y + 28, f"0{index + 1} · {item.get('label', '').upper()}", size=9.2, fill=ACCENT, font="mono", ls=1.5), cls="fade", d=0.28 + index * 0.05))
        card.add(card.wrap(paragraph(card, x + 16, y + 54, item.get("text", ""), 344, size=15.5, leading=21, max_lines=3, fill=INK_SOFT), cls="fade", d=0.32 + index * 0.05))

    card.add(card.wrap(card.text(440, 234, "→", size=14, fill=SOFT, font="mono", anchor="middle"), cls="fade", d=0.44))
    card.add(card.wrap(card.text(636, 298, "↓", size=14, fill=SOFT, font="mono", anchor="middle"), cls="fade", d=0.46))
    card.add(card.wrap(card.text(440, 372, "←", size=14, fill=SOFT, font="mono", anchor="middle"), cls="fade", d=0.48))

    closing = flow.get("closing") or ""
    if closing:
        card.add(card.wrap(paragraph(card, 56, 458, closing, 760, size=17, leading=24, max_lines=2, fill=INK), cls="fade", d=0.52))

    return card.render()


def render_public(profile, data, static):
    card = Card(880, 620, "Public repositories on GitHub", 0.95, static)
    card.add(rect(0, 0, 880, 620, PAPER, rx=14))

    card.add(kicker(card, 56, 50, "In public", d=0.02, live=True))
    synced = fmt_short_date(data.get("generated_at", ""))
    card.add(card.wrap(card.text(824, 50, f"PUBLIC ONLY · SYNCED {synced}", size=9, fill=SOFT, font="mono", anchor="end", ls=1.5), cls="fade", d=0.06))

    public_repos = data.get("public_repos", 0)
    card.add(card.wrap(card.text(56, 150, fmt_two(public_repos), size=64, fill=INK, font="serif", ls=-1.2), d=0.08))
    card.add(card.wrap(card.text(56, 178, "PUBLIC REPOSITORIES", size=10, fill=MUTED, font="mono", ls=1.7), d=0.1))
    card.add(card.wrap(paragraph(card, 56, 202, "Public repositories I own. This updates when I publish or archive one.", 262, size=13.5, leading=19, max_lines=2), cls="fade", d=0.14))

    stats = data.get("stats", {})
    languages = data.get("languages", [])
    repos = data.get("repos", [])
    named = [item for item in languages if item["name"] != "Other"]
    last_push = fmt_short_date(stats.get("last_push", ""))
    boxes = [
        (fmt_two(stats.get("total_contributions", 0)), "contributions"),
        (fmt_two(stats.get("active_days", 0)), "active days"),
        (fmt_two(len(named)), "languages"),
        (last_push, "last push"),
    ]
    box_x, box_w, box_gap, box_y, box_h = 350, 110, 10, 116, 86
    for index, (value, label) in enumerate(boxes):
        stat_box(card, box_x + index * (box_w + box_gap), box_y, box_w, box_h, value, label, d=0.16 + index * 0.04)

    card.add(card.wrap(card.text(56, 252, "LANGUAGES · BY PUBLIC REPOSITORY", size=9.5, fill=MUTED, font="mono", ls=1.8), cls="fade", d=0.32))
    bar_y, bar_h, bar_w = 268, 9, 768
    total_repos = sum(item["count"] for item in languages) or 1
    offset = 0.0
    for index, item in enumerate(languages):
        segment = bar_w * item["count"] / total_repos
        card.add(
            card.wrap(
                rect(56 + offset, bar_y, segment, bar_h, language_color(index, item["name"]), rx=4),
                cls="growx",
                d=0.36 + index * 0.05,
            )
        )
        offset += segment
    legend_x = 56
    for index, item in enumerate(languages[:5]):
        color = language_color(index, item["name"])
        card.add(card.wrap(circle(legend_x + 4, 298, 4, color), cls="fade", d=0.42 + index * 0.04))
        card.add(
            card.wrap(
                card.text(legend_x + 14, 302, f"{item['name']} · {item['count']}", size=10, fill=INK_SOFT),
                cls="fade",
                d=0.44 + index * 0.04,
            )
        )
        legend_x += 152

    shown = min(len(repos), 4)
    card.add(card.wrap(card.text(56, 348, f"RECENT PUBLIC WORK · {shown} OF {public_repos}", size=9.5, fill=MUTED, font="mono", ls=1.8), cls="fade", d=0.5))
    if repos:
        for index, repo in enumerate(repos[:4]):
            y = 384 + index * 32
            meta = repo.get("language") or "No language"
            meta += f" · {fmt_short_date(repo.get('updated', ''))}"
            if repo.get("stars"):
                meta += f" · ★ {repo['stars']}"
            card.add(card.wrap(card.text(56, y, truncate(repo.get("name", ""), 34), size=14, fill=INK, weight=500), cls="fade", d=0.54 + index * 0.05))
            card.add(card.wrap(card.text(824, y, meta.upper(), size=9, fill=MUTED, font="mono", anchor="end", ls=1.2), cls="fade", d=0.56 + index * 0.05))
            card.add(card.wrap(line(56, y + 12, 824, y + 12, RULE_SOFT), cls="fade", d=0.56 + index * 0.05))
    else:
        card.add(card.wrap(card.text(56, 384, "No public repositories yet.", size=13.5, fill=MUTED), cls="fade", d=0.54))

    months = data.get("months", [])
    month_peak = max((item.get("count", 0) for item in months), default=0)
    card.add(card.wrap(card.text(56, 514, "CONTRIBUTIONS · LAST 12 MONTHS", size=9.5, fill=MUTED, font="mono", ls=1.8), cls="fade", d=0.72))
    chart_h, chart_w, chart_x, chart_base = 40, 768, 56, 578
    card.add(card.wrap(line(chart_x, chart_base, chart_x + chart_w, chart_base, RULE), cls="fade", d=0.74))
    if months:
        step = chart_w / len(months)
        bar_width = min(26.0, step * 0.42)
        for index, month in enumerate(months):
            count = int(month.get("count", 0))
            height = chart_h * count / month_peak if month_peak else 0
            height = max(2.0, height)
            x = chart_x + index * step + (step - bar_width) / 2
            fill = ACCENT if count else RULE_SOFT
            card.add(card.wrap(rect(x, chart_base - height, bar_width, height, fill, rx=3), cls="grow", d=0.76 + index * 0.03))
            card.add(card.wrap(card.text(x + bar_width / 2, chart_base + 16, month.get("label", ""), size=7.4, fill=MUTED, font="mono", anchor="middle", ls=1.1), cls="fade", d=0.78 + index * 0.03))

    return card.render()


def content_version(data):
    stable = {key: value for key, value in data.items() if key != "generated_at"}
    digest = hashlib.sha1(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest[:10]


def build_readme(profile, data):
    links = profile["links"]
    email = links["email"]
    version = content_version(data)
    src = lambda name: f"cards/{name}?v={version}"
    snake = lambda name: f"{name}?v={version}"
    name = esc(profile["display_name"])
    public = data.get("public_repos", 0)
    languages = data.get("stats", {}).get("language_count", 0)
    story_alt = "The point: I build systems that make real impact, with outcomes over demos."
    middle_alt = "The part that matters: I care about the unglamorous middle, where ideas become dependable."
    flow_alt = "The flow: problem, constraints, system, impact."
    public_alt = f"{public} public repositories and {languages} languages"
    return "\n".join(
        [
            f'<p align="center"><img src="{src("hero.svg")}" width="100%" alt="{name}, {esc(profile["role"])}"></p>',
            "",
            f'<p align="center"><a href="mailto:{esc(email)}"><img src="{src("email.svg")}" width="49%" alt="Email {name}"></a> <a href="{esc(links["linkedin"])}"><img src="{src("linkedin.svg")}" width="49%" alt="LinkedIn"></a></p>',
            "",
            f'<p align="center"><img src="{src("story.svg")}" width="100%" alt="{esc(story_alt)}"></p>',
            "",
            f'<p align="center"><img src="{src("middle.svg")}" width="100%" alt="{esc(middle_alt)}"></p>',
            "",
            f'<p align="center"><img src="{src("flow.svg")}" width="100%" alt="{esc(flow_alt)}"></p>',
            "",
            f'<p align="center"><img src="{src("public.svg")}" width="100%" alt="{esc(public_alt)}"></p>',
            "",
            '<p align="center"><sub>THE LAST YEAR · one commit at a time · refreshed every 6 hours</sub></p>',
            "",
            '<p align="center"><picture>'
            f'<source media="(prefers-color-scheme: dark)" srcset="{snake("github-contribution-grid-snake-dark.svg")}">'
            f'<source media="(prefers-color-scheme: light)" srcset="{snake("github-contribution-grid-snake.svg")}">'
            f'<img src="{snake("github-contribution-grid-snake.svg")}" width="100%" alt="Contribution snake">'
            "</picture></p>",
            "",
            f'<p align="center"><sub>{name} · refreshed every 6 hours</sub></p>',
            "",
        ]
    )


def build_preview(profile, data, static):
    links = profile["links"]
    email = links["email"]
    banner = "STATIC FRAME · ANIMATIONS OFF" if static else "LIVE PREVIEW · ANIMATIONS ON"
    public = data.get("public_repos", 0)
    name = esc(profile["display_name"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400&display=swap" rel="stylesheet">
<title>Profile preview</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-font-smoothing: antialiased; }}
  body {{ margin: 0; background: {PAPER}; color: {INK_SOFT}; font-family: Newsreader, Georgia, "Times New Roman", serif; }}
  .page {{ max-width: 1012px; margin: 0 auto; padding: 28px 24px 64px; }}
  .banner {{ display: flex; justify-content: space-between; gap: 16px; padding: 10px 14px; margin-bottom: 18px; border: 1px solid {RULE}; border-radius: 12px; background: rgba(255,255,255,.45); color: {MUTED}; font: 11px "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; }}
  .banner strong {{ color: {ACCENT}; font-weight: 500; }}
  .readme {{ border: 1px solid {RULE}; border-radius: 18px; padding: 26px; background: {WHITE}; }}
  .readme p {{ margin: 0 0 16px; line-height: 1.5; text-align: center; }}
  .readme img {{ display: inline-block; max-width: 100%; height: auto; }}
  .readme a {{ color: {ACCENT}; text-decoration: none; font-family: Geist, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; }}
  .readme a:hover {{ text-decoration: underline; }}
  .readme sub {{ color: {MUTED}; font-family: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; letter-spacing: .06em; }}
</style>
</head>
<body>
<div class="page">
  <div class="banner"><span>{banner}</span><strong>theanugrahh</strong></div>
  <div class="readme">
    <p><img src="cards/hero.svg" width="100%" alt="Hero"></p>
    <p><a href="mailto:{esc(email)}"><img src="cards/email.svg" width="49%" alt="Email"></a> <a href="{esc(links["linkedin"])}"><img src="cards/linkedin.svg" width="49%" alt="LinkedIn"></a></p>
    <p><img src="cards/story.svg" width="100%" alt="The point: building systems that make real impact"></p>
    <p><img src="cards/middle.svg" width="100%" alt="The unglamorous middle"></p>
    <p><img src="cards/flow.svg" width="100%" alt="The flow from problem to impact"></p>
    <p><img src="cards/public.svg" width="100%" alt="{public} public repositories"></p>
    <p><sub>THE LAST YEAR · one commit at a time · refreshed every 6 hours</sub></p>
    <p><img src="github-contribution-grid-snake.svg" width="100%" alt="Contribution snake"></p>
    <p><sub>{name} · refreshed every 6 hours</sub></p>
  </div>
</div>
</body>
</html>
"""


def main():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    static = os.environ.get("STATIC", "").strip().lower() in {"1", "true", "yes"} or "--static" in sys.argv
    ensure_fonts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "hero.svg": render_hero(profile, data, static),
        "email.svg": render_link_card(profile, "email", static),
        "linkedin.svg": render_link_card(profile, "linkedin", static),
        "story.svg": render_story(profile, data, static),
        "middle.svg": render_middle(profile, data, static),
        "flow.svg": render_flow(profile, data, static),
        "public.svg": render_public(profile, data, static),
    }

    for name, markup in outputs.items():
        (OUT_DIR / name).write_text(markup, encoding="utf-8")
        print(f"{name:28} {len(markup.encode('utf-8')) / 1024:6.1f} KB")

    for path in OUT_DIR.glob("*.svg"):
        if path.name not in outputs:
            path.unlink()

    README_PATH.write_text(build_readme(profile, data), encoding="utf-8")
    PREVIEW_PATH.write_text(build_preview(profile, data, static), encoding="utf-8")
    print(f"Wrote {len(outputs)} cards · README.md · preview.html{' · static frame' if static else ''}")


if __name__ == "__main__":
    main()
