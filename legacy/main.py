"""Raster → Plotter SVG  —  dot stippling with live preview."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from stipple import grid_halftone, random_stipple
from svg_export import export_svg

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PREVIEW_BG = "#ffffff"


# ── helpers ──────────────────────────────────────────────────────────────────

def _labeled_slider(
    parent,
    label: str,
    from_: float,
    to: float,
    var,
    fmt: str = "{:.1f}",
    steps: int = 200,
) -> None:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(6, 0))
    ctk.CTkLabel(row, text=label, anchor="w").pack(side="left")
    val_label = ctk.CTkLabel(row, text=fmt.format(var.get()), width=50, anchor="e")
    val_label.pack(side="right")

    def on_change(v):
        val_label.configure(text=fmt.format(float(v)))

    ctk.CTkSlider(
        parent,
        from_=from_,
        to=to,
        number_of_steps=steps,
        variable=var,
        command=on_change,
    ).pack(fill="x", pady=(2, 0))


# ── main app ─────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Raster → Plotter SVG")
        self.geometry("1200x760")
        self.minsize(900, 600)

        self.source_image: Image.Image | None = None
        self.dots: list[tuple[float, float, float]] = []
        self._preview_job: threading.Thread | None = None
        self._computing = False

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── left panel ──
        panel = ctk.CTkScrollableFrame(self, width=280, corner_radius=0)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 1))

        # Load image
        ctk.CTkLabel(panel, text="SOURCE IMAGE", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(12, 4))
        ctk.CTkButton(panel, text="Load image…", command=self._load_image).pack(fill="x")
        self._img_name_label = ctk.CTkLabel(panel, text="—", text_color="gray", wraplength=240)
        self._img_name_label.pack(anchor="w", pady=(4, 0))

        # Algo
        ctk.CTkLabel(panel, text="ALGORITHM", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(16, 4))
        self._algo = ctk.StringVar(value="grid")
        ctk.CTkRadioButton(panel, text="Grid halftone", variable=self._algo, value="grid",
                           command=self._on_algo_change).pack(anchor="w")
        ctk.CTkRadioButton(panel, text="Random stipple", variable=self._algo, value="random",
                           command=self._on_algo_change).pack(anchor="w", pady=(4, 0))

        # ── grid params ──
        self._grid_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self._grid_frame.pack(fill="x")

        self._grid_spacing = ctk.IntVar(value=10)
        _labeled_slider(self._grid_frame, "Grid spacing (px)", 3, 60, self._grid_spacing, "{:.0f}", 57)

        self._min_radius = ctk.DoubleVar(value=0.5)
        _labeled_slider(self._grid_frame, "Min dot radius (px)", 0.0, 15.0, self._min_radius)

        self._max_radius = ctk.DoubleVar(value=4.5)
        _labeled_slider(self._grid_frame, "Max dot radius (px)", 0.5, 20.0, self._max_radius)

        # ── random params ──
        self._random_frame = ctk.CTkFrame(panel, fg_color="transparent")

        self._dot_count = ctk.IntVar(value=8000)
        _labeled_slider(self._random_frame, "Dot count", 200, 60000, self._dot_count, "{:.0f}", 598)

        self._dot_radius = ctk.DoubleVar(value=1.5)
        _labeled_slider(self._random_frame, "Dot radius (px)", 0.3, 15.0, self._dot_radius)

        self._jitter = ctk.DoubleVar(value=0.0)
        _labeled_slider(self._random_frame, "Position jitter (px)", 0.0, 10.0, self._jitter)

        # Initially show grid frame only
        self._on_algo_change()

        # Output
        ctk.CTkLabel(panel, text="OUTPUT", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(16, 4))

        self._output_width = ctk.DoubleVar(value=100.0)
        _labeled_slider(panel, "Physical width (mm)", 10.0, 500.0, self._output_width, "{:.0f}", 490)

        # Preview toggle: show original behind dots
        self._show_original = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(panel, text="Show original behind dots", variable=self._show_original,
                        command=self._refresh_canvas).pack(anchor="w", pady=(10, 0))

        # Actions
        ctk.CTkLabel(panel, text="", height=8).pack()
        self._preview_btn = ctk.CTkButton(panel, text="▶  Preview", command=self._start_preview)
        self._preview_btn.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(panel, text="Export SVG…", command=self._export).pack(fill="x")

        self._status = ctk.CTkLabel(panel, text="", text_color="gray", wraplength=240)
        self._status.pack(anchor="w", pady=(8, 0))

        # ── right: preview canvas ──
        canvas_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=PREVIEW_BG)
        canvas_frame.grid(row=0, column=1, sticky="nsew")
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(canvas_frame, bg=PREVIEW_BG, highlightthickness=0)
        self._canvas.grid(sticky="nsew")
        self._canvas.bind("<Configure>", lambda _e: self._refresh_canvas())

        self._canvas_img_id = None
        self._tk_img: ImageTk.PhotoImage | None = None

    def _on_algo_change(self):
        if self._algo.get() == "grid":
            self._random_frame.pack_forget()
            self._grid_frame.pack(fill="x")
        else:
            self._grid_frame.pack_forget()
            self._random_frame.pack(fill="x")

    # ── image loading ─────────────────────────────────────────────────────────

    def _load_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self.source_image = Image.open(path)
            self.source_image.load()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open image:\n{exc}")
            return

        name = Path(path).name
        w, h = self.source_image.size
        self._img_name_label.configure(text=f"{name}\n{w} × {h} px  |  {self.source_image.mode}")
        self.dots = []
        self._status.configure(text="Image loaded. Press Preview.")
        self._refresh_canvas()

    # ── stippling ─────────────────────────────────────────────────────────────

    def _start_preview(self):
        if self.source_image is None:
            messagebox.showwarning("No image", "Load an image first.")
            return
        if self._computing:
            return

        self._computing = True
        self._preview_btn.configure(state="disabled", text="Computing…")
        self._status.configure(text="Computing dots…")

        t = threading.Thread(target=self._compute_dots, daemon=True)
        t.start()

    def _compute_dots(self):
        try:
            img = self.source_image
            if self._algo.get() == "grid":
                dots = grid_halftone(
                    img,
                    grid_spacing=self._grid_spacing.get(),
                    min_radius=self._min_radius.get(),
                    max_radius=self._max_radius.get(),
                )
            else:
                dots = random_stipple(
                    img,
                    dot_count=self._dot_count.get(),
                    dot_radius=self._dot_radius.get(),
                    jitter=self._jitter.get(),
                )
            self.dots = dots
            self.after(0, self._on_dots_ready)
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Error", str(exc)))
            self.after(0, self._reset_preview_btn)

    def _on_dots_ready(self):
        self._computing = False
        n = len(self.dots)
        self._status.configure(text=f"{n:,} dots computed.")
        self._reset_preview_btn()
        self._refresh_canvas()

    def _reset_preview_btn(self):
        self._computing = False
        self._preview_btn.configure(state="normal", text="▶  Preview")

    # ── canvas rendering ──────────────────────────────────────────────────────

    def _refresh_canvas(self):
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        if self.source_image is None and not self.dots:
            self._canvas.delete("all")
            self._canvas.create_text(cw // 2, ch // 2, text="Load an image to start",
                                     fill="#aaaaaa", font=("Helvetica", 14))
            return

        img_w, img_h = self.source_image.size if self.source_image else (cw, ch)

        # Scale to fit canvas
        scale = min(cw / img_w, ch / img_h)
        pw = int(img_w * scale)
        ph = int(img_h * scale)

        # Background
        preview = Image.new("RGB", (pw, ph), (255, 255, 255))

        # Optional: faded original behind dots
        if self._show_original.get() and self.source_image is not None:
            orig = self.source_image.convert("RGBA").resize((pw, ph), Image.LANCZOS)
            white = Image.new("RGBA", (pw, ph), (255, 255, 255, 255))
            blended = Image.blend(white, orig, alpha=0.25)
            preview.paste(blended.convert("RGB"))

        # Draw dots
        if self.dots:
            draw = ImageDraw.Draw(preview)
            for cx, cy, r in self.dots:
                sx, sy, sr = cx * scale, cy * scale, r * scale
                sr = max(sr, 0.5)
                draw.ellipse(
                    (sx - sr, sy - sr, sx + sr, sy + sr),
                    fill=(0, 0, 0),
                )

        # Center on canvas
        ox = (cw - pw) // 2
        oy = (ch - ph) // 2

        self._tk_img = ImageTk.PhotoImage(preview)
        self._canvas.delete("all")
        self._canvas_img_id = self._canvas.create_image(ox, oy, anchor="nw", image=self._tk_img)

    # ── SVG export ────────────────────────────────────────────────────────────

    def _export(self):
        if not self.dots:
            messagebox.showwarning("Nothing to export", "Generate a preview first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".svg",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            w, h = self.source_image.size
            export_svg(
                self.dots,
                img_width_px=w,
                img_height_px=h,
                output_path=path,
                output_width_mm=self._output_width.get(),
            )
            self._status.configure(text=f"Saved: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))


if __name__ == "__main__":
    app = App()
    app.mainloop()
