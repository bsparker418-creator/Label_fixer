#!/usr/bin/env python3
"""
label_print.py - Extract a 4x6 shipping label from a full-page PDF and
print it to a Windows label printer (e.g. Rongta RP245) at the printer's
own native resolution, with no snip/screenshot/Paint steps in between.

Also see gui.py for a point-and-click version of the same tool.

Why this fixes the "fuzzy barcode" problem:
  Snip -> Paint -> rotate -> print puts the label through several lossy
  raster steps at low (screen) resolution before it ever reaches the
  printer. This script stays in vector space (PyMuPDF) until the very
  last moment, then rasterizes exactly once, directly at the printer's
  native DPI (queried live from the Windows driver), so there is no
  extra scaling/resampling for the driver to do.

Usage examples:
    # See what printers Windows knows about
    uv run python label_print.py --list-printers

    # Preview the auto-cropped/rotated label as a PNG (no printing,
    # works on any OS -- good for sanity-checking before you print)
    uv run python label_print.py label.pdf --preview out.png --no-print

    # Print to the default printer
    uv run python label_print.py label.pdf

    # Print to a specific printer, 2 copies
    uv run python label_print.py label.pdf --printer "Rongta RP245" --copies 2

    # Save a corrected, vector, exactly-4x6 PDF as a fallback you can
    # print from any PDF viewer at "Actual Size / 100%"
    uv run python label_print.py label.pdf --save-pdf corrected.pdf --no-print

Requirements (see pyproject.toml):
    uv sync                      # installs pymupdf, pillow, numpy (+ pywin32 on Windows)
    uv run python label_print.py ...
"""

import argparse
import sys

import fitz  # PyMuPDF

import core


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?", help="Path to the shipping label PDF")
    ap.add_argument("--page", type=int, default=0, help="Page index to print (default 0)")
    ap.add_argument("--all-pages", action="store_true", help="Process every page in the PDF")
    ap.add_argument("--printer", default=None, help="Windows printer name (default: system default printer)")
    ap.add_argument("--copies", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=None, help="Override render DPI (default: query the printer's native DPI)")
    ap.add_argument("--rotate", choices=["auto", "cw", "ccw", "none", "180"], default="auto")
    ap.add_argument("--grayscale", action="store_true", help="Skip black/white thresholding, keep antialiased grayscale")
    ap.add_argument("--threshold", type=int, default=180, help="Bilevel threshold 0-255 (default 180)")
    ap.add_argument("--save-pdf", metavar="PATH", help="Save the corrected (cropped+rotated) vector PDF here")
    ap.add_argument("--preview", metavar="PATH", help="Save a rendered PNG preview here (use with --no-print)")
    ap.add_argument("--no-print", action="store_true", help="Don't send anything to the printer")
    ap.add_argument("--list-printers", action="store_true", help="List Windows printers and exit")
    args = ap.parse_args()

    if args.list_printers:
        names, default = core.get_printers()
        print(f"Default printer: {default}\n")
        print("Available printers:")
        for name in names:
            marker = " (default)" if name == default else ""
            print(f"  - {name}{marker}")
        return

    if not args.pdf:
        ap.error("pdf is required unless --list-printers is given")

    doc = fitz.open(args.pdf)
    pages = range(len(doc)) if args.all_pages else [args.page]

    # Correct (crop + rotate) the requested pages first, vector-only.
    for i in pages:
        core.correct_page(doc[i], rotate=args.rotate)

    if args.save_pdf:
        out = fitz.open()
        for i in pages:
            out.insert_pdf(doc, from_page=i, to_page=i)
        out.save(args.save_pdf)
        print(f"Saved corrected PDF: {args.save_pdf}")

    need_render = args.preview or not args.no_print
    if not need_render:
        return

    # Figure out target DPI.
    dpi_x = dpi_y = args.dpi
    printer_name = args.printer
    if not args.no_print:
        _, default_printer = core.get_printers()
        printer_name = printer_name or default_printer
        if not printer_name:
            ap.error("no printer found -- pass --printer or use --no-print")
        if dpi_x is None:
            dpi_x, dpi_y = core.get_printer_dpi(printer_name)
            print(f"Printer '{printer_name}' native resolution: {dpi_x} x {dpi_y} DPI")
    elif dpi_x is None:
        dpi_x = dpi_y = 300  # sane default for preview-only mode

    for i in pages:
        img = core.render_page(doc[i], dpi_x, dpi_y, bilevel=not args.grayscale, bilevel_threshold=args.threshold)

        if args.preview:
            path = args.preview if len(pages) == 1 else args.preview.replace(".png", f"_{i}.png")
            img.convert("L").save(path)
            print(f"Saved preview: {path} ({img.size[0]}x{img.size[1]} px)")

        if not args.no_print:
            core.print_image(img, printer_name, copies=args.copies)
            print(f"Sent page {i} to '{printer_name}' ({args.copies} copy/copies)")


if __name__ == "__main__":
    sys.exit(main())
