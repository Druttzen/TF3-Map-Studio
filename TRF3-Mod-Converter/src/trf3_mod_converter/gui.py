"""Native desktop workflow. All mod I/O runs off the Tk event loop."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .converter import ModDescriptor, _source_root, convert_mod, prepare_mod


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("TRF3 Mod Converter")
        width = min(1080, root.winfo_screenwidth() - 60)
        height = min(820, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(900, width), min(620, height))
        root.configure(bg="#edf0f4")
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.loading = False
        self.preview: ModDescriptor | None = None
        self.report: dict | None = None
        self.variables = {key: tk.StringVar() for key in ("source", "destination", "name", "author", "mod_id", "revision", "summary")}
        self.overwrite = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose a source to begin")
        self.note = tk.StringVar(value="Inspect the mod before creating any output.")
        self.controls: list[ttk.Widget] = []
        self._styles()
        self._layout()
        for variable in self.variables.values():
            variable.trace_add("write", self._invalidate)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(80, self._poll)

    def _styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#edf0f4", foreground="#17283e")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Card.TLabel", background="#ffffff")
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground="#637184", background="#ffffff")
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 14), background="#ffffff")
        style.configure("TEntry", fieldbackground="#f6f8fb", padding=7)
        style.configure("TButton", padding=(12, 9), background="#e8edf3", borderwidth=0)
        style.map("TButton", background=[("active", "#dbe4ed")])
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 11), background="#16796c", foreground="white", padding=(18, 12))
        style.map("Accent.TButton", background=[("disabled", "#b0c5c0"), ("active", "#116659")], foreground=[("disabled", "#f4f6f5")])
        style.configure("TCheckbutton", background="white")
        style.configure("TProgressbar", background="#16796c", troughcolor="#edf0f4", borderwidth=0)

    def _layout(self) -> None:
        header = tk.Frame(self.root, bg="#17283e", padx=26, pady=22)
        header.pack(fill="x")
        tk.Label(header, text="TRF3", fg="#71dbbd", bg="#17283e", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        tk.Label(header, text="Give your mod a new home.", fg="white", bg="#17283e", font=("Segoe UI Semibold", 24)).pack(anchor="w")
        tk.Label(header, text=f"MOD CONVERTER  /  {__version__}     ·     Local files. Original sources preserved.", fg="#b7c5d6", bg="#17283e", font=("Segoe UI", 10)).pack(anchor="w", pady=(7, 0))
        body = ttk.Frame(self.root, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=6)
        body.rowconfigure(0, weight=1)

        left_host = ttk.Frame(body, style="Card.TFrame")
        left_host.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left_host.columnconfigure(0, weight=1)
        left_host.rowconfigure(0, weight=1)
        left_canvas = tk.Canvas(left_host, bg="white", highlightthickness=0, width=390)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scroll = ttk.Scrollbar(left_host, orient="vertical", command=left_canvas.yview)
        left_scroll.grid(row=0, column=1, sticky="ns")
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left = ttk.Frame(left_canvas, style="Card.TFrame", padding=20)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _event: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind("<Configure>", lambda event: left_canvas.itemconfigure(left_window, width=event.width))

        def scroll_fields(event):
            if str(event.widget).startswith(str(left_host)):
                left_canvas.yview_scroll(-int(event.delta / 120), "units")
                return "break"
        self.root.bind("<MouseWheel>", scroll_fields)
        self.root.bind("<Button-4>", lambda event: left_canvas.yview_scroll(-1, "units") if str(event.widget).startswith(str(left_host)) else None)
        self.root.bind("<Button-5>", lambda event: left_canvas.yview_scroll(1, "units") if str(event.widget).startswith(str(left_host)) else None)
        left.columnconfigure(0, weight=1)
        self._label(left, "01  Choose your files", "Heading.TLabel", 0)
        self._label(left, "Source folder or JSON / Lua metadata", "Card.TLabel", 1, (18, 4))
        self._entry(left, "source", 2)
        source_buttons = ttk.Frame(left, style="Card.TFrame")
        source_buttons.grid(row=3, column=0, sticky="w", pady=(6, 12))
        self._button(source_buttons, "Choose folder", self._browse_source_folder).pack(side="left", padx=(0, 6))
        self._button(source_buttons, "Metadata file", self._browse_source_file).pack(side="left")
        self._label(left, "Output folder", "Card.TLabel", 4, (0, 4))
        self._entry(left, "destination", 5)
        self._button(left, "Choose output folder", self._browse_destination).grid(row=6, column=0, sticky="w", pady=(6, 14))
        self._label(left, "02  Review metadata", "Heading.TLabel", 7, (0, 8))

        fields = ttk.Frame(left, style="Card.TFrame")
        fields.grid(row=8, column=0, sticky="ew")
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate((("name", "Display name"), ("mod_id", "Mod ID"), ("author", "Author override (optional)"), ("revision", "Revision"), ("summary", "Summary"))):
            ttk.Label(fields, text=label, style="Small.TLabel").grid(row=row * 2, column=0, columnspan=2, sticky="w", pady=(4, 3))
            entry = ttk.Entry(fields, textvariable=self.variables[key])
            entry.grid(row=row * 2 + 1, column=0, columnspan=2, sticky="ew", pady=(0, 3))
            self.controls.append(entry)
        replace = ttk.Checkbutton(left, text="Replace existing output and keep a backup", variable=self.overwrite)
        replace.grid(row=9, column=0, sticky="w", pady=(14, 0))
        self.controls.append(replace)

        right = ttk.Frame(body, style="Card.TFrame", padding=20)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self._label(right, "Conversion preview", "Heading.TLabel", 0)
        ttk.Label(right, textvariable=self.status, style="Card.TLabel", font=("Segoe UI Semibold", 11), wraplength=460).grid(row=1, column=0, sticky="w", pady=(18, 6))
        ttk.Label(right, textvariable=self.note, style="Small.TLabel", wraplength=460).grid(row=2, column=0, sticky="w", pady=(0, 12))
        preview_frame = ttk.Frame(right, style="Card.TFrame")
        preview_frame.grid(row=3, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.details = tk.Text(preview_frame, wrap="word", font=("Segoe UI", 10), bg="#f6f8fb", fg="#26384e", padx=14, pady=14, relief="flat", state="disabled")
        self.details.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=self.details.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=scrollbar.set)
        self._set_details("Your preview will appear here.\n\n1. Select a mod folder or metadata file.\n2. Choose a separate output folder.\n3. Preview, review, then convert.\n\nLegacy resources are copied to content. Scripts and assets may require manual migration and testing in Transport Fever 3.")
        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(14, 8))
        actions = ttk.Frame(right, style="Card.TFrame")
        actions.grid(row=5, column=0, sticky="ew")
        self.inspect_button = self._button(actions, "Preview mod", self.inspect)
        self.inspect_button.pack(side="left")
        self.convert_button = ttk.Button(actions, text="Convert mod", style="Accent.TButton", command=self.convert, state="disabled")
        self.convert_button.pack(side="right")
        self.open_button = ttk.Button(right, text="Open converted folder", command=self.open_output, state="disabled")
        self.open_button.grid(row=6, column=0, sticky="w", pady=(12, 0))
        self.port_button = self._button(right, "Port TF2 electric locomotive…", self.port_tf2)
        self.port_button.grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Label(body, text="Metadata and folder conversion · Game compatibility is confirmed by testing the mod in TF3.", foreground="#637184").grid(row=1, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _label(self, parent: ttk.Frame, text: str, style: str, row: int, pady=(0, 0)) -> None:
        ttk.Label(parent, text=text, style=style).grid(row=row, column=0, sticky="w", pady=pady)

    def _entry(self, parent: ttk.Frame, key: str, row: int) -> None:
        entry = ttk.Entry(parent, textvariable=self.variables[key])
        entry.grid(row=row, column=0, sticky="ew")
        self.controls.append(entry)

    def _button(self, parent: ttk.Frame, text: str, command) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        return button

    def _browse_source_folder(self) -> None:
        if path := filedialog.askdirectory(parent=self.root, title="Choose a source mod folder"):
            self._set_source(path)

    def _browse_source_file(self) -> None:
        if path := filedialog.askopenfilename(parent=self.root, title="Choose mod metadata", filetypes=[("Mod metadata", "*.json *.lua"), ("All files", "*.*")]):
            self._set_source(path)

    def _set_source(self, path: str) -> None:
        self.loading = True
        for key, variable in self.variables.items():
            if key not in {"source", "destination"}:
                variable.set("")
        self.variables["source"].set(path)
        source = Path(path)
        mod_root = _source_root(source)
        output_name = ModDescriptor._slugify_name(mod_root.name) + "_converted"
        self.variables["destination"].set(str(mod_root.with_name(output_name)))
        self.loading = False
        self._invalidate()

    def _browse_destination(self) -> None:
        if path := filedialog.askdirectory(parent=self.root, title="Choose output folder (or enter a new path in the field)"):
            self.variables["destination"].set(path)

    def _invalidate(self, *_args) -> None:
        if self.loading or self.busy:
            return
        self.preview = None
        self.report = None
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status.set("Preview needed")
        self.note.set("Preview the current choices to check metadata and required changes.")

    def _arguments(self) -> tuple[str, dict]:
        source = self.variables["source"].get().strip().strip('"')
        if not source:
            raise ValueError("Choose a source mod folder or metadata file.")
        overrides = {key: self.variables[key].get().strip() or None for key in ("name", "author", "mod_id", "summary")}
        revision = self.variables["revision"].get().strip()
        overrides["revision"] = int(revision) if revision else None
        return source, overrides

    def _run(self, operation, kind: str) -> None:
        self.busy = True
        self.report = None
        for control in self.controls:
            control.configure(state="disabled")
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.start(12)

        def worker() -> None:
            try:
                result = operation()
                self.events.put((kind, result))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def inspect(self) -> None:
        if self.busy:
            return
        try:
            source, overrides = self._arguments()
        except ValueError as error:
            self._error(str(error))
            return
        self.status.set("Reading mod metadata…")
        self.note.set("The mod's Lua code is parsed without being executed.")
        self._run(lambda: prepare_mod(source, **overrides), "preview")

    def convert(self) -> None:
        if self.busy or self.preview is None or self.preview.blockers:
            return
        try:
            source, overrides = self._arguments()
            destination = self.variables["destination"].get().strip().strip('"')
            if not destination:
                raise ValueError("Choose a separate output folder.")
        except ValueError as error:
            self._error(str(error))
            return
        overwrite = self.overwrite.get()
        last_update = 0.0

        def progress(message: str) -> None:
            nonlocal last_update
            now = time.monotonic()
            if now - last_update > 0.1:
                self.events.put(("progress", message))
                last_update = now
        self.status.set("Converting mod…")
        self.note.set("Copying to a temporary folder before finalizing the output.")
        self._run(lambda: convert_mod(source, destination, overwrite=overwrite, progress=progress, **overrides), "converted")

    def port_tf2(self) -> None:
        if self.busy:
            return
        try:
            source, overrides = self._arguments()
            destination = self.variables['destination'].get().strip().strip('"')
            if not destination or not overrides['name'] or not overrides['mod_id']:
                raise ValueError("Fill in a separate output folder, a display name (up to 32 characters) and a Mod ID first.")
            game = filedialog.askdirectory(parent=self.root,title="Choose installed Transport Fever 3 folder (contains base)")
            if not game:
                return
            repair_file = filedialog.askopenfilename(parent=self.root,title="Optional texture repair JSON — Cancel if none",
                                                     filetypes=[("Texture repairs", "*.json")])
            repairs = json.loads(Path(repair_file).read_text(encoding='utf-8')) if repair_file else None
            overwrite = self.overwrite.get()
        except (ValueError, OSError) as error:
            self._error(str(error))
            return
        from .tf2_vehicle_port import port_tf2_mod
        self.status.set("Porting TF2 locomotive resources…")
        self.note.set("Checking the installed TF3 formats. Unknown behavior or missing resources stop export.")
        self._run(lambda: port_tf2_mod(source,destination,tf3_game=game,name=overrides['name'],
                                      mod_id=overrides['mod_id'],repairs=repairs,overwrite=overwrite,
                                      author=overrides['author'],revision=overrides['revision'],summary=overrides['summary']),"converted")

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.note.set(value)
                    continue
                self.busy = False
                self.progress.stop()
                for control in self.controls:
                    control.configure(state="normal")
                if kind == "error":
                    self._error(value)
                elif kind == "preview":
                    self.preview = value
                    self._show_preview(value)
                elif kind == "converted":
                    self.report = value
                    self.status.set("Conversion complete")
                    self.note.set("Output saved. Test the converted mod in Transport Fever 3.")
                    self._set_details("OUTPUT\n" + value["destination"] + "\n\n" + json.dumps(value, ensure_ascii=False, indent=2))
                    self.open_button.configure(state="normal")
                    self.convert_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _show_preview(self, descriptor: ModDescriptor) -> None:
        self.loading = True
        for key, value in (("name", descriptor.name), ("mod_id", descriptor.target_mod_id), ("revision", str(descriptor.revision)), ("summary", descriptor.summary)):
            if not self.variables[key].get():
                self.variables[key].set(value)
        self.loading = False
        if descriptor.blockers:
            self.status.set("Manual changes required")
            self.note.set("Resolve the items below, then preview again.")
        else:
            self.status.set("Ready to convert metadata")
            self.note.set("Review the details and create the converted folder.")
        sections = [f"{descriptor.name}\nID: {descriptor.target_mod_id}\nRevision: {descriptor.revision}"]
        if descriptor.blockers:
            sections.append("REQUIRED CHANGES\n" + "\n\n".join(descriptor.blockers))
        if descriptor.warnings:
            sections.append("REVIEW NOTES\n" + "\n\n".join(descriptor.warnings))
        audit = descriptor.resource_audit
        plan = descriptor.conversion_plan
        sections.append("CONTENT MIGRATION\n" +
                        "\n".join(f"{category.replace('_', ' ')}: {count} resources" for category, count in plan.get("categories", {}).items()) +
                        f"\n{len(plan.get('geometry', []))} mesh/blob pairs analyzed.\n" +
                        "Analysis identifies required work; automated export currently supports metadata/layout and the separate electric-locomotive draft.\n\n" +
                        "\n\n".join(f"{item['file']}\n" + "\n".join(item["requirements"]) for item in plan.get("resources", [])))
        references = audit.get("references", [])
        sections.append(f"RESOURCE CHECKS\n{audit.get('filesScanned', 0)} text resources checked; {len(references)} literal references found.\n"
                        "External resources and game compatibility still require TF3 testing.\n\n" +
                        "\n".join(f"{item['status']}: {item['source']} → {item['reference']}" for item in references))
        sections.append("GENERATED MOD.JSON\n" + json.dumps(descriptor.as_mod_json(), ensure_ascii=False, indent=2))
        sections.append("GENERATED MODINFO.JSON\n" + json.dumps(descriptor.as_modinfo_json(), ensure_ascii=False, indent=2))
        self._set_details("\n\n".join(sections))
        self.convert_button.configure(state="normal" if not descriptor.blockers and self.variables["destination"].get().strip() else "disabled")

    def _set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _error(self, message: str) -> None:
        self.preview = None
        self.status.set("Could not continue")
        self.note.set("Check the message below and update your choices.")
        self.convert_button.configure(state="disabled")
        self._set_details(message)

    def open_output(self) -> None:
        if not self.report:
            return
        try:
            path = self.report["destination"]
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        except OSError as error:
            self._error(f"Could not open output folder: {error}")

    def _close(self) -> None:
        if self.busy:
            messagebox.showinfo("Conversion in progress", "Wait for the current operation to finish before closing.", parent=self.root)
            return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
