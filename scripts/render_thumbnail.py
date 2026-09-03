#!/usr/bin/env python3
"""Render exact Korean copy onto a text-free 9:16 Shorts thumbnail."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - environment-specific failure
    raise SystemExit(
        "Pillow is required. Install it with: python3 -m pip install pillow"
    ) from exc


WIDTH = 1080
HEIGHT = 1920
SAFE_LEFT = 70
SAFE_RIGHT = WIDTH - 70
SAFE_TOP = 120
SAFE_BOTTOM = HEIGHT - 160
TEXT_TOP = round(HEIGHT * 0.15)
TEXT_BOTTOM = round(HEIGHT * 0.50)
PREVIEW_SIZE = (270, 480)

MAIN_COLOR = "#FFFFFF"
HIGHLIGHT_COLORS = ("#FFD400", "#FF5A1F")
HOOK_TERMS = (
    "세계 최초",
    "충격",
    "위험",
    "폭발",
    "실제",
    "10배",
    "1초",
    "독",
    "피",
)


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int
    label: str


@dataclass(frozen=True)
class Span:
    text: str
    color: str
    scale: float


@dataclass
class LineLayout:
    spans: list[tuple[Span, ImageFont.FreeTypeFont, float]]
    width: float
    ascent: int
    descent: int

    @property
    def height(self) -> int:
        return self.ascent + self.descent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--text", required=True, help="Exact copy; use real newlines or \\n")
    parser.add_argument("--highlight", action="append", default=[])
    parser.add_argument("--subtext", default="")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--align", choices=("left", "center"), default="center")
    parser.add_argument("--focus-x", type=float, default=0.5)
    parser.add_argument("--focus-y", type=float, default=0.5)
    return parser.parse_args()


def clamp_unit(value: float, name: str) -> float:
    if not 0.0 <= value <= 1.0:
        raise SystemExit(f"{name} must be between 0 and 1")
    return value


def cover_crop(image: Image.Image, focus_x: float, focus_y: float) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = max(WIDTH / image.width, HEIGHT / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    overflow_x = max(0, resized.width - WIDTH)
    overflow_y = max(0, resized.height - HEIGHT)
    left = round(overflow_x * focus_x)
    top = round(overflow_y * focus_y)
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def candidate_font_paths(explicit: Path | None) -> Iterable[Path]:
    if explicit:
        yield explicit.expanduser()
        return

    preferred = (
        "/Library/Fonts/Pretendard-Black.otf",
        "/Library/Fonts/Pretendard-ExtraBold.otf",
        "/Library/Fonts/GmarketSansBold.otf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Black.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    )
    seen: set[Path] = set()
    for value in preferred:
        path = Path(value)
        if path.is_file() and path not in seen:
            seen.add(path)
            yield path

    roots = (
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/usr/share/fonts"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    )
    name_hints = ("pretendard", "gmarket", "notosans", "apple", "nanum", "malgun")
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            if not any(hint in path.name.lower() for hint in name_hints):
                continue
            if path not in seen:
                seen.add(path)
                yield path


def face_score(path: Path, family: str, style: str) -> int:
    value = f"{path.name} {family} {style}".lower().replace(" ", "")
    score = 0
    for hint, points in (
        ("pretendard", 100),
        ("gmarket", 95),
        ("notosanskr", 90),
        ("notosanscjk", 88),
        ("applesdgothic", 82),
        ("malgun", 78),
        ("nanum", 72),
    ):
        if hint in value:
            score += points
            break
    for weight, points in (
        ("black", 35),
        ("heavy", 32),
        ("extrabold", 28),
        ("bold", 22),
        ("semibold", 10),
    ):
        if weight in value:
            score += points
            break
    if "thin" in value or "light" in value:
        score -= 40
    return score


def choose_font(explicit: Path | None) -> FontFace:
    best: tuple[int, FontFace] | None = None
    for path in candidate_font_paths(explicit):
        if not path.is_file():
            continue
        indices = range(20) if path.suffix.lower() == ".ttc" else range(1)
        for index in indices:
            try:
                font = ImageFont.truetype(str(path), 64, index=index)
            except OSError:
                if index == 0:
                    break
                continue
            family, style = font.getname()
            score = face_score(path, family, style)
            face = FontFace(path=path, index=index, label=f"{family} {style}".strip())
            if best is None or score > best[0]:
                best = (score, face)
    if best is None:
        raise SystemExit(
            "No bold Korean font found. Pass --font with a Korean TTF, OTF, or TTC file."
        )
    return best[1]


def font(face: FontFace, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(face.path), size, index=face.index)


def balanced_wrap(text: str) -> list[str]:
    raw = text.replace("\\n", "\n").strip()
    explicit = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(explicit) > 1:
        if len(explicit) > 4:
            raise SystemExit("Main thumbnail copy must use 2 to 4 lines; use --subtext separately.")
        return explicit

    words = raw.split()
    if not words:
        raise SystemExit("Thumbnail text cannot be empty")
    if len(words) == 1:
        target_lines = min(4, max(2, round(len(raw) / 7)))
        width = max(1, (len(raw) + target_lines - 1) // target_lines)
        return [raw[i : i + width] for i in range(0, len(raw), width)][:4]

    target_lines = 2 if len(raw) <= 16 else 3 if len(raw) <= 28 else 4
    lines: list[str] = []
    remaining = words[:]
    for slot in range(target_lines, 0, -1):
        remaining_chars = sum(len(word) for word in remaining) + max(0, len(remaining) - 1)
        target = max(1, round(remaining_chars / slot))
        line: list[str] = []
        while remaining:
            proposal = " ".join(line + [remaining[0]])
            if line and len(proposal) > target and len(remaining) >= slot:
                break
            line.append(remaining.pop(0))
        lines.append(" ".join(line))
    if remaining:
        lines[-1] = " ".join([lines[-1], *remaining])
    return [line for line in lines if line]


def choose_highlights(text: str, requested: list[str]) -> list[str]:
    selected: list[str] = []
    for value in requested:
        value = value.strip()
        if value and value in text and value not in selected:
            selected.append(value)
    if not selected:
        number_pattern = re.compile(
            r"\d+(?:[.,]\d+)?(?:\s?(?:℃|도씨|[Hh][Zz]|배|초|%))?"
        )
        selected.extend(match.group(0) for match in number_pattern.finditer(text))
        selected.extend(term for term in HOOK_TERMS if term in text)
    unique: list[str] = []
    for value in selected:
        if value not in unique:
            unique.append(value)
    return unique[:2]


def split_spans(line: str, highlights: list[str]) -> list[Span]:
    if not highlights:
        return [Span(line, MAIN_COLOR, 1.0)]
    pattern = re.compile("(" + "|".join(re.escape(x) for x in sorted(highlights, key=len, reverse=True)) + ")")
    result: list[Span] = []
    for part in pattern.split(line):
        if not part:
            continue
        if part in highlights:
            color = HIGHLIGHT_COLORS[highlights.index(part) % len(HIGHLIGHT_COLORS)]
            scale = 1.25 if re.search(r"\d", part) else 1.10
            result.append(Span(part, color, scale))
        else:
            result.append(Span(part, MAIN_COLOR, 1.0))
    return result


def line_layout(
    draw: ImageDraw.ImageDraw,
    face: FontFace,
    line: str,
    highlights: list[str],
    base_size: int,
) -> LineLayout:
    spans: list[tuple[Span, ImageFont.FreeTypeFont, float]] = []
    width = 0.0
    ascent = 0
    descent = 0
    for span in split_spans(line, highlights):
        span_font = font(face, max(12, round(base_size * span.scale)))
        span_width = draw.textlength(span.text, font=span_font)
        span_ascent, span_descent = span_font.getmetrics()
        spans.append((span, span_font, span_width))
        width += span_width
        ascent = max(ascent, span_ascent)
        descent = max(descent, span_descent)
    return LineLayout(spans=spans, width=width, ascent=ascent, descent=descent)


def fit_layout(
    draw: ImageDraw.ImageDraw,
    face: FontFace,
    lines: list[str],
    highlights: list[str],
) -> tuple[int, list[LineLayout], int, int, int]:
    for base_size in range(170, 53, -2):
        layouts = [line_layout(draw, face, line, highlights, base_size) for line in lines]
        stroke = max(5, round(base_size * 0.065))
        shadow = max(6, round(base_size * 0.055))
        gap = max(10, round(base_size * 0.18))
        total_height = sum(layout.height for layout in layouts) + gap * (len(layouts) - 1)
        edge_pad = stroke + shadow + 4
        max_width = max(layout.width for layout in layouts)
        if (
            max_width <= (SAFE_RIGHT - SAFE_LEFT) - 2 * edge_pad
            and total_height <= (TEXT_BOTTOM - TEXT_TOP) - 2 * edge_pad
        ):
            return base_size, layouts, stroke, shadow, gap
    raise SystemExit("Text does not fit the safe area. Shorten the selected thumbnail copy.")


def draw_main_text(
    image: Image.Image,
    face: FontFace,
    lines: list[str],
    highlights: list[str],
    align: str,
) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(image)
    _, layouts, stroke, shadow, gap = fit_layout(draw, face, lines, highlights)
    total_height = sum(layout.height for layout in layouts) + gap * (len(layouts) - 1)
    y = TEXT_TOP + ((TEXT_BOTTOM - TEXT_TOP) - total_height) / 2
    bounds = [WIDTH, HEIGHT, 0, 0]

    for layout in layouts:
        edge_pad = stroke + shadow + 4
        if align == "left":
            x = SAFE_LEFT + edge_pad
        else:
            x = (WIDTH - layout.width) / 2
        baseline = y + layout.ascent
        line_left = x - stroke
        line_top = y - stroke
        for span, span_font, span_width in layout.spans:
            draw.text(
                (x + shadow, baseline + shadow),
                span.text,
                font=span_font,
                fill="#000000",
                stroke_width=stroke + 2,
                stroke_fill="#000000",
                anchor="ls",
            )
            draw.text(
                (x, baseline),
                span.text,
                font=span_font,
                fill=span.color,
                stroke_width=stroke,
                stroke_fill="#050505",
                anchor="ls",
            )
            x += span_width
        line_right = x + stroke + shadow
        line_bottom = y + layout.height + stroke + shadow
        bounds[0] = min(bounds[0], round(line_left))
        bounds[1] = min(bounds[1], round(line_top))
        bounds[2] = max(bounds[2], round(line_right))
        bounds[3] = max(bounds[3], round(line_bottom))
        y += layout.height + gap

    bbox = tuple(bounds)
    if not (
        bbox[0] >= SAFE_LEFT
        and bbox[1] >= SAFE_TOP
        and bbox[2] <= SAFE_RIGHT
        and bbox[3] <= SAFE_BOTTOM
    ):
        raise SystemExit(f"Rendered text escaped the safe area: {bbox}")
    return bbox


def draw_subtext(
    image: Image.Image, face: FontFace, value: str, align: str
) -> tuple[int, int, int, int] | None:
    value = value.replace("\\n", " ").strip()
    if not value:
        return None
    draw = ImageDraw.Draw(image)
    size = 58
    available = SAFE_RIGHT - SAFE_LEFT
    while size >= 30:
        sub_font = font(face, size)
        width = draw.textlength(value, font=sub_font)
        if width <= available - 24:
            break
        size -= 2
    else:
        raise SystemExit("Subtext does not fit the safe area")
    ascent, descent = sub_font.getmetrics()
    stroke = max(3, round(size * 0.07))
    x = SAFE_LEFT + stroke if align == "left" else (WIDTH - width) / 2
    shadow = 5
    baseline = SAFE_BOTTOM - descent - stroke - shadow
    draw.text(
        (x + shadow, baseline + shadow),
        value,
        font=sub_font,
        fill="#000000",
        stroke_width=stroke + 1,
        stroke_fill="#000000",
        anchor="ls",
    )
    draw.text(
        (x, baseline),
        value,
        font=sub_font,
        fill="#FFFFFF",
        stroke_width=stroke,
        stroke_fill="#050505",
        anchor="ls",
    )
    bbox = (
        round(x - stroke),
        round(baseline - ascent - stroke),
        round(x + width + stroke + shadow),
        round(baseline + descent + stroke + shadow),
    )
    if not (
        bbox[0] >= SAFE_LEFT
        and bbox[1] >= SAFE_TOP
        and bbox[2] <= SAFE_RIGHT
        and bbox[3] <= SAFE_BOTTOM
    ):
        raise SystemExit(f"Rendered subtext escaped the safe area: {bbox}")
    return bbox


def srgb_profile() -> bytes | None:
    try:
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def save_png(image: Image.Image, path: Path) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, object] = {"format": "PNG", "optimize": True}
    profile = srgb_profile()
    if profile:
        options["icc_profile"] = profile
    image.save(path, **options)


def main() -> None:
    args = parse_args()
    focus_x = clamp_unit(args.focus_x, "--focus-x")
    focus_y = clamp_unit(args.focus_y, "--focus-y")
    background = args.background.expanduser().resolve()
    if not background.is_file():
        raise SystemExit(f"Background image not found: {background}")

    lines = balanced_wrap(args.text)
    highlights = choose_highlights("\n".join(lines), args.highlight)
    face = choose_font(args.font)

    with Image.open(background) as source:
        thumbnail = cover_crop(source, focus_x, focus_y)
    bbox = draw_main_text(thumbnail, face, lines, highlights, args.align)
    subtext_bbox = draw_subtext(thumbnail, face, args.subtext, args.align)
    if thumbnail.size != (WIDTH, HEIGHT) or thumbnail.mode != "RGB":
        raise SystemExit("Internal output validation failed")

    save_png(thumbnail, args.output)
    preview_path = ""
    if args.preview:
        preview = thumbnail.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        save_png(preview, args.preview)
        preview_path = str(args.preview.expanduser().resolve())

    print(f"output={args.output.expanduser().resolve()}")
    print(f"size={WIDTH}x{HEIGHT}")
    print("mode=RGB")
    print("profile=sRGB")
    print(f"font={face.label} | {face.path} | index={face.index}")
    print(f"lines={len(lines)}")
    print(f"highlights={','.join(highlights)}")
    print(f"text_bbox={bbox}")
    if subtext_bbox:
        print(f"subtext_bbox={subtext_bbox}")
    print("safe_area=true")
    if preview_path:
        print(f"preview={preview_path} | size={PREVIEW_SIZE[0]}x{PREVIEW_SIZE[1]}")


if __name__ == "__main__":
    main()
