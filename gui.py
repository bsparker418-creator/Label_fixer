#!/usr/bin/env python3
"""
gui.py - Point-and-click front end for label_print / core.

Workflow: pick a shipping-label PDF -> the app auto-crops/rotates it and
shows a preview of exactly what will be sent to the printer -> pick a
printer (and copy count) -> Print.

Run with:
    uv run python gui.py
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import ImageTk

import core

PREVIEW_DPI = 150
PREVIEW_MAX_SIZE = (380, 480)  # px, keeps the window a sane size

# Works both run from source (uv run python gui.py) and when frozen into
# a standalone exe with PyInstaller (--add-data "icon.ico;.").
ICON_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "icon.ico"

# -- Palette --------------------------------------------------------------
# Warm, minimal palette (cream page, terracotta accent, near-black text)
BG = "#FAF9F5"
CARD_BG = "#FFFFFF"
PREVIEW_BG = "#F5F4EF"
BORDER = "#E5E4DF"
TEXT = "#141413"
TEXT_MUTED = "#83827C"
ACCENT = "#D97757"
ACCENT_HOVER = "#C2653F"
ACCENT_PRESSED = "#AC5735"


class LabelPrintApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Label Fixer")
        self.configure(bg=BG)
        self.resizable(False, False)
        if ICON_PATH.exists():
            try:
                self.iconbitmap(str(ICON_PATH))
            except tk.TclError:
                pass  # .ico icons aren't supported on non-Windows Tk builds

        self.pdf_path: str | None = None
        self.page_count = 1
        self.preview_photo: ImageTk.PhotoImage | None = None  # keep a reference alive

        self._build_fonts()
        self._build_style()
        self._build_widgets()
        self._refresh_printers()
        self._center()

    # -- Look and feel -------------------------------------------------------

    def _build_fonts(self) -> None:
        self.f_title = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        self.f_subtitle = tkfont.Font(family="Segoe UI", size=10)
        self.f_section = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_button = tkfont.Font(family="Segoe UI", size=10, weight="bold")

    def _build_style(self) -> None:
        style = ttk.Style(self)
        # 'clam' is the only built-in theme that reliably honors custom
        # colors on every platform (native themes mostly ignore them).
        style.theme_use("clam")

        style.configure(
            "Accent.TButton", background=ACCENT, foreground="white",
            font=self.f_button, padding=(18, 10), borderwidth=0, relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#E7C7B7"), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
            foreground=[("disabled", "#FFFFFF")],
        )

        style.configure(
            "Secondary.TButton", background=CARD_BG, foreground=TEXT,
            font=self.f_body, padding=(14, 8), borderwidth=1, relief="solid",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", PREVIEW_BG)],
            bordercolor=[("!disabled", BORDER)],
        )

        for name in ("TCombobox", "TSpinbox"):
            style.configure(
                name, fieldbackground=CARD_BG, background=CARD_BG, foreground=TEXT,
                arrowcolor=TEXT_MUTED, bordercolor=BORDER, lightcolor=CARD_BG,
                darkcolor=CARD_BG, padding=6, relief="flat",
            )
            style.map(name, fieldbackground=[("readonly", CARD_BG)], foreground=[("readonly", TEXT)])

        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT, font=self.f_body)
        style.map("TCheckbutton", background=[("active", CARD_BG)])

    def _card(self, parent: tk.Misc, title: str) -> tk.Frame:
        """A flat white 'card' with a thin border and a bold section title."""
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=20, pady=(0, 14))

        card = tk.Frame(outer, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        card.pack(fill="both", expand=True)

        tk.Label(card, text=title, bg=CARD_BG, fg=TEXT, font=self.f_section).pack(
            anchor="w", padx=16, pady=(14, 8),
        )
        return card

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{x}+{y}")

    # -- UI construction ---------------------------------------------------

    def _build_widgets(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(20, 16))
        tk.Label(header, text="Label Fixer", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(
            header, text="Crop, straighten, and print 4x6 shipping labels at full resolution.",
            bg=BG, fg=TEXT_MUTED, font=self.f_subtitle,
        ).pack(anchor="w", pady=(2, 0))

        # 1. Source file
        card1 = self._card(self, "Source PDF")
        file_row = tk.Frame(card1, bg=CARD_BG)
        file_row.pack(fill="x", padx=16, pady=(0, 16))
        self.file_label = tk.Label(
            file_row, text="No file selected", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_body,
            anchor="w",
        )
        self.file_label.pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse...", style="Secondary.TButton", command=self.on_browse).pack(side="right")

        # 2. Preview + options
        card2 = self._card(self, "Preview")
        preview_wrap = tk.Frame(card2, bg=CARD_BG)
        preview_wrap.pack(fill="both", padx=16, pady=(0, 4))

        self.preview_label = tk.Label(
            preview_wrap, text="Select a PDF to see a preview", anchor="center",
            bg=PREVIEW_BG, fg=TEXT_MUTED, font=self.f_body, width=48, height=14,
            highlightbackground=BORDER, highlightthickness=1,
        )
        self.preview_label.pack(fill="both", expand=True, pady=(0, 12))

        options_frame = tk.Frame(card2, bg=CARD_BG)
        options_frame.pack(fill="x", padx=16, pady=(0, 4))

        tk.Label(options_frame, text="Page", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small).grid(row=0, column=0, sticky="w")
        self.page_var = tk.IntVar(value=1)
        self.page_spin = ttk.Spinbox(
            options_frame, from_=1, to=1, width=4, textvariable=self.page_var,
            command=self.refresh_preview, state="disabled",
        )
        self.page_spin.grid(row=1, column=0, sticky="w", padx=(0, 20))

        tk.Label(options_frame, text="Rotation", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small).grid(row=0, column=1, sticky="w")
        self.rotate_var = tk.StringVar(value="auto")
        rotate_menu = ttk.Combobox(
            options_frame, textvariable=self.rotate_var, state="readonly", width=10,
            values=["auto", "cw", "ccw", "180", "none"],
        )
        rotate_menu.grid(row=1, column=1, sticky="w")
        rotate_menu.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())

        self.status_label = tk.Label(card2, text="", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small, anchor="w")
        self.status_label.pack(fill="x", padx=16, pady=(10, 16))

        # 3. Printer + print
        card3 = self._card(self, "Print")
        row = tk.Frame(card3, bg=CARD_BG)
        row.pack(fill="x", padx=16)

        tk.Label(row, text="Printer", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small).grid(row=0, column=0, sticky="w")
        self.printer_var = tk.StringVar()
        self.printer_menu = ttk.Combobox(row, textvariable=self.printer_var, state="readonly", width=24)
        self.printer_menu.grid(row=1, column=0, sticky="we", padx=(0, 16))
        row.grid_columnconfigure(0, weight=1)

        tk.Label(row, text="Copies", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small).grid(row=0, column=1, sticky="w")
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=99, width=4, textvariable=self.copies_var).grid(row=1, column=1, sticky="w")

        self.all_pages_var = tk.BooleanVar(value=False)
        self.all_pages_check = ttk.Checkbutton(
            card3, text="Print all pages in this PDF", variable=self.all_pages_var,
        )
        self.all_pages_check.pack(anchor="w", padx=16, pady=(14, 4))

        button_row = tk.Frame(card3, bg=CARD_BG)
        button_row.pack(fill="x", padx=16, pady=(10, 16))
        ttk.Button(button_row, text="Save corrected PDF...", style="Secondary.TButton", command=self.on_save_pdf).pack(side="left")
        self.print_button = ttk.Button(button_row, text="Print", style="Accent.TButton", command=self.on_print, state="disabled")
        self.print_button.pack(side="right")

    # -- Helpers -------------------------------------------------------------

    def _refresh_printers(self) -> None:
        try:
            names, default = core.get_printers()
        except Exception as exc:  # pywin32 missing / not on Windows / no printers
            names, default = [], None
            self.status_label.config(text=f"Could not list printers: {exc}")
        self.printer_menu["values"] = names
        if default:
            self.printer_var.set(default)
        elif names:
            self.printer_var.set(names[0])

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)
        self.update_idletasks()

    # -- Event handlers --------------------------------------------------

    def on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select shipping label PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            doc = fitz.open(path)
            self.page_count = len(doc)
            doc.close()
        except Exception as exc:
            messagebox.showerror("Could not open PDF", str(exc))
            return

        self.pdf_path = path
        self.file_label.config(text=path, fg=TEXT)
        self.page_var.set(1)
        self.page_spin.config(to=self.page_count, state="normal" if self.page_count > 1 else "disabled")
        self.print_button.config(state="normal")
        self.refresh_preview()

    def refresh_preview(self) -> None:
        if not self.pdf_path:
            return
        page_index = max(0, min(self.page_var.get() - 1, self.page_count - 1))
        try:
            doc, page = core.open_corrected_page(self.pdf_path, page_index, rotate=self.rotate_var.get())
            img = core.render_page(page, PREVIEW_DPI, PREVIEW_DPI, bilevel=True)
            label_w_in = page.rect.width / 72
            label_h_in = page.rect.height / 72
            doc.close()
        except Exception as exc:
            messagebox.showerror("Could not process PDF", str(exc))
            return

        display_img = img.convert("L").copy()
        display_img.thumbnail(PREVIEW_MAX_SIZE)
        self.preview_photo = ImageTk.PhotoImage(display_img)
        self.preview_label.config(image=self.preview_photo, text="", width=0, height=0)
        self._set_status(f"Label size: {label_w_in:.2f} x {label_h_in:.2f} in   |   {img.width}x{img.height} px @ {PREVIEW_DPI} DPI preview")

    def on_save_pdf(self) -> None:
        if not self.pdf_path:
            messagebox.showinfo("No file", "Select a source PDF first.")
            return
        out_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not out_path:
            return

        pages = range(self.page_count) if self.all_pages_var.get() else [self.page_var.get() - 1]
        try:
            src = fitz.open(self.pdf_path)
            for i in pages:
                core.correct_page(src[i], rotate=self.rotate_var.get())
            out = fitz.open()
            for i in pages:
                out.insert_pdf(src, from_page=i, to_page=i)
            out.save(out_path)
            src.close()
            out.close()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._set_status(f"Saved corrected PDF: {out_path}")

    def on_print(self) -> None:
        if not self.pdf_path:
            return
        printer_name = self.printer_var.get()
        if not printer_name:
            messagebox.showwarning("No printer", "Select a printer first.")
            return
        copies = self.copies_var.get()
        pages = range(self.page_count) if self.all_pages_var.get() else [self.page_var.get() - 1]

        self.print_button.config(state="disabled")
        try:
            self._set_status(f"Querying '{printer_name}' resolution...")
            dpi_x, dpi_y = core.get_printer_dpi(printer_name)

            for i in pages:
                doc, page = core.open_corrected_page(self.pdf_path, i, rotate=self.rotate_var.get())
                img = core.render_page(page, dpi_x, dpi_y, bilevel=True)
                doc.close()
                self._set_status(f"Printing page {i + 1} to '{printer_name}' at {dpi_x}x{dpi_y} DPI...")
                core.print_image(img, printer_name, copies=copies)

            self._set_status(f"Sent {len(list(pages))} page(s) to '{printer_name}' ({copies} copy/copies).")
        except Exception as exc:
            messagebox.showerror("Print failed", str(exc))
            self._set_status("Print failed.")
        finally:
            self.print_button.config(state="normal")


def main() -> None:
    app = LabelPrintApp()
    app.mainloop()


if __name__ == "__main__":
    main()
