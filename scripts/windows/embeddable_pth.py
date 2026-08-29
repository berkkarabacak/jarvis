"""Rewrite embeddable CPython python*._pth so sibling backend is importable.

Windows embeddable Python ships a ._pth that turns on isolated mode.
PYTHONPATH and cwd are then ignored, so ``python -m app.first_run_env``
fails with ``No module named 'app'`` even when ``resources/backend/app``
exists next to ``resources/python``.

Paths in ._pth are relative to the directory that contains the ._pth file
(the bundled python folder). ``../backend`` is that sibling tree.
``import site`` must stay enabled so pip/site-packages still work.
"""

from __future__ import annotations

import argparse
from pathlib import Path

BACKEND_PTH_LINE = "../backend"


def rewrite_embeddable_pth(text: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    out: list[str] = []
    saw_backend = False
    saw_site = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped in {BACKEND_PTH_LINE, f"# {BACKEND_PTH_LINE}", f"#{BACKEND_PTH_LINE}"}:
            if not saw_backend:
                out.append(BACKEND_PTH_LINE)
                saw_backend = True
            continue
        if stripped in {"import site", "#import site", "# import site"}:
            if not saw_site:
                out.append("import site")
                saw_site = True
            continue
        out.append(raw.rstrip("\r"))
    if not saw_backend:
        if saw_site:
            out.insert(out.index("import site"), BACKEND_PTH_LINE)
        else:
            out.append(BACKEND_PTH_LINE)
    if not saw_site:
        out.append("import site")
    body = newline.join(out)
    if not body.endswith(newline):
        body += newline
    return body


def apply_embeddable_pth(path: Path) -> Path:
    path = Path(path)
    # Bytes so Windows CRLF in python*._pth is not normalized away.
    text = path.read_bytes().decode("utf-8")
    path.write_bytes(rewrite_embeddable_pth(text).encode("utf-8"))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add ../backend to embeddable python*._pth")
    parser.add_argument("pth", help="Path to pythonXY._pth")
    args = parser.parse_args(argv)
    apply_embeddable_pth(Path(args.pth))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
