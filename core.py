"""
core.py - Shared label extraction / rendering / printing logic used by
both the CLI (label_print.py) and the GUI (gui.py).

Kept dependency-light and importable on any OS: the PyMuPDF/Pillow/numpy
based functions (find_ink_bbox, correct_page, render_page) work
everywhere. The pywin32-based functions (get_printers, get_printer_dpi,
print_image) only work on Windows and import pywin32 lazily so this
module still imports cleanly elsewhere (e.g. for --preview / --save-pdf
only usage, or running the GUI's preview pane on a dev machine).
"""

from __future__ import annotations

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

ROTATE_MAP = {"none": 0, "cw": 90, "ccw": 270, "180": 180}


# --------------------------------------------------------------------------
# Label extraction (pure vector work -- no printer needed, runs anywhere)
# --------------------------------------------------------------------------

def find_ink_bbox(page: fitz.Page, scan_dpi: int = 150, ink_threshold: int = 250) -> fitz.Rect:
    """Render the page at a low DPI just to find the bounding box of
    non-white content, then convert that box back into PDF point
    coordinates. Cheap, and avoids hardcoding carrier-specific layouts."""
    pix = page.get_pixmap(dpi=scan_dpi)
    mode = "RGB" if pix.n < 4 else "RGBA"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("L")
    arr = np.array(img)
    mask = arr < ink_threshold
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return page.rect
    scale = 72 / scan_dpi
    pad = 3  # points of padding so we don't clip anti-aliased edges
    x0 = max(page.rect.x0, xs.min() * scale - pad)
    x1 = min(page.rect.x1, xs.max() * scale + pad)
    y0 = max(page.rect.y0, ys.min() * scale - pad)
    y1 = min(page.rect.y1, ys.max() * scale + pad)
    return fitz.Rect(x0, y0, x1, y1)


def correct_page(page: fitz.Page, rotate: str = "auto", scan_dpi: int = 150, ink_threshold: int = 250) -> int:
    """Crop the page to just the label's ink, and rotate it upright.
    Mutates the page in place (crop box + /Rotate), keeping everything
    vector. Returns the rotation (degrees) that was applied."""
    bbox = find_ink_bbox(page, scan_dpi=scan_dpi, ink_threshold=ink_threshold)
    page.set_cropbox(bbox)

    if rotate == "auto":
        # Most shipping-label PDFs embed a 4x6 label rotated 90 deg into
        # a Letter/A4 page. If the cropped content is wider than it is
        # tall, it needs to be rotated back to portrait.
        degrees = 90 if bbox.width > bbox.height else 0
    else:
        degrees = ROTATE_MAP[rotate]

    page.set_rotation(degrees)
    return degrees


def open_corrected_page(pdf_path: str, page_index: int = 0, rotate: str = "auto") -> tuple[fitz.Document, fitz.Page]:
    """Open a fresh document and apply correct_page to the requested
    page. Returns (doc, page) -- caller should keep doc alive as long as
    page is used, and close it when done."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    correct_page(page, rotate=rotate)
    return doc, page


# --------------------------------------------------------------------------
# Rasterization at an exact target DPI (done once, at the last moment)
# --------------------------------------------------------------------------

def render_page(page: fitz.Page, dpi_x: float, dpi_y: float, bilevel: bool = True, bilevel_threshold: int = 180) -> Image.Image:
    mat = fitz.Matrix(dpi_x / 72, dpi_y / 72)
    pix = page.get_pixmap(matrix=mat)
    mode = "RGB" if pix.n < 4 else "RGBA"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("L")
    if bilevel:
        # Hard threshold instead of dithering: keeps barcode bar edges
        # crisp instead of speckled, which matters for scan reliability.
        img = img.point(lambda p: 255 if p > bilevel_threshold else 0).convert("1")
    return img


# --------------------------------------------------------------------------
# Windows printing (GDI) -- pywin32 imported lazily, Windows only
# --------------------------------------------------------------------------

def get_printers() -> tuple[list[str], str | None]:
    """Return (all printer names, default printer name). Empty list /
    None if pywin32 isn't available (e.g. not on Windows)."""
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    names = [name for _, _, name, _ in win32print.EnumPrinters(flags)]
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = names[0] if names else None
    return names, default


def get_printer_dpi(printer_name: str) -> tuple[int, int]:
    import win32ui

    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    LOGPIXELSX, LOGPIXELSY = 88, 90
    dpi_x = hdc.GetDeviceCaps(LOGPIXELSX)
    dpi_y = hdc.GetDeviceCaps(LOGPIXELSY)
    hdc.DeleteDC()
    return dpi_x, dpi_y


def print_image(img: Image.Image, printer_name: str, copies: int = 1, job_name: str = "Shipping Label") -> None:
    import win32ui
    from PIL import ImageWin

    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    w, h = img.size
    try:
        for _ in range(copies):
            hdc.StartDoc(job_name)
            hdc.StartPage()
            dib = ImageWin.Dib(img)
            # Draw 1:1 -- img was already rendered at this printer's own
            # DPI, so no extra scaling happens here.
            dib.draw(hdc.GetHandleOutput(), (0, 0, w, h))
            hdc.EndPage()
            hdc.EndDoc()
    finally:
        hdc.DeleteDC()
