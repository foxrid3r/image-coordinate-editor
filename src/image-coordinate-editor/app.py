"""
PNG Coordinate System Metadata Editor
=====================================

A modern Tkinter / sv_ttk utility for defining one or more 2D coordinate
systems in a PNG image.

Features
--------
- Browse for a PNG image.
- Image preview scales with the window while retaining aspect ratio.
- Live source-image pixel coordinates under the mouse cursor.
- Select Origin, X Reference, and Y Reference points by clicking the image.
- Cursor crosshairs for precise point placement.
- Strong color feedback for the active point-selection mode.
- Optional automatic Y axis, clockwise or counterclockwise from X.
- Editable pixel-coordinate and real-world-coordinate fields.
- Multiple named coordinate systems per image.
- Coordinate-system overlays drawn over the preview.
- JSON data embedded in a PNG iTXt metadata chunk.
- Existing embedded coordinate systems are detected automatically.
- Existing PNG text metadata, EXIF bytes, ICC profile, and DPI are preserved
  when practical.

Dependencies
------------
    pip install pillow sv-ttk

sv-ttk is optional. The application falls back to the normal ttk theme if it
is not installed.

Metadata note
-------------
PNG files do not normally use JPEG-style EXIF fields for arbitrary application
data. This application stores JSON in a standards-compliant PNG iTXt chunk
named "coordinate_systems_json". Existing EXIF data is preserved when saving.
"""

from __future__ import annotations

import copy
import json
import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from PIL import Image, ImageTk

from .models import POINT_NAMES, new_coordinate_system
from .png_metadata import (
    METADATA_KEY,
    build_metadata_payload,
    read_coordinate_metadata,
    write_png_with_metadata,
)
from .transforms import affine_cache_key, pixel_to_world

try:
    import sv_ttk
except ImportError:
    sv_ttk = None


APP_TITLE = "PNG Coordinate System Metadata Editor"
DEFAULT_WINDOW_SIZE = "1450x850"
MIN_WINDOW_WIDTH = 1050
MIN_WINDOW_HEIGHT = 650

PREVIEW_BG = "#101010"
EMPTY_TEXT_COLOR = "#9ca3af"
RESIZE_DEBOUNCE_MS = 80
INTERACTION_REDRAW_MS = 8
INTERACTION_SETTLE_MS = 140
PYRAMID_MIN_DIMENSION = 512
MARKER_RADIUS = 7
MARKER_HIT_RADIUS = 12
MIN_ZOOM = 0.05
MAX_ZOOM = 32.0
ZOOM_STEP = 1.15
FAST_ZOOM_STEP = 1.35

POINT_LABELS = {
    "origin": "Origin",
    "x_point": "X Point",
    "y_point": "Y Point",
}

# Tk Canvas colors are deliberately high-contrast because the image content is
# unknown. The active coordinate system uses the brighter primary palette.
ACTIVE_COLORS = {
    "origin": "#0004fa",
    "x_point": "#ff3b30",  # X axis: red
    "y_point": "#34c759",  # Y axis: green
}
INACTIVE_COLORS = {
    "origin": "#4537c2",
    "x_point": "#9f3d38",
    "y_point": "#3f874f",
}


@dataclass
class DisplayTransform:
    """Mapping between source-image pixels and preview-canvas coordinates."""

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    display_width: int = 0
    display_height: int = 0

    def image_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.offset_x + x * self.scale,
            self.offset_y + y * self.scale,
        )

    def canvas_to_image(self, x: float, y: float) -> tuple[float, float]:
        return (
            (x - self.offset_x) / self.scale,
            (y - self.offset_y) / self.scale,
        )

    def contains_canvas_point(self, x: float, y: float) -> bool:
        return (
            self.offset_x <= x < self.offset_x + self.display_width
            and self.offset_y <= y < self.offset_y + self.display_height
        )



