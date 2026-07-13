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

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import ImageTk

import core

PREVIEW_DPI = 150
PREVIEW_MAX_SIZE = (380, 560)  # px, keeps the window a sane size


class LabelPrintApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Shipping Label Printer")
        self.resizable(False, False)

        self.pdf_path: str | None = None
        self.page_count = 1
        self.preview_photo: ImageTk.PhotoImage | None = None  # keep a reference alive

        self._build_widgets()
        self._refresh_printers()

    # -- UI construction ---------------------------------------------------

    def _build_widgets(self) -> None:
        # 1. Source file
        file_frame = ttk.LabelFrame(self, text="1. Source PDF")
        file_frame.pack(fill="x", padx=8, pady=6)

        self.file_label = ttk.Label(file_frame, text="No file selected", foreground="#666")
        self.file_label.pack(side="left", padx=8, pady=8, fill="x", expand=True)
        ttk.Button(file_frame, text="Browse...", command=self.on_browse).pack(side="right", padx=8, pady=8)

        # 2. Preview + options
        preview_frame = ttk.LabelFrame(self, text="2. Preview (what will be printed)")
        preview_frame.pack(fill="both", expand=True, padx=8, pady=6)

        self.preview_label = ttk.Label(
            preview_frame, text="Select a PDF to see a preview", anchor="center",
            background="#f0f0f0", width=48,
        )
        self.preview_label.pack(padx=8, pady=8, fill="both", expand=True)

        options_frame = ttk.Frame(preview_frame)
        options_frame.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(options_frame, text="Page:").grid(row=0, column=0, sticky="w")
        self.page_var = tk.IntVar(value=1)
        self.page_spin = ttk.Spinbox(
            options_frame, from_=1, to=1, width=4, textvariable=self.page_var,
            command=self.refresh_preview, state="disabled",
        )
        self.page_spin.grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(options_frame, text="Rotation:").grid(row=0, column=2, sticky="w")
        self.rotate_var = tk.StringVar(value="auto")
        rotate_menu = ttk.Combobox(
            options_frame, textvariable=self.rotate_var, state="readonly", width=10,
            values=["auto", "cw", "ccw", "180", "none"],
        )
        rotate_menu.grid(row=0, column=3, sticky="w", padx=(4, 0))
        rotate_menu.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())

        self.status_label = ttk.Label(preview_frame, text="", foreground="#666")
        self.status_label.pack(padx=8, pady=(0, 8), anchor="w")

        # 3. Printer + print
        printer_frame = ttk.LabelFrame(self, text="3. Output printer")
        printer_frame.pack(fill="x", padx=8, pady=6)

        row = ttk.Frame(printer_frame)
        row.pack(fill="x", padx=8, pady=8)

        ttk.Label(row, text="Printer:").grid(row=0, column=0, sticky="w")
        self.printer_var = tk.StringVar()
        self.printer_menu = ttk.Combobox(row, textvariable=self.printer_var, state="readonly", width=28)
        self.printer_menu.grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(row, text="Copies:").grid(row=0, column=2, sticky="w")
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=99, width=4, textvariable=self.copies_var).grid(row=0, column=3, sticky="w", padx=4)

        self.all_pages_var = tk.BooleanVar(value=False)
        self.all_pages_check = ttk.Checkbutton(
            printer_frame, text="Print all pages in this PDF", variable=self.all_pages_var,
        )
        self.all_pages_check.pack(anchor="w", padx=8, pady=(0, 4))

        button_row = ttk.Frame(printer_frame)
        button_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(button_row, text="Save corrected PDF...", command=self.on_save_pdf).pack(side="left")
        self.print_button = ttk.Button(button_row, text="Print", command=self.on_print, state="disabled")
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
        self.file_label.config(text=path, foreground="#000")
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
        self.preview_label.config(image=self.preview_photo, text="")
        self._set_status(f"Label size: {label_w_in:.2f} x {label_h_in:.2f} in  ({img.width}x{img.height} px @ {PREVIEW_DPI} DPI preview)")

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
