#!/usr/bin/env python3
"""
gui.py - Point-and-click front end for label_print / core.

Workflow: add one or more shipping-label PDFs -> use the Prev/Next
selector to flip through them, each showing an Original/Fixed
side-by-side preview -> pick a printer (and copy count) -> Print.

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
from PIL import Image, ImageTk

import core

PREVIEW_DPI = 150
PREVIEW_MAX_SIZE = (230, 330)  # px, per pane (Original / Fixed side by side)

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

        self.files: list[str] = []
        self.current_index: int = -1
        self.page_count = 1
        # Keep PhotoImage references alive (Tk drops images with no ref).
        self.original_photo: ImageTk.PhotoImage | None = None
        self.fixed_photo: ImageTk.PhotoImage | None = None

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
            background=[("active", PREVIEW_BG), ("disabled", CARD_BG)],
            foreground=[("disabled", TEXT_MUTED)],
            bordercolor=[("!disabled", BORDER)],
        )

        style.configure(
            "Nav.TButton", background=CARD_BG, foreground=TEXT,
            font=self.f_button, padding=(10, 8), borderwidth=1, relief="solid",
        )
        style.map(
            "Nav.TButton",
            background=[("active", PREVIEW_BG), ("disabled", CARD_BG)],
            foreground=[("disabled", BORDER)],
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

    def _preview_pane(self, parent: tk.Misc, caption: str) -> tuple[tk.Frame, tk.Label]:
        """Fixed-size box (so the layout doesn't jump when the image
        changes) with a small caption above it."""
        col = tk.Frame(parent, bg=CARD_BG)
        tk.Label(col, text=caption, bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small).pack(anchor="w", pady=(0, 4))

        box = tk.Frame(col, bg=PREVIEW_BG, width=PREVIEW_MAX_SIZE[0] + 20, height=PREVIEW_MAX_SIZE[1] + 20,
                        highlightbackground=BORDER, highlightthickness=1)
        box.pack_propagate(False)
        box.pack()

        img_label = tk.Label(box, text="—", anchor="center", bg=PREVIEW_BG, fg=TEXT_MUTED, font=self.f_body)
        img_label.pack(fill="both", expand=True)
        return col, img_label

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

        # 1. Source files
        card1 = self._card(self, "Source PDFs")
        add_row = tk.Frame(card1, bg=CARD_BG)
        add_row.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(add_row, text="Add files...", style="Secondary.TButton", command=self.on_add_files).pack(side="left")
        self.file_count_label = tk.Label(add_row, text="No files loaded", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small)
        self.file_count_label.pack(side="right")

        # 1.5 Quick file switcher -- sits between Source PDFs and Preview
        # so it's obvious it controls which file the Preview below shows.
        nav_card = self._card(self, "Viewing")
        nav_row = tk.Frame(nav_card, bg=CARD_BG)
        nav_row.pack(fill="x", padx=16, pady=(0, 8))

        self.prev_button = ttk.Button(nav_row, text="‹ Prev", style="Nav.TButton", command=self.on_prev_file, state="disabled")
        self.prev_button.pack(side="left")

        self.file_selector = ttk.Combobox(nav_row, state="disabled", font=self.f_body, justify="center")
        self.file_selector.pack(side="left", fill="x", expand=True, padx=8)
        self.file_selector.bind("<<ComboboxSelected>>", self.on_file_selector_change)

        self.next_button = ttk.Button(nav_row, text="Next ›", style="Nav.TButton", command=self.on_next_file, state="disabled")
        self.next_button.pack(side="left")

        self.remove_button = ttk.Button(nav_row, text="Remove", style="Secondary.TButton", command=self.on_remove_file, state="disabled")
        self.remove_button.pack(side="left", padx=(8, 0))

        self.path_label = tk.Label(nav_card, text="No files loaded", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small, anchor="w", wraplength=520)
        self.path_label.pack(fill="x", padx=16, pady=(0, 16))

        # 2. Preview (Original next to Fixed)
        card2 = self._card(self, "Preview")
        columns = tk.Frame(card2, bg=CARD_BG)
        columns.pack(padx=16, pady=(0, 4))

        left_col, self.original_label = self._preview_pane(columns, "Original (as received)")
        left_col.grid(row=0, column=0, padx=(0, 10))
        right_col, self.fixed_label = self._preview_pane(columns, "Fixed (what will print)")
        right_col.grid(row=0, column=1, padx=(10, 0))

        options_frame = tk.Frame(card2, bg=CARD_BG)
        options_frame.pack(fill="x", padx=16, pady=(12, 4))

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

        self.status_label = tk.Label(card2, text="", bg=CARD_BG, fg=TEXT_MUTED, font=self.f_small, anchor="w", justify="left")
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

        checks = tk.Frame(card3, bg=CARD_BG)
        checks.pack(anchor="w", padx=16, pady=(14, 4))
        self.all_pages_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Print all pages in this file", variable=self.all_pages_var).pack(anchor="w")
        self.all_files_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Print every loaded file", variable=self.all_files_var).pack(anchor="w")

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

    def _refresh_file_selector(self) -> None:
        n = len(self.files)
        values = [f"{i + 1}. {Path(p).name}" for i, p in enumerate(self.files)]
        self.file_selector["values"] = values
        self.file_selector.config(state="readonly" if values else "disabled")
        if 0 <= self.current_index < n:
            self.file_selector.set(values[self.current_index])
        else:
            self.file_selector.set("")

        self.remove_button.config(state="normal" if n else "disabled")
        self.prev_button.config(state="normal" if self.current_index > 0 else "disabled")
        self.next_button.config(state="normal" if 0 <= self.current_index < n - 1 else "disabled")

        self.file_count_label.config(text=f"{n} file{'s' if n != 1 else ''} loaded" if n else "No files loaded")
        if 0 <= self.current_index < n:
            self.path_label.config(text=f"File {self.current_index + 1} of {n}  —  {self.files[self.current_index]}", fg=TEXT)
        else:
            self.path_label.config(text="No files loaded", fg=TEXT_MUTED)

    def _clear_previews(self) -> None:
        self.original_photo = None
        self.fixed_photo = None
        self.original_label.config(image="", text="—")
        self.fixed_label.config(image="", text="—")
        self.status_label.config(text="")
        self.print_button.config(state="disabled")
        self.page_spin.config(to=1, state="disabled")
        self.page_var.set(1)

    # -- Event handlers --------------------------------------------------

    def on_add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select shipping label PDF(s)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not paths:
            return
        first_new_index = None
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                if first_new_index is None:
                    first_new_index = len(self.files) - 1
        if first_new_index is None:
            return  # everything picked was already loaded
        self.select_file(first_new_index)

    def on_remove_file(self) -> None:
        if not (0 <= self.current_index < len(self.files)):
            return
        del self.files[self.current_index]
        if not self.files:
            self.current_index = -1
            self._refresh_file_selector()
            self._clear_previews()
            return
        self.select_file(min(self.current_index, len(self.files) - 1))

    def on_prev_file(self) -> None:
        if self.current_index > 0:
            self.select_file(self.current_index - 1)

    def on_next_file(self) -> None:
        if self.current_index < len(self.files) - 1:
            self.select_file(self.current_index + 1)

    def on_file_selector_change(self, _event: object) -> None:
        idx = self.file_selector.current()
        if idx >= 0:
            self.select_file(idx)

    def select_file(self, index: int) -> None:
        path = self.files[index]
        try:
            doc = fitz.open(path)
            self.page_count = len(doc)
            doc.close()
        except Exception as exc:
            messagebox.showerror("Could not open PDF", str(exc))
            return

        self.current_index = index
        self._refresh_file_selector()
        self.page_var.set(1)
        self.page_spin.config(to=self.page_count, state="normal" if self.page_count > 1 else "disabled")
        self.print_button.config(state="normal")
        self.refresh_preview()

    def _thumb(self, img: Image.Image) -> ImageTk.PhotoImage:
        display_img = img.convert("L").copy()
        display_img.thumbnail(PREVIEW_MAX_SIZE)
        return ImageTk.PhotoImage(display_img)

    def refresh_preview(self) -> None:
        if not (0 <= self.current_index < len(self.files)):
            return
        path = self.files[self.current_index]
        page_index = max(0, min(self.page_var.get() - 1, self.page_count - 1))

        try:
            # Original, as-is -- no crop/rotate -- so it's a true "before".
            raw_doc = fitz.open(path)
            raw_page = raw_doc[page_index]
            raw_pix = raw_page.get_pixmap(dpi=PREVIEW_DPI)
            raw_mode = "RGB" if raw_pix.n < 4 else "RGBA"
            raw_img = Image.frombytes(raw_mode, (raw_pix.width, raw_pix.height), raw_pix.samples)
            raw_w_in, raw_h_in = raw_page.rect.width / 72, raw_page.rect.height / 72
            raw_doc.close()

            # Fixed, via the same crop+rotate+render pipeline used to print.
            fixed_doc, fixed_page = core.open_corrected_page(path, page_index, rotate=self.rotate_var.get())
            fixed_img = core.render_page(fixed_page, PREVIEW_DPI, PREVIEW_DPI, bilevel=True)
            fixed_w_in, fixed_h_in = fixed_page.rect.width / 72, fixed_page.rect.height / 72
            fixed_doc.close()
        except Exception as exc:
            messagebox.showerror("Could not process PDF", str(exc))
            return

        self.original_photo = self._thumb(raw_img)
        self.original_label.config(image=self.original_photo, text="")
        self.fixed_photo = self._thumb(fixed_img)
        self.fixed_label.config(image=self.fixed_photo, text="")

        self._set_status(
            f"Original: {raw_w_in:.2f} x {raw_h_in:.2f} in (page {page_index + 1} of {self.page_count})\n"
            f"Fixed: {fixed_w_in:.2f} x {fixed_h_in:.2f} in  |  {fixed_img.width}x{fixed_img.height} px @ {PREVIEW_DPI} DPI preview"
        )

    def on_save_pdf(self) -> None:
        if not (0 <= self.current_index < len(self.files)):
            messagebox.showinfo("No file", "Add a source PDF first.")
            return
        path = self.files[self.current_index]
        out_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not out_path:
            return

        pages = range(self.page_count) if self.all_pages_var.get() else [self.page_var.get() - 1]
        try:
            src = fitz.open(path)
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
        if not (0 <= self.current_index < len(self.files)):
            return
        printer_name = self.printer_var.get()
        if not printer_name:
            messagebox.showwarning("No printer", "Select a printer first.")
            return
        copies = self.copies_var.get()

        if self.all_files_var.get():
            targets = list(self.files)
        else:
            targets = [self.files[self.current_index]]

        self.print_button.config(state="disabled")
        total_sent = 0
        try:
            self._set_status(f"Querying '{printer_name}' resolution...")
            dpi_x, dpi_y = core.get_printer_dpi(printer_name)

            for path in targets:
                doc = fitz.open(path)
                page_count = len(doc)
                doc.close()
                is_current = path == self.files[self.current_index]
                if self.all_pages_var.get():
                    pages = range(page_count)
                elif is_current:
                    pages = [max(0, min(self.page_var.get() - 1, page_count - 1))]
                else:
                    pages = [0]

                for i in pages:
                    fdoc, fpage = core.open_corrected_page(path, i, rotate=self.rotate_var.get())
                    img = core.render_page(fpage, dpi_x, dpi_y, bilevel=True)
                    fdoc.close()
                    self._set_status(f"Printing {Path(path).name} (page {i + 1}) to '{printer_name}' at {dpi_x}x{dpi_y} DPI...")
                    core.print_image(img, printer_name, copies=copies)
                    total_sent += 1

            self._set_status(f"Sent {total_sent} page(s) across {len(targets)} file(s) to '{printer_name}' ({copies} copy/copies).")
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