class PngCoordinateEditor:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(DEFAULT_WINDOW_SIZE)
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.image_path: Path | None = None
        self.source_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_image_item: int | None = None
        self.image_pyramid: list[Image.Image] = []
        self.display_transform = DisplayTransform()
        self.resize_job: str | None = None
        self.interaction_settle_job: str | None = None
        self.interaction_active = False
        self._affine_cache_key: tuple[Any, ...] | None = None
        self._affine_cache_coefficients: tuple[float, float, float, float, float, float] | None = None

        # Persistent image-view state. A None scale is used only briefly
        # after loading an image. The first redraw calculates and stores a
        # fit-to-window scale; subsequent window resizes preserve user zoom.
        self.view_scale: float | None = None
        self.view_center_x = 0.0
        self.view_center_y = 0.0
        self.pan_start_canvas: tuple[float, float] | None = None
        self.pan_start_center: tuple[float, float] | None = None

        self.coordinate_systems: list[dict[str, Any]] = []
        self.active_system_index: int | None = None
        self.active_point_name: str | None = None
        self.auto_y_perpendicular_var = tk.BooleanVar(value=False)
        self.auto_y_direction_var = tk.StringVar(value="counterclockwise")
        self.cursor_canvas_position: tuple[float, float] | None = None
        self.dirty = False
        self._loading_fields = False

        self.file_label_var = tk.StringVar(value="No image loaded")
        self.status_var = tk.StringVar(value="Browse to load a PNG image.")
        self.cursor_pixel_var = tk.StringVar(value="Pixel: —")
        self.cursor_world_var = tk.StringVar(value="World: —")
        self.zoom_var = tk.StringVar(value="Zoom: —")
        self.active_instruction_var = tk.StringVar(
            value="Choose Origin, X Point, or Y Point, then click the image."
        )
        self.system_name_var = tk.StringVar()

        self.point_vars: dict[str, dict[str, tk.StringVar]] = {}
        for point_name in POINT_NAMES:
            self.point_vars[point_name] = {
                "pixel_x": tk.StringVar(),
                "pixel_y": tk.StringVar(),
                "world_x": tk.StringVar(),
                "world_y": tk.StringVar(),
            }

        self._configure_theme()
        self._build_ui()
        self._bind_events()
        self._update_controls_enabled()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # Theme and UI construction
    # ------------------------------------------------------------------

    def _configure_theme(self) -> None:
        if sv_ttk is not None:
            sv_ttk.set_theme("dark")

        style = ttk.Style()
        style.configure("Section.TLabelframe", padding=8)
        style.configure("Section.TLabelframe.Label", font=("Segoe UI Semibold", 10))
        style.configure(
            "ActivePoint.TButton",
            background="#d97706",
            foreground="#ffffff",
            font=("Segoe UI", 9),
        )
        style.map(
            "ActivePoint.TButton",
            background=[
                ("active", "#f59e0b"),
                ("pressed", "#b45309"),
                ("disabled", "#6b4a20"),
            ],
            foreground=[("disabled", "#d1d5db")],
        )
        style.configure("Muted.TLabel", foreground="#9ca3af")
        style.configure("Status.TLabel", padding=(8, 5))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_toolbar()

        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        self._build_preview()
        self._build_inspector()

        self.main_pane.add(self.preview_shell, weight=4)
        self.main_pane.add(self.inspector_container, weight=1)

        # Set the initial inspector width only after the PanedWindow has been
        # mapped and has a real on-screen width. after_idle() is too early on
        # some Windows/Tk builds and sees a temporary width of 1 pixel.
        self._initial_inspector_width = 300
        self._inspector_width_initialized = False
        self.main_pane.bind("<Configure>", self._initialize_inspector_width, add="+")

        status_bar = ttk.Frame(self.root)
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)

        ttk.Label(
            status_bar,
            textvariable=self.status_var,
            style="Status.TLabel",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        ttk.Separator(status_bar, orient="vertical").grid(
            row=0, column=1, sticky="ns", padx=4
        )

        ttk.Label(
            status_bar,
            textvariable=self.cursor_pixel_var,
            style="Status.TLabel",
            width=22,
            anchor="w",
        ).grid(row=0, column=2, sticky="w")

        ttk.Label(
            status_bar,
            textvariable=self.cursor_world_var,
            style="Status.TLabel",
            width=28,
            anchor="w",
        ).grid(row=0, column=3, sticky="w")

        ttk.Label(
            status_bar,
            textvariable=self.zoom_var,
            style="Status.TLabel",
            width=14,
            anchor="w",
        ).grid(row=0, column=4, sticky="w")

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(20, weight=1)

        self.browse_button = ttk.Button(
            toolbar, text="Browse Image", command=self.browse_image
        )
        self.browse_button.grid(row=0, column=0, padx=(0, 6))

        self.save_button = ttk.Button(
            toolbar, text="Save Metadata", command=self.save_metadata
        )
        self.save_button.grid(row=0, column=1, padx=6)

        self.save_as_button = ttk.Button(
            toolbar, text="Save As", command=self.save_metadata_as
        )
        self.save_as_button.grid(row=0, column=2, padx=6)

        ttk.Separator(toolbar, orient="vertical").grid(
            row=0, column=3, sticky="ns", padx=10
        )

        self.add_system_button = ttk.Button(
            toolbar, text="Add Coordinate System", command=self.add_coordinate_system
        )
        self.add_system_button.grid(row=0, column=4, padx=6)

        self.delete_system_button = ttk.Button(
            toolbar, text="Delete System", command=self.delete_coordinate_system
        )
        self.delete_system_button.grid(row=0, column=5, padx=6)

        ttk.Separator(toolbar, orient="vertical").grid(
            row=0, column=6, sticky="ns", padx=10
        )

        self.zoom_out_button = ttk.Button(
            toolbar, text="Zoom −", command=self.zoom_out
        )
        self.zoom_out_button.grid(row=0, column=7, padx=(0, 4))

        self.zoom_in_button = ttk.Button(
            toolbar, text="Zoom +", command=self.zoom_in
        )
        self.zoom_in_button.grid(row=0, column=8, padx=4)

        self.fit_button = ttk.Button(
            toolbar, text="Fit", command=self.fit_image_to_window
        )
        self.fit_button.grid(row=0, column=9, padx=4)

        self.actual_size_button = ttk.Button(
            toolbar, text="100%", command=self.zoom_100_percent
        )
        self.actual_size_button.grid(row=0, column=10, padx=4)

        self.file_label = ttk.Label(
            toolbar,
            textvariable=self.file_label_var,
            anchor="e",
        )
        self.file_label.grid(row=0, column=20, sticky="e", padx=(20, 0))

    def _build_preview(self) -> None:
        self.preview_shell = ttk.Frame(self.main_pane)
        self.preview_shell.columnconfigure(0, weight=1)
        self.preview_shell.rowconfigure(0, weight=1)

        self.image_canvas = tk.Canvas(
            self.preview_shell,
            bg=PREVIEW_BG,
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.image_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_image_item = self.image_canvas.create_image(
            0,
            0,
            anchor=tk.NW,
            state=tk.HIDDEN,
            tags=("preview_image",),
        )

        self.image_canvas.create_text(
            0,
            0,
            text="Browse to load a PNG image",
            fill=EMPTY_TEXT_COLOR,
            tags=("empty_text",),
            anchor="center",
            font=("Segoe UI", 16),
        )

        instruction_frame = ttk.Frame(self.preview_shell, padding=(8, 5))
        instruction_frame.grid(row=1, column=0, sticky="ew")
        instruction_frame.columnconfigure(0, weight=1)

        ttk.Label(
            instruction_frame,
            textvariable=self.active_instruction_var,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        ttk.Label(
            instruction_frame,
            text="Wheel: zoom  •  Middle-drag: pan  •  Ctrl+0: fit  •  Ctrl+1: 100%  •  Esc: cancel",
            style="Muted.TLabel",
        ).grid(row=0, column=1, padx=(12, 0))


    def _initialize_inspector_width(self, event: tk.Event) -> None:
        """Set the inspector width once, after the PanedWindow is fully sized."""
        if self._inspector_width_initialized:
            return

        pane_width = int(event.width)
        target_width = int(self._initial_inspector_width)

        # Ignore Tk's early placeholder Configure events. Wait until the pane
        # has enough space to establish the requested preview/inspector split.
        if pane_width <= target_width + 200:
            return

        self.main_pane.sashpos(0, pane_width - target_width)
        self._inspector_width_initialized = True

    def _build_inspector(self) -> None:
        self.inspector_container = ttk.Frame(
            self.main_pane, padding=(10, 0, 0, 0)
        )
        self.inspector_container.columnconfigure(0, weight=1)
        self.inspector_container.rowconfigure(0, weight=1)

        self.inspector_canvas = tk.Canvas(
            self.inspector_container,
            highlightthickness=0,
            bd=0,
        )
        self.inspector_scrollbar = ttk.Scrollbar(
            self.inspector_container,
            orient="vertical",
            command=self.inspector_canvas.yview,
        )
        self.inspector = ttk.Frame(self.inspector_canvas)
        self.inspector.columnconfigure(0, weight=1)

        self.inspector_window = self.inspector_canvas.create_window(
            (0, 0),
            window=self.inspector,
            anchor="nw",
        )
        self.inspector_canvas.configure(
            yscrollcommand=self.inspector_scrollbar.set
        )

        self.inspector_canvas.grid(row=0, column=0, sticky="nsew")
        self.inspector_scrollbar.grid(row=0, column=1, sticky="ns")

        self._build_system_list_section()
        self._build_axis_options_section()
        self._build_point_sections()
        self._build_metadata_section()

        self.inspector.bind(
            "<Configure>",
            lambda event: self._sync_inspector_scroll_state(),
        )
        self.inspector_canvas.bind(
            "<Configure>",
            self._on_inspector_canvas_resize,
        )

    def _build_system_list_section(self) -> None:
        frame = ttk.LabelFrame(
            self.inspector,
            text="Coordinate Systems",
            style="Section.TLabelframe",
        )
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
        list_frame.columnconfigure(0, weight=1)

        self.system_listbox = tk.Listbox(
            list_frame,
            height=5,
            exportselection=False,
            activestyle="none",
        )
        self.system_listbox.grid(row=0, column=0, sticky="ew")

        scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.system_listbox.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.system_listbox.configure(yscrollcommand=scrollbar.set)

        ttk.Label(frame, text="Name").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.system_name_entry = ttk.Entry(
            frame,
            textvariable=self.system_name_var,
        )
        self.system_name_entry.grid(
            row=2, column=0, sticky="ew", pady=(2, 0)
        )

        self.rename_button = ttk.Button(
            frame,
            text="Apply Name",
            command=self.apply_system_name,
        )
        self.rename_button.grid(row=2, column=1, padx=(6, 0), pady=(2, 0))


    def _build_axis_options_section(self) -> None:
        frame = ttk.LabelFrame(
            self.inspector,
            text="Axis Definition",
            style="Section.TLabelframe",
        )
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        self.auto_y_checkbox = ttk.Checkbutton(
            frame,
            text="Automatically define Y perpendicular to X",
            variable=self.auto_y_perpendicular_var,
            command=self._on_auto_y_toggled,
        )
        self.auto_y_checkbox.grid(
            row=0, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(frame, text="Y direction:").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )

        direction_frame = ttk.Frame(frame)
        direction_frame.grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

        self.auto_y_ccw_radio = ttk.Radiobutton(
            direction_frame,
            text="Counterclockwise",
            variable=self.auto_y_direction_var,
            value="counterclockwise",
            command=self._on_auto_y_direction_changed,
        )
        self.auto_y_ccw_radio.grid(row=0, column=0, sticky="w")

        self.auto_y_cw_radio = ttk.Radiobutton(
            direction_frame,
            text="Clockwise",
            variable=self.auto_y_direction_var,
            value="clockwise",
            command=self._on_auto_y_direction_changed,
        )
        self.auto_y_cw_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(
            frame,
            text=(
                "Uses the same axis length as X. Y updates whenever Origin, "
                "X, or the selected direction changes."
            ),
            style="Muted.TLabel",
            wraplength=340,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _build_point_sections(self) -> None:
        row = 2
        for point_name in POINT_NAMES:
            frame = ttk.LabelFrame(
                self.inspector,
                text=POINT_LABELS[point_name],
                style="Section.TLabelframe",
            )
            frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            frame.columnconfigure(1, weight=1)
            frame.columnconfigure(2, weight=1)

            # Use a classic Tk button here instead of ttk.Button. On Windows,
            # native ttk themes may ignore custom background colors, making an
            # active selection mode difficult to see. A Tk button provides
            # reliable foreground/background feedback across themes.
            select_button = tk.Button(
                frame,
                text=f"Select {POINT_LABELS[point_name]}",
                command=lambda p=point_name: self.begin_point_selection(p),
                font=("Segoe UI", 9),
                relief=tk.RAISED,
                borderwidth=1,
                padx=8,
                pady=5,
                cursor="hand2",
                highlightthickness=0,
            )
            select_button.grid(
                row=0,
                column=0,
                columnspan=3,
                sticky="ew",
                pady=(0, 8),
            )
            setattr(self, f"{point_name}_select_button", select_button)

            ttk.Label(frame, text="").grid(row=1, column=0)
            ttk.Label(frame, text="X", anchor="center").grid(
                row=1, column=1, sticky="ew"
            )
            ttk.Label(frame, text="Y", anchor="center").grid(
                row=1, column=2, sticky="ew"
            )

            ttk.Label(frame, text="Pixel").grid(row=2, column=0, sticky="w")
            pixel_x_entry = ttk.Entry(
                frame,
                textvariable=self.point_vars[point_name]["pixel_x"],
                width=12,
            )
            pixel_x_entry.grid(row=2, column=1, sticky="ew", padx=(6, 3))
            pixel_y_entry = ttk.Entry(
                frame,
                textvariable=self.point_vars[point_name]["pixel_y"],
                width=12,
            )
            pixel_y_entry.grid(row=2, column=2, sticky="ew", padx=(3, 0))

            ttk.Label(frame, text="Real World").grid(
                row=3, column=0, sticky="w", pady=(6, 0)
            )
            world_x_entry = ttk.Entry(
                frame,
                textvariable=self.point_vars[point_name]["world_x"],
                width=12,
            )
            world_x_entry.grid(
                row=3, column=1, sticky="ew", padx=(6, 3), pady=(6, 0)
            )
            world_y_entry = ttk.Entry(
                frame,
                textvariable=self.point_vars[point_name]["world_y"],
                width=12,
            )
            world_y_entry.grid(
                row=3, column=2, sticky="ew", padx=(3, 0), pady=(6, 0)
            )

            for entry in (
                pixel_x_entry,
                pixel_y_entry,
                world_x_entry,
                world_y_entry,
            ):
                entry.bind("<Return>", self.commit_field_edits)
                entry.bind("<FocusOut>", self.commit_field_edits)

            row += 1

    def _build_metadata_section(self) -> None:
        frame = ttk.LabelFrame(
            self.inspector,
            text="Embedded Metadata",
            style="Section.TLabelframe",
        )
        frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text=(
                "Coordinate-system data is stored as JSON in the PNG iTXt "
                f'chunk "{METADATA_KEY}".'
            ),
            wraplength=360,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        self.json_preview_button = ttk.Button(
            frame,
            text="Preview JSON",
            command=self.preview_json,
        )
        self.json_preview_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    # ------------------------------------------------------------------
    # Event bindings
    # ------------------------------------------------------------------

    def _bind_events(self) -> None:
        self.image_canvas.bind("<Configure>", self.on_canvas_resize)
        self.image_canvas.bind("<Motion>", self.on_canvas_motion)
        self.image_canvas.bind("<Leave>", self.on_canvas_leave)
        self.image_canvas.bind("<Button-1>", self.on_canvas_click)
        # Use one application-wide wheel handler and route it by the current
        # pointer position. Tk on Windows commonly sends wheel events to the
        # keyboard-focused widget rather than the widget under the mouse.
        # A single binding also avoids local and global handlers competing.
        self.root.bind_all("<MouseWheel>", self._dispatch_mouse_wheel)
        self.root.bind_all("<Button-4>", self._dispatch_mouse_wheel)
        self.root.bind_all("<Button-5>", self._dispatch_mouse_wheel)
        self.image_canvas.bind("<Enter>", lambda event: self.image_canvas.focus_set())
        self.image_canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.image_canvas.bind("<B2-Motion>", self.on_pan_motion)
        self.image_canvas.bind("<ButtonRelease-2>", self.on_pan_end)
        self.image_canvas.bind("<Double-Button-1>", lambda event: self.zoom_100_percent())
        self.image_canvas.bind("<Double-Button-2>", lambda event: self.fit_image_to_window())

        self.system_listbox.bind("<<ListboxSelect>>", self.on_system_selected)
        self.system_name_entry.bind("<Return>", lambda event: self.apply_system_name())

        self.root.bind("<Escape>", self.cancel_point_selection)
        self.root.bind("<Control-o>", lambda event: self.browse_image())
        self.root.bind("<Control-s>", lambda event: self.save_metadata())
        self.root.bind("<Control-Shift-S>", lambda event: self.save_metadata_as())
        self.root.bind("<Control-Key-0>", lambda event: self.fit_image_to_window())
        self.root.bind("<Control-Key-1>", lambda event: self.zoom_100_percent())

        self.inspector_canvas.bind("<MouseWheel>", self._on_inspector_mousewheel)
        self.inspector_canvas.bind("<Button-4>", self._on_inspector_mousewheel)
        self.inspector_canvas.bind("<Button-5>", self._on_inspector_mousewheel)


    # ------------------------------------------------------------------
    # Image loading and metadata parsing
    # ------------------------------------------------------------------

    def browse_image(self) -> None:
        if not self._confirm_discard_unsaved_changes():
            return

        path = filedialog.askopenfilename(
            title="Select PNG Image",
            filetypes=[
                ("PNG images", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.load_image(Path(path))

    def load_image(self, path: Path) -> None:
        try:
            with Image.open(path) as opened:
                if opened.format != "PNG":
                    raise ValueError("The selected file is not a PNG image.")
                opened.load()
                self.source_image = opened.convert("RGBA")
                self._build_image_pyramid()
                self._invalidate_affine_cache()
                self.view_scale = None
                self.view_center_x = self.source_image.width / 2.0
                self.view_center_y = self.source_image.height / 2.0
                metadata = self._read_coordinate_metadata(opened)
        except Exception as exc:
            messagebox.showerror(
                "Open Image Failed",
                f"Could not open the image:\n\n{exc}",
            )
            return

        self.image_path = path
        self.file_label_var.set(path.name)
        self.coordinate_systems = metadata

        if not self.coordinate_systems:
            self.coordinate_systems = [new_coordinate_system("Coordinate System 1")]
            self.status_var.set(
                "Image loaded. A new coordinate system was created."
            )
        else:
            self.status_var.set(
                f"Loaded {len(self.coordinate_systems)} embedded coordinate "
                f"system{'s' if len(self.coordinate_systems) != 1 else ''}."
            )

        self.active_system_index = 0
        self.active_point_name = None
        self.dirty = False
        self._refresh_system_list()
        self._load_active_system_into_fields()
        self._schedule_preview_redraw()
        self._update_controls_enabled()

    def _build_image_pyramid(self) -> None:
        """Build progressively smaller source images for fast zoom rendering."""
        self.image_pyramid = []
        if self.source_image is None:
            return

        current = self.source_image
        self.image_pyramid.append(current)
        while min(current.size) > PYRAMID_MIN_DIMENSION:
            next_size = (
                max(1, current.width // 2),
                max(1, current.height // 2),
            )
            current = current.resize(next_size, Image.Resampling.BILINEAR)
            self.image_pyramid.append(current)

    def _select_pyramid_level(
        self,
        scale: float,
    ) -> tuple[Image.Image, float, float]:
        """Return a pyramid image and its exact X/Y source reduction factors.

        Pyramid dimensions are produced with integer division, so odd source
        dimensions are not always reduced by exactly ``2 ** level``. Using the
        actual width and height ratios prevents crop boxes from extending a
        fraction of a pixel beyond a pyramid image at its right or bottom edge.
        """
        assert self.source_image is not None

        if not self.image_pyramid:
            return self.source_image, 1.0, 1.0

        if scale >= 1.0:
            level = 0
        else:
            ideal_level = int(round(math.log2(1.0 / max(scale, 1e-12))))
            level = max(0, min(ideal_level, len(self.image_pyramid) - 1))

        pyramid_image = self.image_pyramid[level]
        reduction_x = self.source_image.width / pyramid_image.width
        reduction_y = self.source_image.height / pyramid_image.height
        return pyramid_image, reduction_x, reduction_y

    def _invalidate_affine_cache(self) -> None:
        self._affine_cache_key = None
        self._affine_cache_coefficients = None

    def _read_coordinate_metadata(
        self,
        image: Image.Image,
    ) -> list[dict[str, Any]]:
        try:
            return read_coordinate_metadata(image)
        except ValueError as exc:
            messagebox.showwarning("Metadata Warning", str(exc))
            return []

    # ------------------------------------------------------------------
    # Coordinate-system list management
    # ------------------------------------------------------------------

    def add_coordinate_system(self) -> None:
        if self.source_image is None:
            messagebox.showinfo("No Image", "Load an image first.")
            return

        self.commit_field_edits(show_errors=False)

        base_name = "Coordinate System"
        existing_names = {
            str(system.get("name", "")).casefold()
            for system in self.coordinate_systems
        }
        number = 1
        while f"{base_name} {number}".casefold() in existing_names:
            number += 1

        self.coordinate_systems.append(
            new_coordinate_system(f"{base_name} {number}")
        )
        self.active_system_index = len(self.coordinate_systems) - 1
        self.active_point_name = None
        self.dirty = True

        self._refresh_system_list()
        self._load_active_system_into_fields()
        self.redraw_preview()
        self._update_controls_enabled()
        self.status_var.set("Added a new coordinate system.")

    def delete_coordinate_system(self) -> None:
        system = self._active_system()
        if system is None:
            return

        if not messagebox.askyesno(
            "Delete Coordinate System",
            f'Delete "{system["name"]}"?',
        ):
            return

        assert self.active_system_index is not None
        del self.coordinate_systems[self.active_system_index]

        if self.coordinate_systems:
            self.active_system_index = min(
                self.active_system_index,
                len(self.coordinate_systems) - 1,
            )
        else:
            self.active_system_index = None

        self.active_point_name = None
        self.dirty = True
        self._refresh_system_list()
        self._load_active_system_into_fields()
        self.redraw_preview()
        self._update_controls_enabled()
        self.status_var.set("Coordinate system deleted.")

    def on_system_selected(self, event: tk.Event | None = None) -> None:
        selection = self.system_listbox.curselection()
        if not selection:
            return

        new_index = selection[0]
        if new_index == self.active_system_index:
            return

        if not self.commit_field_edits(show_errors=True):
            self._select_active_listbox_row()
            return

        self.active_system_index = new_index
        self._invalidate_affine_cache()
        self.active_point_name = None
        self._load_active_system_into_fields()
        self.redraw_preview()
        self._update_active_instruction()
        self._update_controls_enabled()

    def apply_system_name(self) -> None:
        system = self._active_system()
        if system is None:
            return

        name = self.system_name_var.get().strip()
        if not name:
            messagebox.showwarning(
                "Invalid Name",
                "Coordinate-system name cannot be blank.",
            )
            return

        system["name"] = name
        self.dirty = True
        self._refresh_system_list()
        self.status_var.set("Coordinate-system name updated.")

    def _refresh_system_list(self) -> None:
        self.system_listbox.delete(0, tk.END)
        for system in self.coordinate_systems:
            self.system_listbox.insert(tk.END, str(system["name"]))
        self._select_active_listbox_row()

    def _select_active_listbox_row(self) -> None:
        self.system_listbox.selection_clear(0, tk.END)
        if self.active_system_index is not None:
            self.system_listbox.selection_set(self.active_system_index)
            self.system_listbox.activate(self.active_system_index)
            self.system_listbox.see(self.active_system_index)

    def _active_system(self) -> dict[str, Any] | None:
        if self.active_system_index is None:
            return None
        if not 0 <= self.active_system_index < len(self.coordinate_systems):
            return None
        return self.coordinate_systems[self.active_system_index]

    # ------------------------------------------------------------------
    # Point selection and field editing
    # ------------------------------------------------------------------

    def begin_point_selection(self, point_name: str) -> None:
        if self.source_image is None or self._active_system() is None:
            return

        if not self.commit_field_edits(show_errors=True):
            return

        self.active_point_name = point_name
        self._update_active_instruction()
        self._update_point_button_styles()
        self.status_var.set(
            f"Click the image to set {POINT_LABELS[point_name]}."
        )
        self.image_canvas.focus_set()

    def cancel_point_selection(self, event: tk.Event | None = None) -> None:
        if self.active_point_name is not None:
            self.active_point_name = None
            self._update_active_instruction()
            self._update_point_button_styles()
            self.status_var.set("Point selection cancelled.")

    def on_canvas_click(self, event: tk.Event) -> None:
        if (
            self.source_image is None
            or self.active_point_name is None
            or not self.display_transform.contains_canvas_point(event.x, event.y)
        ):
            return

        image_x, image_y = self.display_transform.canvas_to_image(
            event.x,
            event.y,
        )
        pixel_x = int(round(image_x))
        pixel_y = int(round(image_y))

        pixel_x = max(0, min(pixel_x, self.source_image.width - 1))
        pixel_y = max(0, min(pixel_y, self.source_image.height - 1))

        system = self._active_system()
        if system is None:
            return

        point = system[self.active_point_name]
        point["pixel_x"] = float(pixel_x)
        point["pixel_y"] = float(pixel_y)

        if self.auto_y_perpendicular_var.get() and self.active_point_name in ("origin", "x_point"):
            self._derive_y_from_x(system)

        selected_label = POINT_LABELS[self.active_point_name]
        self.dirty = True
        self._invalidate_affine_cache()
        self._load_active_system_into_fields()
        self.redraw_preview()
        self.status_var.set(
            f"{selected_label} set to pixel ({pixel_x}, {pixel_y})."
        )

    def commit_field_edits(
        self,
        event: tk.Event | None = None,
        show_errors: bool = True,
    ) -> bool:
        if self._loading_fields:
            return True

        system = self._active_system()
        if system is None:
            return True

        updated = copy.deepcopy(system)

        for point_name in POINT_NAMES:
            for field_name in ("pixel_x", "pixel_y", "world_x", "world_y"):
                text = self.point_vars[point_name][field_name].get().strip()

                if field_name.startswith("pixel_") and text == "":
                    updated[point_name][field_name] = None
                    continue

                try:
                    value = float(text)
                except ValueError:
                    if show_errors:
                        messagebox.showwarning(
                            "Invalid Coordinate",
                            f"{POINT_LABELS[point_name]} "
                            f"{self._friendly_field_name(field_name)} must be numeric.",
                        )
                    return False

                if field_name.startswith("pixel_"):
                    if self.source_image is not None:
                        maximum = (
                            self.source_image.width - 1
                            if field_name == "pixel_x"
                            else self.source_image.height - 1
                        )
                        if not 0 <= value <= maximum:
                            if show_errors:
                                messagebox.showwarning(
                                    "Pixel Outside Image",
                                    f"{POINT_LABELS[point_name]} "
                                    f"{self._friendly_field_name(field_name)} "
                                    f"must be between 0 and {maximum}.",
                                )
                            return False

                updated[point_name][field_name] = value

        if self.auto_y_perpendicular_var.get():
            self._derive_y_from_x(updated)

        if updated != system:
            self.coordinate_systems[self.active_system_index] = updated
            self._invalidate_affine_cache()
            self.dirty = True
            self._load_active_system_into_fields()
            self.redraw_preview()

        return True

    def _on_auto_y_toggled(self) -> None:
        if self.auto_y_perpendicular_var.get():
            system = self._active_system()
            if system is not None:
                if self.active_point_name == "y_point":
                    self.active_point_name = None
                if self._derive_y_from_x(system):
                    self.dirty = True
                    self._invalidate_affine_cache()
                    self._load_active_system_into_fields()
                    self.redraw_preview()
                    direction = self.auto_y_direction_var.get()
                    self.status_var.set(
                        f"Y axis automatically defined {direction} from X."
                    )
                else:
                    self.status_var.set(
                        "Define Origin and X Point to automatically create Y."
                    )
        self._update_controls_enabled()

    def _on_auto_y_direction_changed(self) -> None:
        """Recalculate the automatic Y point after its direction changes."""
        if not self.auto_y_perpendicular_var.get():
            return

        system = self._active_system()
        if system is None:
            return

        if self._derive_y_from_x(system):
            self.dirty = True
            self._invalidate_affine_cache()
            self._load_active_system_into_fields()
            self.redraw_preview()

        direction = self.auto_y_direction_var.get()
        self.status_var.set(
            f"Y axis automatically defined {direction} from X."
        )

    def _derive_y_from_x(self, system: dict[str, Any]) -> bool:
        """Derive Y perpendicular to X in the selected direction.

        Image pixel coordinates increase downward, while world coordinates use
        the conventional Cartesian convention where Y increases upward. The
        formulas below therefore differ between pixel and world space so that
        the selected clockwise/counterclockwise direction looks and behaves the
        same in both coordinate systems.
        """
        origin = system["origin"]
        x_point = system["x_point"]
        y_point = system["y_point"]
        clockwise = self.auto_y_direction_var.get() == "clockwise"

        pixel_values = (
            origin.get("pixel_x"), origin.get("pixel_y"),
            x_point.get("pixel_x"), x_point.get("pixel_y"),
        )
        changed = False

        if all(value is not None for value in pixel_values):
            ox, oy, xx, xy = map(float, pixel_values)
            dx = xx - ox
            dy = xy - oy
            if math.hypot(dx, dy) > 1e-12:
                if clockwise:
                    rotated_dx = -dy
                    rotated_dy = dx
                else:
                    rotated_dx = dy
                    rotated_dy = -dx

                new_px = ox + rotated_dx
                new_py = oy + rotated_dy
                if self.source_image is not None:
                    new_px = max(0.0, min(new_px, self.source_image.width - 1.0))
                    new_py = max(0.0, min(new_py, self.source_image.height - 1.0))
                if y_point.get("pixel_x") != new_px or y_point.get("pixel_y") != new_py:
                    y_point["pixel_x"] = new_px
                    y_point["pixel_y"] = new_py
                    changed = True

        world_values = (
            origin.get("world_x"), origin.get("world_y"),
            x_point.get("world_x"), x_point.get("world_y"),
        )
        if all(value is not None for value in world_values):
            ox, oy, xx, xy = map(float, world_values)
            dx = xx - ox
            dy = xy - oy
            if math.hypot(dx, dy) > 1e-12:
                if clockwise:
                    rotated_dx = dy
                    rotated_dy = -dx
                else:
                    rotated_dx = -dy
                    rotated_dy = dx

                new_wx = ox + rotated_dx
                new_wy = oy + rotated_dy
                if y_point.get("world_x") != new_wx or y_point.get("world_y") != new_wy:
                    y_point["world_x"] = new_wx
                    y_point["world_y"] = new_wy
                    changed = True

        return changed

    @staticmethod
    def _friendly_field_name(field_name: str) -> str:
        return {
            "pixel_x": "pixel X",
            "pixel_y": "pixel Y",
            "world_x": "real-world X",
            "world_y": "real-world Y",
        }[field_name]

    def _load_active_system_into_fields(self) -> None:
        self._loading_fields = True
        try:
            system = self._active_system()
            if system is None:
                self.system_name_var.set("")
                for point_name in POINT_NAMES:
                    for variable in self.point_vars[point_name].values():
                        variable.set("")
                return

            self.system_name_var.set(str(system["name"]))
            for point_name in POINT_NAMES:
                point = system[point_name]
                for field_name, variable in self.point_vars[point_name].items():
                    variable.set(self._format_field_value(point.get(field_name)))
        finally:
            self._loading_fields = False

    @staticmethod
    def _format_field_value(value: Any) -> str:
        if value is None:
            return ""
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.9g}"

    # ------------------------------------------------------------------
    # Preview rendering and cursor coordinate display
    # ------------------------------------------------------------------

    def on_canvas_resize(self, event: tk.Event) -> None:
        if self.source_image is None:
            self.image_canvas.coords(
                "empty_text",
                event.width // 2,
                event.height // 2,
            )
            return
        self._schedule_preview_redraw()

    def _schedule_preview_redraw(self, delay_ms: int = RESIZE_DEBOUNCE_MS) -> None:
        """Debounce non-interactive redraws such as window resizing."""
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(delay_ms, self.redraw_preview)

    def _schedule_interaction_redraw(self) -> None:
        """Throttle zoom/pan rendering without discarding input events.

        Unlike a debounce, this does not restart the timer for every wheel or
        pan event. All incoming events immediately update the pending view
        state, while rendering occurs at most once per short UI interval.
        """
        if self.resize_job is None:
            self.resize_job = self.root.after(
                INTERACTION_REDRAW_MS,
                self.redraw_preview,
            )

    def redraw_preview(self) -> None:
        self.resize_job = None

        if self.source_image is None:
            if self.preview_image_item is not None:
                self.image_canvas.itemconfigure(self.preview_image_item, state=tk.HIDDEN)
            self.image_canvas.delete("coordinate_overlay")
            if not self.image_canvas.find_withtag("empty_text"):
                self.image_canvas.create_text(
                    self.image_canvas.winfo_width() // 2,
                    self.image_canvas.winfo_height() // 2,
                    text="Browse to load a PNG image",
                    fill=EMPTY_TEXT_COLOR,
                    tags=("empty_text",),
                    anchor="center",
                    font=("Segoe UI", 16),
                )
            return

        self.image_canvas.delete("empty_text")
        canvas_width = max(1, self.image_canvas.winfo_width())
        canvas_height = max(1, self.image_canvas.winfo_height())

        source_width, source_height = self.source_image.size
        fit_scale = min(canvas_width / source_width, canvas_height / source_height)
        if self.view_scale is None:
            self.view_scale = max(MIN_ZOOM, min(fit_scale, MAX_ZOOM))
            self.view_center_x = source_width / 2.0
            self.view_center_y = source_height / 2.0

        scale = max(MIN_ZOOM, min(self.view_scale, MAX_ZOOM))
        display_width = max(1, int(round(source_width * scale)))
        display_height = max(1, int(round(source_height * scale)))
        offset_x = canvas_width / 2.0 - self.view_center_x * scale
        offset_y = canvas_height / 2.0 - self.view_center_y * scale

        self.display_transform = DisplayTransform(
            scale=scale,
            offset_x=offset_x,
            offset_y=offset_y,
            display_width=display_width,
            display_height=display_height,
        )

        visible_left = max(0.0, -offset_x / scale)
        visible_top = max(0.0, -offset_y / scale)
        visible_right = min(float(source_width), (canvas_width - offset_x) / scale)
        visible_bottom = min(float(source_height), (canvas_height - offset_y) / scale)

        if visible_right > visible_left and visible_bottom > visible_top:
            pyramid_image, reduction_x, reduction_y = self._select_pyramid_level(scale)

            # Convert the visible source-image rectangle into the selected
            # pyramid level using its exact X/Y reduction ratios. Clamp every
            # edge after conversion because floating-point arithmetic can
            # otherwise produce values such as width + 1e-12, which Pillow
            # rejects with "box can't exceed original image size".
            box_left = max(0.0, min(visible_left / reduction_x, float(pyramid_image.width)))
            box_top = max(0.0, min(visible_top / reduction_y, float(pyramid_image.height)))
            box_right = max(box_left, min(visible_right / reduction_x, float(pyramid_image.width)))
            box_bottom = max(box_top, min(visible_bottom / reduction_y, float(pyramid_image.height)))
            box = (box_left, box_top, box_right, box_bottom)
            render_width = max(1, int(math.ceil((visible_right - visible_left) * scale)))
            render_height = max(1, int(math.ceil((visible_bottom - visible_top) * scale)))

            if self.interaction_active:
                resample = Image.Resampling.NEAREST
            else:
                effective_scale = min(
                    scale * reduction_x,
                    scale * reduction_y,
                )
                resample = (
                    Image.Resampling.NEAREST
                    if effective_scale >= 1.0
                    else Image.Resampling.BILINEAR
                )

            rendered = pyramid_image.resize(
                (render_width, render_height),
                resample=resample,
                box=box,
            )
            self.preview_photo = ImageTk.PhotoImage(rendered)
            render_x = offset_x + visible_left * scale
            render_y = offset_y + visible_top * scale

            if self.preview_image_item is None:
                self.preview_image_item = self.image_canvas.create_image(
                    render_x,
                    render_y,
                    image=self.preview_photo,
                    anchor=tk.NW,
                    tags=("preview_image",),
                )
            else:
                self.image_canvas.coords(self.preview_image_item, render_x, render_y)
                self.image_canvas.itemconfigure(
                    self.preview_image_item,
                    image=self.preview_photo,
                    state=tk.NORMAL,
                )
        else:
            self.preview_photo = None
            if self.preview_image_item is not None:
                self.image_canvas.itemconfigure(self.preview_image_item, state=tk.HIDDEN)

        self.image_canvas.delete("coordinate_overlay")
        self._draw_all_coordinate_systems()
        if self.preview_image_item is not None:
            self.image_canvas.tag_lower(self.preview_image_item)
        if self.cursor_canvas_position is not None:
            self._draw_cursor_crosshair(*self.cursor_canvas_position)
        self.zoom_var.set(f"Zoom: {scale * 100:.0f}%")

    def _begin_interaction_rendering(self) -> None:
        self.interaction_active = True
        if self.interaction_settle_job is not None:
            self.root.after_cancel(self.interaction_settle_job)
        self.interaction_settle_job = self.root.after(
            INTERACTION_SETTLE_MS,
            self._finish_interaction_rendering,
        )

    def _finish_interaction_rendering(self) -> None:
        self.interaction_settle_job = None
        self.interaction_active = False
        self.redraw_preview()

    def fit_image_to_window(self) -> None:
        """Fit once using the current canvas size, then preserve that scale."""
        if self.source_image is None:
            return

        canvas_width = max(1, self.image_canvas.winfo_width())
        canvas_height = max(1, self.image_canvas.winfo_height())
        source_width, source_height = self.source_image.size
        self.view_scale = max(
            MIN_ZOOM,
            min(
                canvas_width / source_width,
                canvas_height / source_height,
                MAX_ZOOM,
            ),
        )
        self.view_center_x = source_width / 2.0
        self.view_center_y = source_height / 2.0
        self.redraw_preview()
        self.status_var.set("Image fitted to the preview window.")

    def zoom_100_percent(self) -> None:
        """Display one source-image pixel as one canvas pixel."""
        if self.source_image is None:
            return
        self.view_scale = 1.0
        self.redraw_preview()
        self.status_var.set("Zoom set to 100%.")

    def _zoom_about_canvas_point(self, new_scale: float, canvas_x: float, canvas_y: float) -> None:
        """Apply an absolute zoom while keeping the pointed image pixel fixed."""
        if self.source_image is None:
            return

        # Use the pending view state rather than display_transform. The latter
        # describes the most recently rendered frame and can lag several wheel
        # events behind. Using view_scale/view_center makes every wheel notch
        # accumulate immediately, even before the next image render completes.
        old_scale = max(
            self.view_scale if self.view_scale is not None else self.display_transform.scale,
            1e-12,
        )
        canvas_width = max(1, self.image_canvas.winfo_width())
        canvas_height = max(1, self.image_canvas.winfo_height())
        image_x = self.view_center_x + (canvas_x - canvas_width / 2.0) / old_scale
        image_y = self.view_center_y + (canvas_y - canvas_height / 2.0) / old_scale
        new_scale = max(MIN_ZOOM, min(float(new_scale), MAX_ZOOM))

        self.view_center_x = image_x - (canvas_x - canvas_width / 2.0) / new_scale
        self.view_center_y = image_y - (canvas_y - canvas_height / 2.0) / new_scale
        self.view_scale = new_scale
        self._begin_interaction_rendering()
        self._schedule_interaction_redraw()

    def zoom_in(self) -> None:
        """Zoom in around the center of the preview."""
        if self.source_image is None:
            return
        x = self.image_canvas.winfo_width() / 2.0
        y = self.image_canvas.winfo_height() / 2.0
        self._zoom_about_canvas_point(self.display_transform.scale * ZOOM_STEP, x, y)

    def zoom_out(self) -> None:
        """Zoom out around the center of the preview."""
        if self.source_image is None:
            return
        x = self.image_canvas.winfo_width() / 2.0
        y = self.image_canvas.winfo_height() / 2.0
        self._zoom_about_canvas_point(self.display_transform.scale / ZOOM_STEP, x, y)

    def on_mouse_wheel(self, event: tk.Event) -> str:
        """Zoom around the image location currently beneath the cursor."""
        if self.source_image is None:
            return "break"

        # Windows/macOS use event.delta; X11 commonly uses buttons 4 and 5.
        direction = 0
        if getattr(event, "delta", 0):
            direction = 1 if event.delta > 0 else -1
        elif getattr(event, "num", None) == 4:
            direction = 1
        elif getattr(event, "num", None) == 5:
            direction = -1
        if direction == 0:
            return "break"

        old_scale = (
            self.view_scale
            if self.view_scale is not None
            else self.display_transform.scale
        )
        if old_scale <= 0:
            return "break"

        step = FAST_ZOOM_STEP if (getattr(event, "state", 0) & 0x0001) else ZOOM_STEP
        new_scale = old_scale * (step if direction > 0 else 1.0 / step)
        self._zoom_about_canvas_point(new_scale, event.x, event.y)
        return "break"

    def on_pan_start(self, event: tk.Event) -> str:
        if self.source_image is None:
            return "break"
        self.pan_start_canvas = (event.x, event.y)
        self.pan_start_center = (self.view_center_x, self.view_center_y)
        self.image_canvas.configure(cursor="fleur")
        return "break"

    def on_pan_motion(self, event: tk.Event) -> str:
        if (
            self.source_image is None
            or self.pan_start_canvas is None
            or self.pan_start_center is None
        ):
            return "break"
        scale = max(self.display_transform.scale, 1e-12)
        dx = event.x - self.pan_start_canvas[0]
        dy = event.y - self.pan_start_canvas[1]
        self.view_center_x = self.pan_start_center[0] - dx / scale
        self.view_center_y = self.pan_start_center[1] - dy / scale
        if self.view_scale is None:
            self.view_scale = scale
        self._begin_interaction_rendering()
        self._schedule_interaction_redraw()
        return "break"

    def on_pan_end(self, event: tk.Event) -> str:
        self.pan_start_canvas = None
        self.pan_start_center = None
        self.image_canvas.configure(cursor="crosshair")
        return "break"

    def _draw_all_coordinate_systems(self) -> None:
        for index, system in enumerate(self.coordinate_systems):
            is_active = index == self.active_system_index
            self._draw_coordinate_system(system, is_active)

    def _draw_coordinate_system(
        self,
        system: dict[str, Any],
        is_active: bool,
    ) -> None:
        colors = ACTIVE_COLORS if is_active else INACTIVE_COLORS
        line_width = 3 if is_active else 2
        dash = None if is_active else (5, 4)

        canvas_points: dict[str, tuple[float, float] | None] = {}
        for point_name in POINT_NAMES:
            point = system[point_name]
            pixel_x = point.get("pixel_x")
            pixel_y = point.get("pixel_y")
            if pixel_x is None or pixel_y is None:
                canvas_points[point_name] = None
            else:
                canvas_points[point_name] = (
                    self.display_transform.image_to_canvas(
                        float(pixel_x),
                        float(pixel_y),
                    )
                )

        origin = canvas_points["origin"]
        x_point = canvas_points["x_point"]
        y_point = canvas_points["y_point"]

        if origin is not None and x_point is not None:
            self.image_canvas.create_line(
                *origin,
                *x_point,
                fill=colors["x_point"],
                width=line_width,
                dash=dash,
                arrow=tk.LAST,
                arrowshape=(10, 12, 5),
                tags=("coordinate_overlay",),
            )

        if origin is not None and y_point is not None:
            self.image_canvas.create_line(
                *origin,
                *y_point,
                fill=colors["y_point"],
                width=line_width,
                dash=dash,
                arrow=tk.LAST,
                arrowshape=(10, 12, 5),
                tags=("coordinate_overlay",),
            )

        for point_name, canvas_point in canvas_points.items():
            if canvas_point is None:
                continue
            self._draw_marker(
                canvas_point[0],
                canvas_point[1],
                point_name,
                str(system["name"]),
                colors[point_name],
                is_active,
            )

    def _draw_marker(
        self,
        x: float,
        y: float,
        point_name: str,
        system_name: str,
        color: str,
        is_active: bool,
    ) -> None:
        radius = MARKER_RADIUS + (1 if is_active else 0)
        self.image_canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill=color,
            outline="white" if is_active else color,
            width=2 if is_active else 1,
            tags=("coordinate_overlay",),
        )
        self.image_canvas.create_line(
            x - radius - 4,
            y,
            x + radius + 4,
            y,
            fill=color,
            width=2,
            tags=("coordinate_overlay",),
        )
        self.image_canvas.create_line(
            x,
            y - radius - 4,
            x,
            y + radius + 4,
            fill=color,
            width=2,
            tags=("coordinate_overlay",),
        )

        if is_active:
            label = (
                f"{system_name}: "
                f"{'O' if point_name == 'origin' else 'X' if point_name == 'x_point' else 'Y'}"
            )
            self.image_canvas.create_text(
                x + radius + 6,
                y - radius - 4,
                text=label,
                fill="white",
                anchor="sw",
                font=("Segoe UI Semibold", 9),
                tags=("coordinate_overlay",),
            )

    def on_canvas_motion(self, event: tk.Event) -> None:
        if (
            self.source_image is None
            or not self.display_transform.contains_canvas_point(event.x, event.y)
        ):
            self.cursor_pixel_var.set("Pixel: —")
            self.cursor_world_var.set("World: —")
            self.cursor_canvas_position = None
            self.image_canvas.delete("cursor_crosshair")
            return

        self.cursor_canvas_position = (float(event.x), float(event.y))
        self._draw_cursor_crosshair(event.x, event.y)

        image_x, image_y = self.display_transform.canvas_to_image(
            event.x,
            event.y,
        )
        pixel_x = max(
            0,
            min(int(math.floor(image_x)), self.source_image.width - 1),
        )
        pixel_y = max(
            0,
            min(int(math.floor(image_y)), self.source_image.height - 1),
        )
        self.cursor_pixel_var.set(f"Pixel: X={pixel_x}, Y={pixel_y}")

        world = self._pixel_to_world_for_active_system(image_x, image_y)
        if world is None:
            self.cursor_world_var.set("World: —")
        else:
            self.cursor_world_var.set(
                f"World: X={world[0]:.4f}, Y={world[1]:.4f}"
            )

    def on_canvas_leave(self, event: tk.Event | None = None) -> None:
        self.cursor_pixel_var.set("Pixel: —")
        self.cursor_world_var.set("World: —")
        self.cursor_canvas_position = None
        self.image_canvas.delete("cursor_crosshair")

    def _draw_cursor_crosshair(self, canvas_x: float, canvas_y: float) -> None:
        self.image_canvas.delete("cursor_crosshair")
        if self.source_image is None:
            return
        if not self.display_transform.contains_canvas_point(canvas_x, canvas_y):
            return

        left = max(0.0, self.display_transform.offset_x)
        top = max(0.0, self.display_transform.offset_y)
        right = min(
            float(self.image_canvas.winfo_width()),
            self.display_transform.offset_x + self.display_transform.display_width,
        )
        bottom = min(
            float(self.image_canvas.winfo_height()),
            self.display_transform.offset_y + self.display_transform.display_height,
        )

        self.image_canvas.create_line(
            left, canvas_y, right, canvas_y,
            fill="#f8fafc", width=1, dash=(4, 4),
            tags=("cursor_crosshair",),
        )
        self.image_canvas.create_line(
            canvas_x, top, canvas_x, bottom,
            fill="#f8fafc", width=1, dash=(4, 4),
            tags=("cursor_crosshair",),
        )
        self.image_canvas.tag_raise("cursor_crosshair")

    def _pixel_to_world_for_active_system(
        self,
        pixel_x: float,
        pixel_y: float,
    ) -> tuple[float, float] | None:
        """Convert a pixel using cached affine coefficients for the active system."""
        system = self._active_system()
        if system is None:
            return None

        cache_key = (self.active_system_index, *affine_cache_key(system))
        if cache_key != self._affine_cache_key:
            self._affine_cache_key = cache_key
            self._affine_cache_coefficients = None

        result, coefficients = pixel_to_world(
            system,
            pixel_x,
            pixel_y,
            coefficients=self._affine_cache_coefficients,
        )
        self._affine_cache_coefficients = coefficients
        return result

    # ------------------------------------------------------------------
    # PNG metadata writing
    # ------------------------------------------------------------------

    def _build_metadata_payload(self) -> dict[str, Any]:
        width = self.source_image.width if self.source_image else None
        height = self.source_image.height if self.source_image else None
        return build_metadata_payload(self.coordinate_systems, width, height)

    def save_metadata(self) -> None:
        if self.image_path is None:
            messagebox.showinfo("No Image", "Load an image first.")
            return
        if not self.commit_field_edits(show_errors=True):
            return
        self._write_png_with_metadata(self.image_path)

    def save_metadata_as(self) -> None:
        if self.image_path is None:
            messagebox.showinfo("No Image", "Load an image first.")
            return
        if not self.commit_field_edits(show_errors=True):
            return

        output_path = filedialog.asksaveasfilename(
            title="Save PNG With Coordinate Metadata",
            initialdir=str(self.image_path.parent),
            initialfile=self.image_path.name,
            defaultextension=".png",
            filetypes=[("PNG images", "*.png")],
        )
        if output_path:
            self._write_png_with_metadata(Path(output_path))

    def _write_png_with_metadata(self, output_path: Path) -> None:
        if self.image_path is None:
            return

        try:
            write_png_with_metadata(
                self.image_path,
                output_path,
                self._build_metadata_payload(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Save Failed",
                f"Could not save the PNG metadata:\n\n{exc}",
            )
            return

        self.image_path = output_path.resolve()
        self.file_label_var.set(self.image_path.name)
        self.dirty = False
        self.status_var.set(
            f"Saved {len(self.coordinate_systems)} coordinate "
            f"system{'s' if len(self.coordinate_systems) != 1 else ''} "
            f"to {self.image_path.name}."
        )

    def preview_json(self) -> None:
        if self.source_image is None:
            return
        if not self.commit_field_edits(show_errors=True):
            return

        window = tk.Toplevel(self.root)
        window.title("Coordinate Metadata JSON")
        window.geometry("760x600")
        window.minsize(520, 360)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        text = tk.Text(
            window,
            wrap="none",
            font=("Cascadia Mono", 10),
            undo=False,
        )
        vertical = ttk.Scrollbar(
            window,
            orient="vertical",
            command=text.yview,
        )
        horizontal = ttk.Scrollbar(
            window,
            orient="horizontal",
            command=text.xview,
        )
        text.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        text.insert(
            "1.0",
            json.dumps(
                self._build_metadata_payload(),
                indent=2,
                ensure_ascii=False,
            ),
        )
        text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Inspector behavior and general UI state
    # ------------------------------------------------------------------

    def _update_controls_enabled(self) -> None:
        image_loaded = self.source_image is not None
        system_loaded = self._active_system() is not None

        self.save_button.configure(
            state=tk.NORMAL if image_loaded else tk.DISABLED
        )
        self.save_as_button.configure(
            state=tk.NORMAL if image_loaded else tk.DISABLED
        )
        self.add_system_button.configure(
            state=tk.NORMAL if image_loaded else tk.DISABLED
        )
        self.delete_system_button.configure(
            state=tk.NORMAL if system_loaded else tk.DISABLED
        )
        self.rename_button.configure(
            state=tk.NORMAL if system_loaded else tk.DISABLED
        )
        self.json_preview_button.configure(
            state=tk.NORMAL if image_loaded else tk.DISABLED
        )
        self.system_name_entry.configure(
            state=tk.NORMAL if system_loaded else tk.DISABLED
        )

        self.auto_y_checkbox.configure(
            state=tk.NORMAL if system_loaded else tk.DISABLED
        )

        direction_enabled = system_loaded and self.auto_y_perpendicular_var.get()
        direction_state = tk.NORMAL if direction_enabled else tk.DISABLED
        self.auto_y_ccw_radio.configure(state=direction_state)
        self.auto_y_cw_radio.configure(state=direction_state)

        for point_name in POINT_NAMES:
            button = getattr(self, f"{point_name}_select_button")
            enabled = system_loaded and not (
                point_name == "y_point" and self.auto_y_perpendicular_var.get()
            )
            button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

        self._update_point_button_styles()
        self._update_active_instruction()

    def _update_point_button_styles(self) -> None:
        """Give point-selection mode unmistakable visual feedback.

        The point buttons are classic Tk buttons rather than ttk buttons so
        their colors remain dependable under Windows native and sv_ttk themes.
        """
        normal_background = "#3b3b3b"
        normal_foreground = "#f3f4f6"
        active_background = "#d97706"
        active_foreground = "#ffffff"
        disabled_background = "#2b2b2b"
        disabled_foreground = "#7f8792"

        for point_name in POINT_NAMES:
            button = getattr(self, f"{point_name}_select_button")
            is_active = point_name == self.active_point_name
            is_auto_y = (
                point_name == "y_point"
                and self.auto_y_perpendicular_var.get()
            )
            is_disabled = str(button.cget("state")) == tk.DISABLED

            if is_disabled:
                background = disabled_background
                foreground = disabled_foreground
                relief = tk.FLAT
            elif is_active:
                background = active_background
                foreground = active_foreground
                relief = tk.SUNKEN
            else:
                background = normal_background
                foreground = normal_foreground
                relief = tk.RAISED

            button.configure(
                text=(
                    "Y Auto-Defined"
                    if is_auto_y
                    else f"Select {POINT_LABELS[point_name]}"
                ),
                background=background,
                foreground=foreground,
                activebackground=(
                    "#f59e0b" if is_active else "#4b5563"
                ),
                activeforeground="#ffffff",
                disabledforeground=disabled_foreground,
                relief=relief,
            )

    def _update_active_instruction(self) -> None:
        if self.source_image is None:
            self.active_instruction_var.set("Browse to load a PNG image.")
        elif self._active_system() is None:
            self.active_instruction_var.set(
                "Add a coordinate system to begin."
            )
        elif self.active_point_name is None:
            self.active_instruction_var.set(
                "Choose Origin, X Point, or Y Point, then click the image."
            )
        else:
            self.active_instruction_var.set(
                f"Selecting {POINT_LABELS[self.active_point_name]} — "
                "click anywhere inside the image."
            )

    def _on_inspector_canvas_resize(self, event: tk.Event) -> None:
        self.inspector_canvas.itemconfigure(
            self.inspector_window,
            width=event.width,
        )
        self._sync_inspector_scroll_state()

    def _sync_inspector_scroll_state(self) -> None:
        self.inspector.update_idletasks()
        bbox = self.inspector_canvas.bbox("all")
        if bbox is None:
            self.inspector_scrollbar.grid_remove()
            return

        content_height = bbox[3] - bbox[1]
        viewport_height = max(1, self.inspector_canvas.winfo_height())
        if content_height > viewport_height + 1:
            self.inspector_canvas.configure(scrollregion=bbox)
            self.inspector_scrollbar.grid()
        else:
            self.inspector_scrollbar.grid_remove()
            self.inspector_canvas.yview_moveto(0)
            self.inspector_canvas.configure(
                scrollregion=(
                    0,
                    0,
                    max(1, self.inspector_canvas.winfo_width()),
                    viewport_height,
                )
            )

    def _widget_is_descendant(self, widget: tk.Misc, ancestor: tk.Misc) -> bool:
        """Return True when *widget* is *ancestor* or one of its children."""
        current: tk.Misc | None = widget
        while current is not None:
            if current == ancestor:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                break
            try:
                current = current.nametowidget(parent_name)
            except KeyError:
                break
        return False

    def _dispatch_mouse_wheel(self, event: tk.Event) -> str | None:
        """Route wheel input according to the widget beneath the pointer.

        Using the pointer position instead of keyboard focus makes image zoom
        work even after the user has edited an Entry in the inspector.
        """
        try:
            pointer_x = self.root.winfo_pointerx()
            pointer_y = self.root.winfo_pointery()
            widget = self.root.winfo_containing(pointer_x, pointer_y)
        except tk.TclError:
            widget = None

        if widget is None:
            return None

        if self._widget_is_descendant(widget, self.image_canvas):
            canvas_x = self.image_canvas.winfo_pointerx() - self.image_canvas.winfo_rootx()
            canvas_y = self.image_canvas.winfo_pointery() - self.image_canvas.winfo_rooty()

            # The globally received event may identify a child or toplevel
            # widget.  Supply canvas-relative coordinates to the zoom routine.
            event.x = canvas_x
            event.y = canvas_y
            return self.on_mouse_wheel(event)

        if self._widget_is_descendant(widget, self.inspector_canvas):
            return self._on_inspector_mousewheel(event)

        return None

    def _on_inspector_mousewheel(self, event: tk.Event) -> str:
        if self.root.focus_get() is not None and isinstance(
            self.root.focus_get(),
            (tk.Entry, ttk.Entry, tk.Text),
        ):
            return "break"

        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            raw_delta = getattr(event, "delta", 0)
            delta = -1 * int(raw_delta / 120)
            if delta == 0 and raw_delta:
                delta = -1 if raw_delta > 0 else 1

        if delta:
            self.inspector_canvas.yview_scroll(delta, "units")
        return "break"

    # ------------------------------------------------------------------
    # Unsaved-change handling
    # ------------------------------------------------------------------

    def _confirm_discard_unsaved_changes(self) -> bool:
        if not self.dirty:
            return True

        answer = messagebox.askyesnocancel(
            "Unsaved Changes",
            "Save the current coordinate metadata before continuing?",
        )
        if answer is None:
            return False
        if answer:
            self.save_metadata()
            return not self.dirty
        return True

    def on_close(self) -> None:
        if self._confirm_discard_unsaved_changes():
            self.root.destroy()

