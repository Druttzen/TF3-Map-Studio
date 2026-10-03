"""A removable mod queue; filesystem work never runs on the Tk event loop."""
from __future__ import annotations

import queue
from dataclasses import replace
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .batch import scan_mods, convert_queue, find_tf3_game


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title('TRF3 Mod Converter')
        root.geometry(f'{min(1080, root.winfo_screenwidth()-60)}x{min(820, root.winfo_screenheight()-60)}')
        root.minsize(840, 620)
        root.configure(bg='#edf0f4')
        self.events = queue.Queue()
        self.busy, self.operation, self.loading = False, '', False
        self.stop_event = threading.Event()
        self.items, self.rows, self.controls = [], {}, []
        self.report = None
        self.variables = {key: tk.StringVar() for key in ('source', 'destination', 'tf3_game')}
        self.status = tk.StringVar(value='Choose a folder to build your queue')
        self.note = tk.StringVar(value='Subfolders are scanned automatically. Remove any mod you do not want to include.')
        self.counter = tk.StringVar(value='0 mods listed')
        self._styles()
        self._layout()
        for key, variable in self.variables.items():
            variable.trace_add('write', lambda *_args, k=key: self._changed(k))
        root.protocol('WM_DELETE_WINDOW', self._close)
        self.poll_id = root.after(60, self._poll)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#edf0f4', foreground='#17283e')
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white')
        style.configure('TEntry', padding=4, fieldbackground='#f6f8fb')
        style.configure('TButton', padding=(8, 4))
        style.configure('Accent.TButton', background='#16796c', foreground='white', padding=(14, 8), font=('Segoe UI Semibold', 10))
        style.map('Accent.TButton', background=[('disabled', '#b0c5c0'), ('active', '#116659')])
        style.configure('TProgressbar', background='#16796c', troughcolor='#edf0f4')

    def _layout(self):
        header = tk.Frame(self.root, bg='#17283e', padx=18, pady=10)
        header.pack(fill='x')
        tk.Label(header, text='Convert your mod collection.', bg='#17283e', fg='white', font=('Segoe UI Semibold', 18)).pack(anchor='w')
        tk.Label(header, text=f'TRF3 MOD CONVERTER {__version__}  ·  Original mods preserved', bg='#17283e', fg='#b7c5d6', font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 0))
        body = ttk.Frame(self.root, padding=12)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        paths = ttk.Frame(body, style='Card.TFrame', padding=10)
        paths.grid(row=0, column=0, sticky='ew')
        paths.columnconfigure(1, weight=1)
        for row, (key, label, command) in enumerate((
            ('source', 'Mod folder', self._browse_source_folder),
            ('destination', 'Export folder', self._browse_destination),
            ('tf3_game', 'TF3 installation', self._browse_game))):
            ttk.Label(paths, text=label, style='Card.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 12), pady=2)
            entry = ttk.Entry(paths, textvariable=self.variables[key])
            entry.grid(row=row, column=1, sticky='ew', pady=2)
            button = ttk.Button(paths, text='Choose folder', command=command)
            button.grid(row=row, column=2, padx=(10, 0), pady=2)
            self.controls.extend((entry, button))
            if key == 'source':
                entry.bind('<Return>', lambda _event: self.scan())
        toolbar = ttk.Frame(body)
        toolbar.grid(row=1, column=0, sticky='ew', pady=(8, 6))
        ttk.Label(toolbar, textvariable=self.counter, font=('Segoe UI Semibold', 11)).pack(side='left')
        ttk.Label(toolbar, text='− removes a mod from this queue').pack(side='right')
        host = ttk.Frame(body, style='Card.TFrame')
        host.grid(row=2, column=0, sticky='nsew')
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(host, background='white', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(host, command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.list_frame = tk.Frame(self.canvas, bg='white')
        self.list_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor='nw')
        self.list_frame.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._resize_list)
        self.root.bind('<MouseWheel>', lambda event: self.canvas.yview_scroll(-int(event.delta/120), 'units') if str(event.widget).startswith(str(host)) else None)
        details_host = ttk.Frame(body)
        details_host.grid(row=3, column=0, sticky='ew', pady=(6, 0))
        details_host.columnconfigure(0, weight=1)
        self.details = tk.Text(details_host, height=3, wrap='word', font=('Segoe UI', 9), bg='#f6f8fb', fg='#526174', relief='flat', padx=8, pady=6, state='disabled')
        self.details.grid(row=0, column=0, sticky='ew')
        detail_scroll = ttk.Scrollbar(details_host, command=self.details.yview)
        detail_scroll.grid(row=0, column=1, sticky='ns')
        self.details.configure(yscrollcommand=detail_scroll.set)
        self._set_details('Choose a mod folder or a Workshop collection. Click a mod name to see its result.\nA green ✓ confirms an export; test exported mods in TF3.')
        ttk.Label(body, textvariable=self.status, font=('Segoe UI Semibold', 10)).grid(row=4, column=0, sticky='w', pady=(6, 2))
        note = ttk.Label(body, textvariable=self.note, font=('Segoe UI', 9), wraplength=1000)
        note.grid(row=5, column=0, sticky='ew')
        body.bind('<Configure>', lambda event: note.configure(wraplength=max(200, event.width-24)))
        self.progress = ttk.Progressbar(body, mode='determinate')
        self.progress.grid(row=6, column=0, sticky='ew', pady=(6, 8))
        actions = ttk.Frame(body)
        actions.grid(row=7, column=0, sticky='ew')
        self.stop_button = ttk.Button(actions, text='Stop after current mod', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        self.convert_button = ttk.Button(actions, text='Convert all listed mods', style='Accent.TButton', command=self.convert_all, state='disabled')
        self.convert_button.pack(side='right')

    def _set_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def _changed(self, key):
        if self.loading or self.busy:
            return
        self.report = None
        if key == 'source':
            self.items = []
            self._render_queue()
            self.status.set('Press Enter or choose a folder to scan')
        else:
            for item in self.items:
                item.status, item.message = 'pending', ''
                self._update_row(item)
        self._buttons()

    def _buttons(self):
        self.convert_button.configure(state='normal' if self.items and self.variables['destination'].get().strip() and not self.busy else 'disabled')
        self.stop_button.configure(state='normal' if self.busy else 'disabled')
        for control in self.controls:
            control.configure(state='disabled' if self.busy else 'normal')
        for row in self.rows.values():
            row['minus'].configure(state='disabled' if self.busy else 'normal')

    def _browse_source_folder(self):
        if path := filedialog.askdirectory(parent=self.root, title='Choose a mod folder or collection'):
            self._set_source(path)

    def _set_source(self, path):
        self.loading = True
        self.variables['source'].set(path)
        if not self.variables['destination'].get():
            self.variables['destination'].set(str(Path.home()/'Documents/TF3-Converted-Mods'))
        self.loading = False
        self.scan()

    def _browse_destination(self):
        if path := filedialog.askdirectory(parent=self.root, title='Choose a separate export folder'):
            self.variables['destination'].set(path)

    def _browse_game(self):
        if path := filedialog.askdirectory(parent=self.root, title='Choose installed Transport Fever 3'):
            self.variables['tf3_game'].set(path)

    def _run(self, operation, result_kind):
        self.busy = True
        self.stop_event.clear()
        self._buttons()
        def worker():
            try:
                self.events.put((result_kind, operation()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def scan(self):
        if self.busy:
            return
        source = self.variables['source'].get().strip().strip('"')
        if not source:
            self._error('Choose a mod folder first.')
            return
        destination = self.variables['destination'].get().strip().strip('"')
        game_missing = not self.variables['tf3_game'].get().strip()
        self.items = []
        self._render_queue()
        self.operation = 'scan'
        self.status.set('Scanning folders…')
        self.note.set('Reading mod names without running their scripts.')
        self.stop_button.configure(text='Stop scanning')
        self.progress.configure(mode='indeterminate')
        self.progress.start(15)
        def work():
            result = scan_mods(source, exclude=destination or None, stop=self.stop_event,
                               progress=lambda message: self.events.put(('progress', {'message': message})))
            result['game'] = find_tf3_game(source) if game_missing else ''
            return result
        self._run(work, 'scanned')

    def remove_item(self, key):
        if self.busy:
            return
        self.items = [item for item in self.items if item.key != key]
        row = self.rows.pop(key, None)
        if row:
            row['frame'].destroy()
        self.counter.set(f'{len(self.items)} mods listed')
        self._buttons()

    def _render_queue(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.rows = {}
        for item in self.items:
            frame = tk.Frame(self.list_frame, bg='white', padx=14, pady=5)
            frame.pack(fill='x')
            frame.columnconfigure(0, weight=1)
            name = tk.Label(frame, text=item.display_name, bg='white', anchor='w', justify='left', wraplength=max(240, self.canvas.winfo_width()-230), font=('Segoe UI Semibold', 10), cursor='hand2')
            name.grid(row=0, column=0, sticky='ew')
            status = tk.Label(frame, text='Listed', bg='white', fg='#637184', font=('Segoe UI', 9))
            status.grid(row=0, column=1, padx=12)
            minus = ttk.Button(frame, text='−', width=3, command=lambda key=item.key: self.remove_item(key))
            minus.grid(row=0, column=2)
            name.bind('<Button-1>', lambda _event, value=item: self.show_item(value))
            self.rows[item.key] = {'frame': frame, 'name': name, 'status': status, 'minus': minus}
            self._update_row(item)
        self.counter.set(f'{len(self.items)} mods listed')
        self.canvas.yview_moveto(0)

    def _resize_list(self, event):
        self.canvas.itemconfigure(self.list_window, width=event.width)
        for row in self.rows.values():
            row['name'].configure(wraplength=max(240, event.width-230))

    def _update_row(self, item):
        if item.key not in self.rows:
            return
        row = self.rows[item.key]
        color = {'pending': '#17283e', 'running': '#16796c', 'completed': '#16803a', 'failed': '#b53636'}[item.status]
        row['name'].configure(text=item.display_name + (' ✓' if item.status == 'completed' else ''), fg=color)
        row['status'].configure(text={'pending': 'Needs review' if item.scan_error else 'Listed', 'running': 'Converting…', 'completed': 'Exported', 'failed': 'Needs review'}[item.status], fg=color)

    def show_item(self, item):
        self._set_details(f'{item.display_name}\n{item.message or item.scan_error or "Waiting in the queue"}\nSource: {item.source}' + (f'\nExport: {item.destination}' if item.destination else ''))

    def convert_all(self):
        if self.busy or not self.items:
            return
        destination = self.variables['destination'].get().strip().strip('"')
        if not destination:
            self._error('Choose a separate export folder.')
            return
        game = self.variables['tf3_game'].get().strip().strip('"') or None
        for item in self.items:
            item.status, item.message = 'pending', ''
            self._update_row(item)
        self.operation = 'convert'
        self.status.set('Converting listed mods…')
        self.note.set('One mod at a time. Errors are recorded and the queue continues.')
        self.stop_button.configure(text='Stop after current mod')
        self.progress.stop()
        self.progress.configure(mode='determinate', maximum=len(self.items), value=0)
        queue_items = [replace(item) for item in self.items]
        self._run(lambda: convert_queue(queue_items, destination, tf3_game=game, stop=self.stop_event,
                                       event=lambda kind, value: self.events.put((kind, value))), 'finished')

    def stop(self):
        self.stop_event.set()
        self.note.set('Stopping…' if self.operation == 'scan' else 'The current mod will finish safely. Remaining mods stay in the queue.')
        self.stop_button.configure(state='disabled')

    def _poll(self):
        try:
            for _ in range(80):
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    if not self.stop_event.is_set():
                        self.note.set(value['message'])
                elif kind == 'item':
                    item = next((i for i in self.items if i.key == value['key']), None)
                    if item:
                        item.status, item.message = value['status'], value['message']
                        item.destination = value.get('destination', '')
                        self._update_row(item)
                        self.progress.configure(value=value['index'])
                        if item.status == 'failed':
                            self.show_item(item)
                else:
                    self.busy = False
                    self.progress.stop()
                    if kind == 'scanned':
                        self.items = value['items']
                        self.loading = True
                        if value['game']:
                            self.variables['tf3_game'].set(value['game'])
                        self.loading = False
                        self._render_queue()
                        self.status.set(f'Scan {"stopped" if value["cancelled"] else "complete"} · {len(self.items)} mods listed')
                        self.note.set('Remove unwanted mods with −, then convert the remaining list.')
                        if value['warnings']:
                            self._set_details('\n'.join(value['warnings']))
                    elif kind == 'finished':
                        self.report = value
                        counts = value['counts']
                        self.status.set(f'{"Queue stopped" if value["cancelled"] else "Queue finished"} · {counts["completed"]} exported · {counts["failed"]} need review')
                        self.note.set('Results saved. Click a mod name for details. Existing exports are never overwritten.')
                    elif kind == 'error':
                        for item in self.items:
                            if item.status == 'running':
                                item.status, item.message = 'failed', value
                                self._update_row(item)
                        self._error(value)
                    self._buttons()
        except queue.Empty:
            pass
        self.poll_id = self.root.after(60, self._poll)

    def _error(self, message):
        self.status.set('Could not continue')
        self.note.set('Review the message and update your folder choices.')
        self._set_details(message)

    def _close(self):
        if self.busy:
            self.stop()
            messagebox.showinfo('Stopping safely', 'The current operation must finish before closing. Remaining mods will stay unconverted.', parent=self.root)
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
