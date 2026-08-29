#!/usr/bin/env python3
"""Generate the small Windows-like XFCE theme pack (wallpaper, icons, xfwm pixmaps).

Run from this directory: python3 generate.py
Checked-in output is what the image copies. No Pillow required.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Classic Windows 95 palette.
NAVY = (0x00, 0x00, 0x80, 0xFF)
NAVY_DK = (0x00, 0x00, 0x40, 0xFF)
TEAL = (0x00, 0x80, 0x80, 0xFF)
TEAL_LT = (0x00, 0x96, 0x96, 0xFF)
TEAL_DK = (0x00, 0x6A, 0x6A, 0xFF)
SILVER = (0xC0, 0xC0, 0xC0, 0xFF)
WHITE = (0xFF, 0xFF, 0xFF, 0xFF)
BLACK = (0x00, 0x00, 0x00, 0xFF)
GRAY = (0x80, 0x80, 0x80, 0xFF)
DKGRAY = (0x40, 0x40, 0x40, 0xFF)
YELLOW = (0xFF, 0xC8, 0x40, 0xFF)
YELLOW_DK = (0xC0, 0x90, 0x20, 0xFF)
RED = (0xC0, 0x20, 0x20, 0xFF)
GREEN = (0x20, 0xA0, 0x40, 0xFF)
BLUE = (0x20, 0x40, 0xC0, 0xFF)
TR = (0x00, 0x00, 0x00, 0x00)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def new_canvas(w: int, h: int, color=TR) -> list[list[tuple[int, int, int, int]]]:
    return [[color for _ in range(w)] for _ in range(h)]


def set_px(canvas, x: int, y: int, color) -> None:
    if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
        canvas[y][x] = color


def fill_rect(canvas, x0: int, y0: int, x1: int, y1: int, color) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            set_px(canvas, x, y, color)


def rect_outline(canvas, x0: int, y0: int, x1: int, y1: int, color) -> None:
    for x in range(x0, x1):
        set_px(canvas, x, y0, color)
        set_px(canvas, x, y1 - 1, color)
    for y in range(y0, y1):
        set_px(canvas, x0, y, color)
        set_px(canvas, x1 - 1, y, color)


def raised_box(canvas, x0: int, y0: int, x1: int, y1: int, face=SILVER) -> None:
    fill_rect(canvas, x0, y0, x1, y1, face)
    for x in range(x0, x1 - 1):
        set_px(canvas, x, y0, WHITE)
        set_px(canvas, x, y1 - 1, DKGRAY)
    for y in range(y0, y1 - 1):
        set_px(canvas, x0, y, WHITE)
        set_px(canvas, x1 - 1, y, DKGRAY)
    for x in range(x0 + 1, x1 - 1):
        set_px(canvas, x, y1 - 2, GRAY)
    for y in range(y0 + 1, y1 - 1):
        set_px(canvas, x1 - 2, y, GRAY)


def flatten(canvas) -> bytes:
    out = bytearray()
    for row in canvas:
        for r, g, b, a in row:
            out.extend((r, g, b, a))
    return bytes(out)


def save_canvas(path: Path, canvas) -> None:
    write_png(path, len(canvas[0]), len(canvas), flatten(canvas))


def hex_rgb(color) -> str:
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"


def write_xpm(path: Path, symbol: str, canvas, none_char: str | None = " ") -> None:
    h = len(canvas)
    w = len(canvas[0])
    palette: dict[tuple[int, int, int, int], str] = {}
    chars = ".*+#=@%$&ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
    next_i = 0
    rows: list[str] = []
    for y in range(h):
        line = []
        for x in range(w):
            c = canvas[y][x]
            if c not in palette:
                if none_char is not None and c[3] == 0:
                    palette[c] = none_char
                else:
                    ch = chars[next_i]
                    next_i += 1
                    if none_char is not None and ch == none_char:
                        ch = chars[next_i]
                        next_i += 1
                    palette[c] = ch
            line.append(palette[c])
        rows.append("".join(line))
    ncolors = len(palette)
    lines = [
        "/* XPM */",
        f"static char * {symbol}[] = {{",
        f'"{w} {h} {ncolors} 1",',
    ]
    for color, ch in palette.items():
        if color[3] == 0:
            lines.append(f'"{ch} c None",')
        else:
            lines.append(f'"{ch} c {hex_rgb(color)}",')
    for i, row in enumerate(rows):
        comma = "," if i < len(rows) - 1 else ""
        lines.append(f'"{row}"{comma}')
    lines.append("};")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_wallpaper() -> None:
    w, h = 1280, 720
    canvas = new_canvas(w, h, TEAL)
    # Subtle classic dither so it is not a flat void.
    for y in range(h):
        for x in range(w):
            if (x + y * 3) % 17 == 0:
                canvas[y][x] = TEAL_LT
            elif (x * 2 + y) % 23 == 0:
                canvas[y][x] = TEAL_DK
    save_canvas(ROOT / "wallpaper.png", canvas)


def make_start_icon(size: int):
    c = new_canvas(size, size, TR)
    m = max(1, size // 16)
    pad = max(1, size // 8)
    mid = size // 2
    # Four panes — original start-button mark, not a vendor logo.
    raised_box(c, pad, pad, mid - m, mid - m, RED)
    raised_box(c, mid + m, pad, size - pad, mid - m, GREEN)
    raised_box(c, pad, mid + m, mid - m, size - pad, BLUE)
    raised_box(c, mid + m, mid + m, size - pad, size - pad, YELLOW)
    return c


def make_folder_icon(size: int):
    c = new_canvas(size, size, TR)
    tab_h = max(3, size // 5)
    body_top = tab_h
    fill_rect(c, size // 8, 2, size // 2, tab_h + 1, YELLOW_DK)
    raised_box(c, 2, body_top, size - 2, size - 2, YELLOW)
    return c


def make_home_icon(size: int):
    c = make_folder_icon(size)
    # Door
    dw = max(3, size // 5)
    dh = max(5, size // 3)
    x0 = (size - dw) // 2
    y0 = size - 3 - dh
    fill_rect(c, x0, y0, x0 + dw, size - 3, YELLOW_DK)
    return c


def make_computer_icon(size: int):
    c = new_canvas(size, size, TR)
    m = max(2, size // 10)
    raised_box(c, m, m, size - m, size - 3 * m, SILVER)
    fill_rect(c, m + 2, m + 2, size - m - 2, size - 3 * m - 2, NAVY)
    fill_rect(c, size // 3, size - 3 * m, 2 * size // 3, size - m, GRAY)
    fill_rect(c, size // 5, size - m - 1, 4 * size // 5, size - 2, SILVER)
    return c


def make_file_icon(size: int):
    c = new_canvas(size, size, TR)
    m = max(2, size // 8)
    raised_box(c, m, 2, size - m, size - 2, WHITE)
    fold = max(4, size // 4)
    fill_rect(c, size - m - fold, 2, size - m, 2 + fold, SILVER)
    for i in range(3):
        y = m + 4 + i * max(3, size // 8)
        fill_rect(c, m + 2, y, size - m - 2, y + 1, GRAY)
    return c


def make_exec_icon(size: int):
    c = new_canvas(size, size, TR)
    raised_box(c, 2, 2, size - 2, size - 2, SILVER)
    fill_rect(c, 4, 4, size - 4, size // 3, NAVY)
    fill_rect(c, 5, size // 2, size // 2, size - 5, WHITE)
    return c


def make_trash_icon(size: int):
    c = new_canvas(size, size, TR)
    fill_rect(c, size // 3, 2, 2 * size // 3, 5, GRAY)
    raised_box(c, 4, 5, size - 4, size - 2, SILVER)
    for i in range(3):
        x = 6 + i * max(3, size // 5)
        fill_rect(c, x, 8, x + 1, size - 4, GRAY)
    return c


def make_drive_icon(size: int):
    c = new_canvas(size, size, TR)
    raised_box(c, 2, size // 3, size - 2, 2 * size // 3 + 2, SILVER)
    fill_rect(c, 4, size // 3 + 2, size - 4, size // 3 + 6, DKGRAY)
    set_px(c, size - 8, size // 2 + 2, GREEN)
    return c


def write_icon_set(name: str, maker, contexts: list[tuple[str, str]]) -> None:
    for size in (16, 32, 48):
        canvas = maker(size)
        for context, dest in contexts:
            save_canvas(ROOT / "icons" / f"{size}x{size}" / context / f"{dest}.png", canvas)


def make_icons() -> None:
    write_icon_set(
        "start",
        make_start_icon,
        [("apps", "start-here"), ("apps", "distributor-logo"), ("places", "start-here")],
    )
    write_icon_set(
        "folder",
        make_folder_icon,
        [
            ("places", "folder"),
            ("places", "folder-open"),
            ("places", "inode-directory"),
            ("places", "user-desktop"),
        ],
    )
    write_icon_set("home", make_home_icon, [("places", "user-home")])
    write_icon_set(
        "computer",
        make_computer_icon,
        [("places", "computer"), ("devices", "computer"), ("devices", "video-display")],
    )
    write_icon_set(
        "file",
        make_file_icon,
        [("mimetypes", "text-x-generic"), ("mimetypes", "application-x-generic")],
    )
    write_icon_set("exec", make_exec_icon, [("mimetypes", "application-x-executable")])
    write_icon_set(
        "trash",
        make_trash_icon,
        [("places", "user-trash"), ("places", "user-trash-full")],
    )
    write_icon_set(
        "drive",
        make_drive_icon,
        [("devices", "drive-harddisk"), ("places", "drive-harddisk")],
    )


def title_bar(width: int, height: int, active: bool):
    face = NAVY if active else GRAY
    edge = NAVY_DK if active else DKGRAY
    c = new_canvas(width, height, face)
    for x in range(width):
        set_px(c, x, 0, WHITE if active else SILVER)
        set_px(c, x, height - 1, edge)
    return c


def side_border(width: int, height: int, active: bool, side: str):
    c = new_canvas(width, height, SILVER)
    if side == "left":
        for y in range(height):
            set_px(c, 0, y, WHITE)
            set_px(c, 1, y, SILVER)
            set_px(c, width - 1, y, NAVY if active else GRAY)
    elif side == "right":
        for y in range(height):
            set_px(c, 0, y, NAVY if active else GRAY)
            set_px(c, width - 1, y, DKGRAY)
            set_px(c, width - 2, y, GRAY)
    return c


def bottom_border(width: int, height: int, active: bool):
    c = new_canvas(width, height, SILVER)
    for x in range(width):
        set_px(c, x, 0, NAVY if active else GRAY)
        set_px(c, x, height - 1, DKGRAY)
        if height > 2:
            set_px(c, x, height - 2, GRAY)
    return c


def corner(kind: str, active: bool):
    # 4x18-ish pieces for frame corners.
    if kind.startswith("top"):
        w, h = 6, 20
        c = title_bar(w, h, active)
        if kind == "top-left":
            for y in range(h):
                set_px(c, 0, y, WHITE)
        else:
            for y in range(h):
                set_px(c, w - 1, y, DKGRAY)
        return c
    w, h = 6, 6
    c = new_canvas(w, h, SILVER)
    if "left" in kind:
        for y in range(h):
            set_px(c, 0, y, WHITE)
    if "right" in kind:
        for y in range(h):
            set_px(c, w - 1, y, DKGRAY)
    for x in range(w):
        set_px(c, x, h - 1, DKGRAY)
    if active:
        set_px(c, 1, 0, NAVY)
    return c


def wm_button(kind: str, state: str):
    w, h = 16, 14
    face = SILVER
    c = new_canvas(w, h, face)
    if state == "pressed":
        fill_rect(c, 0, 0, w, h, SILVER)
        rect_outline(c, 0, 0, w, h, DKGRAY)
        ox, oy = 1, 1
    else:
        raised_box(c, 0, 0, w, h, SILVER)
        ox, oy = 0, 0
    ink = GRAY if state == "inactive" else BLACK
    if kind == "close":
        for i in range(5):
            set_px(c, 5 + i + ox, 4 + i + oy, ink)
            set_px(c, 9 - i + ox, 4 + i + oy, ink)
            set_px(c, 5 + i + ox, 5 + i + oy, ink)
            set_px(c, 9 - i + ox, 5 + i + oy, ink)
    elif kind == "hide":
        fill_rect(c, 4 + ox, 10 + oy, 12 + ox, 12 + oy, ink)
    elif kind == "maximize":
        rect_outline(c, 4 + ox, 3 + oy, 12 + ox, 11 + oy, ink)
        fill_rect(c, 4 + ox, 3 + oy, 12 + ox, 5 + oy, ink)
    elif kind == "maximize-toggled":
        rect_outline(c, 6 + ox, 3 + oy, 13 + ox, 9 + oy, ink)
        rect_outline(c, 3 + ox, 6 + oy, 10 + ox, 12 + oy, ink)
    elif kind == "menu":
        for i in range(3):
            y = 4 + i * 3 + oy
            fill_rect(c, 4 + ox, y, 12 + ox, y + 1, ink)
    return c


def make_xfwm() -> None:
    dest = ROOT / "xfwm4"
    dest.mkdir(parents=True, exist_ok=True)
    for active, suffix in ((True, "active"), (False, "inactive")):
        write_xpm(dest / f"title-1-{suffix}.xpm", f"title_1_{suffix}", title_bar(8, 20, active))
        write_xpm(dest / f"title-2-{suffix}.xpm", f"title_2_{suffix}", title_bar(8, 20, active))
        write_xpm(dest / f"title-3-{suffix}.xpm", f"title_3_{suffix}", title_bar(16, 20, active))
        write_xpm(dest / f"title-4-{suffix}.xpm", f"title_4_{suffix}", title_bar(8, 20, active))
        write_xpm(dest / f"title-5-{suffix}.xpm", f"title_5_{suffix}", title_bar(8, 20, active))
        write_xpm(dest / f"left-{suffix}.xpm", f"left_{suffix}", side_border(4, 16, active, "left"))
        write_xpm(dest / f"right-{suffix}.xpm", f"right_{suffix}", side_border(4, 16, active, "right"))
        write_xpm(dest / f"bottom-{suffix}.xpm", f"bottom_{suffix}", bottom_border(16, 4, active))
        write_xpm(dest / f"top-left-{suffix}.xpm", f"top_left_{suffix}", corner("top-left", active))
        write_xpm(dest / f"top-right-{suffix}.xpm", f"top_right_{suffix}", corner("top-right", active))
        write_xpm(dest / f"bottom-left-{suffix}.xpm", f"bottom_left_{suffix}", corner("bottom-left", active))
        write_xpm(dest / f"bottom-right-{suffix}.xpm", f"bottom_right_{suffix}", corner("bottom-right", active))

    buttons = {
        "close": "close",
        "hide": "hide",
        "maximize": "maximize",
        "maximize-toggled": "maximize_toggled",
        "menu": "menu",
    }
    for kind, symbol in buttons.items():
        for state in ("active", "inactive", "prelight", "pressed"):
            fname = f"{kind}-{state}.xpm"
            write_xpm(dest / fname, f"{symbol}_{state}", wm_button(kind, state))


def main() -> None:
    make_wallpaper()
    make_icons()
    make_xfwm()
    print("generated Windows-like theme assets under", ROOT)


if __name__ == "__main__":
    main()
