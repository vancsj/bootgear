"""Bootgear's macOS setup window."""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font, ttk

from bootgear_cli import clikit, hook_loader, native_setup

HOSTS = {"claude": "Claude Code", "codex": "Codex"}
OPERATIONS = {
    "install": ("Install", "Set up the plugins you choose."),
    "repair": ("Repair", "Refresh plugins and rebuild Python dependencies."),
    "configure": ("Configure", "Fill in missing settings."),
}
LABELS = {
    "cli": ("Gear CLI", "Shared commands and Python runtime"),
    "memory-ledger": ("Memory Ledger", "Save and verify decisions across sessions"),
    "engine": ("Engine", "Run tasks with goals and review gates"),
    "spec": ("Spec", "Write and review requirements"),
    "test": ("Test", "Verify behaviour and diagnose failures"),
    "converge": ("Converge", "Check claims against independent evidence"),
    "review": ("Review", "Find issues in code and documents"),
    "advisor": ("Advisor", "Work with another coding agent"),
    "deputy": ("Deputy", "Apply your saved decisions"),
}

BACKGROUND = "#F3F6FC"
SURFACE = "#FFFFFF"
TEXT = "#17253D"
MUTED = "#52637B"
BORDER = "#DBE4F1"
BLUE = "#1759CC"
NAVY = "#162C4B"
CARD = "#F7F9FD"


class SetupWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Bootgear Setup")
        root.geometry("920x660")
        root.minsize(780, 570)
        root.configure(background=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self.hosts = [host for host in HOSTS if shutil.which(host)]
        preferred = clikit.host()
        self.host = tk.StringVar(value=HOSTS[preferred] if preferred in self.hosts else
                                 HOSTS[self.hosts[0]] if self.hosts else "Choose a host")
        self.operation = tk.StringVar(value="install")
        self.selected: dict[str, tk.BooleanVar] = {}
        self.controls: list[ttk.Widget] = []
        self.plugin_controls: list[ttk.Widget] = []
        self.messages: queue.Queue = queue.Queue()
        self.busy = False
        self.loaded = False
        self.details = ""
        self._style()
        self._layout()
        self.root.after_idle(self._load_choices)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        default = font.nametofont("TkDefaultFont")
        family = default.actual("family")
        style.configure(".", font=(family, 13), bordercolor=BORDER, foreground=TEXT)
        style.configure("TFrame", background=SURFACE)
        style.configure("Card.TFrame", background=CARD, bordercolor=BORDER)
        style.configure("Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("TCombobox", padding=(9, 5), arrowsize=12, arrowcolor=TEXT,
                        fieldbackground=SURFACE, selectbackground=SURFACE, selectforeground=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE), ("disabled", BACKGROUND)])
        style.layout("Quiet.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"sticky": "nswe"}),
            ]}),
        ])
        style.configure("Quiet.Vertical.TScrollbar", background="#ADBBD0", troughcolor=SURFACE,
                        bordercolor=SURFACE, arrowsize=7)
        self.root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", SURFACE)
        style.configure("Page.TFrame", background=BACKGROUND)
        style.configure("Nav.TFrame", background=NAVY)
        style.configure("TLabel", background=SURFACE, foreground=TEXT)
        style.configure("Page.TLabel", background=BACKGROUND)
        style.configure("Title.TLabel", font=(family, 26, "bold"), background=BACKGROUND)
        style.configure("Section.TLabel", font=(family, 18, "bold"))
        style.configure("Nav.TLabel", font=(family, 15, "bold"), background=NAVY, foreground="white")
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Footer.TLabel", foreground=MUTED, background=BACKGROUND)
        style.configure("Error.TLabel", foreground="#A3273B", background=BACKGROUND)
        style.configure("Done.TLabel", foreground="#186C4B", background=BACKGROUND)
        style.layout("Navigation.TRadiobutton", [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [
                ("Radiobutton.focus", {"sticky": "nswe", "children": [
                    ("Radiobutton.label", {"sticky": "w"}),
                ]}),
            ]}),
        ])
        style.configure("Navigation.TRadiobutton", background=NAVY, foreground="#E7EFFD",
                        focuscolor="#8BBCFF", padding=(12, 11))
        style.map("Navigation.TRadiobutton", background=[("disabled", NAVY), ("selected", "#294C78"),
                                                         ("active", "#223F68")],
                  foreground=[("disabled", "#9BAFCD"), ("selected", "#FFFFFF")])
        style.configure("TCheckbutton", background=CARD, font=(family, 13, "bold"),
                        focuscolor=BLUE, padding=(0, 3))
        style.map("TCheckbutton", background=[("active", "#EBF2FF"), ("disabled", CARD)])
        style.configure("TButton", padding=(14, 8), background=SURFACE, focuscolor=BLUE)
        style.map("TButton", background=[("active", "#E8F0FF")])
        style.configure("Primary.TButton", padding=(22, 9), font=(family, 13, "bold"),
                        background=BLUE, foreground="white", bordercolor=BLUE, focuscolor="#E7EDFF")
        style.map("Primary.TButton", background=[("disabled", "#DCE4F3"), ("active", "#1047AA")],
                  foreground=[("disabled", MUTED)])
        style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor=BORDER)

    def _layout(self) -> None:
        page = ttk.Frame(self.root, padding=(26, 21, 26, 19), style="Page.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)

        header = ttk.Frame(page, style="Page.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 17))
        ttk.Label(header, text="Bootgear Setup", style="Title.TLabel").pack(side="left")
        self.host_picker = ttk.Combobox(header, state="readonly" if self.hosts else "disabled",
                                       textvariable=self.host, values=[HOSTS[host] for host in self.hosts],
                                       width=15)
        self.host_picker.pack(side="right")
        ttk.Label(header, text="Host", style="Page.TLabel").pack(side="right", padx=(0, 9))
        self.host_picker.bind("<<ComboboxSelected>>", lambda _event: self._load_choices())

        nav = ttk.Frame(page, style="Nav.TFrame", padding=(18, 20, 18, 18), width=193)
        nav.grid(row=1, column=0, sticky="ns", padx=(0, 14))
        nav.grid_propagate(False)
        nav.columnconfigure(0, weight=1)
        ttk.Label(nav, text="Operation", style="Nav.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 13))
        for index, (value, (title, _)) in enumerate(OPERATIONS.items(), start=1):
            button = ttk.Radiobutton(nav, value=value, text=title, variable=self.operation,
                                     style="Navigation.TRadiobutton", command=self._refresh_action)
            button.grid(row=index, column=0, sticky="ew", pady=(0, 3))
            self.controls.append(button)

        content = ttk.Frame(page, padding=(21, 17, 15, 10), relief="solid", borderwidth=1)
        content.grid(row=1, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(content, text="Plugins", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.count = ttk.Label(content, style="Muted.TLabel")
        self.count.grid(row=0, column=1, sticky="e", padx=(0, 15))
        self.hint = ttk.Label(content, style="Muted.TLabel", wraplength=445)
        self.hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 13))
        body = ttk.Frame(content)
        body.grid(row=2, column=0, columnspan=2, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        canvas = self.canvas = tk.Canvas(body, background=SURFACE, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(body, orient="vertical", style="Quiet.Vertical.TScrollbar", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(4, 0))

        def scroll_position(start: float, end: float) -> None:
            scroll.set(start, end)
            if float(start) == 0 and float(end) == 1:
                scroll.grid_remove()
            else:
                scroll.grid()

        canvas.configure(yscrollcommand=scroll_position)
        self.rows = ttk.Frame(canvas)
        self.row_window = canvas.create_window(0, 0, window=self.rows, anchor="nw")
        self.rows.columnconfigure((0, 1), weight=1, uniform="plugin")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(self.row_window, width=event.width))
        canvas.bind("<MouseWheel>", self._scroll)
        self.rows.bind("<MouseWheel>", self._scroll)
        self.rows.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))

        footer = self.footer = ttk.Frame(page, style="Page.TFrame")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(11, 0))
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, style="Footer.TLabel", wraplength=480)
        self.status.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=130)
        self.settings = ttk.Button(footer, text="Settings Files…", command=self._show_settings)
        self.settings.grid(row=0, column=1, padx=(0, 9), sticky="e")
        self.settings.grid_remove()
        self.detail_button = ttk.Button(footer, text="Details", command=self._show_details)
        self.detail_button.grid(row=0, column=2, padx=(0, 9), sticky="e")
        self.detail_button.grid_remove()
        self.action = ttk.Button(footer, style="Primary.TButton", command=self._start_setup)
        self.action.grid(row=0, column=3, sticky="e")
        footer.bind("<Configure>", lambda _event: self._wrap_status())
        self._refresh_action()

    def _scroll(self, event: tk.Event) -> str:
        self.canvas.yview_scroll(-max(1, abs(event.delta) // 36) if event.delta > 0 else
                                 max(1, abs(event.delta) // 36), "units")
        return "break"

    def _selected_host(self) -> str:
        return next(host for host in self.hosts if HOSTS[host] == self.host.get())

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.host_picker.configure(state="disabled" if busy or not self.hosts else "readonly")
        for widget in [*self.controls, *self.plugin_controls]:
            widget.state(["disabled" if busy else "!disabled"])
        if busy:
            self.progress.grid(row=1, column=0, sticky="w", pady=(6, 0))
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self._refresh_action()

    def _show_status(self, text: str, style: str = "Footer.TLabel") -> None:
        self.status.configure(text=text, style=style)
        self.root.after_idle(self._wrap_status)

    def _wrap_status(self) -> None:
        buttons = (self.settings, self.detail_button, self.action)
        taken = sum(button.winfo_reqwidth() + 9 for button in buttons if button.winfo_manager())
        self.status.configure(wraplength=max(170, self.footer.winfo_width() - taken - 20))

    def _refresh_action(self) -> None:
        operation = self.operation.get()
        title, hint = OPERATIONS[operation]
        count = sum(variable.get() for variable in self.selected.values())
        if operation == "repair" and not count:
            hint = "Refresh all Bootgear plugins in this host profile."
        elif not count:
            hint = f"{hint} With no selection, use Gear CLI."
        self.hint.configure(text=hint)
        self.count.configure(text=f"{count} selected" if count else "")
        self.action.configure(text=title)
        self.action.state(["disabled" if self.busy or not self.loaded else "!disabled"])
        if self.loaded and operation == "configure":
            self.settings.grid()
            self.settings.state(["disabled" if self.busy else "!disabled"])
        else:
            self.settings.grid_remove()
        self.root.after_idle(self._wrap_status)

    def _background(self, function, on_done, on_error) -> None:
        self._set_busy(True)

        def worker() -> None:
            try:
                self.messages.put((True, function()))
            except (OSError, ValueError, RuntimeError, native_setup.SetupError, native_setup.runtime.RuntimeNotReady) as exc:
                self.messages.put((False, str(exc)))

        def poll() -> None:
            try:
                okay, result = self.messages.get_nowait()
            except queue.Empty:
                self.root.after(70, poll)
                return
            self._set_busy(False)
            (on_done if okay else on_error)(result)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(70, poll)

    def _load_choices(self) -> None:
        self.loaded = False
        self._refresh_action()
        if not self.hosts:
            self._show_status("Install Claude Code or Codex, then reopen Setup.", "Error.TLabel")
            return
        self._show_status("Reading plugin choices…")
        host = self._selected_host()
        self._background(lambda: native_setup._installer(host).choices(), self._render_choices, self._failed)

    def _render_choices(self, plugins: list[dict[str, str]]) -> None:
        chosen = {name for name, var in self.selected.items() if var.get()}
        for widget in self.rows.winfo_children():
            widget.destroy()
        self.selected.clear()
        self.plugin_controls.clear()
        for index, plugin in enumerate(plugins):
            name = plugin["name"]
            title, detail = LABELS.get(name, (name, plugin["description"]))
            variable = self.selected[name] = tk.BooleanVar(value=name in chosen)
            row = ttk.Frame(self.rows, padding=(10, 5, 10, 7), style="Card.TFrame",
                            relief="solid", borderwidth=1)
            row.grid(row=index // 2, column=index % 2, sticky="nsew", padx=(0, 8), pady=(0, 8))
            check = ttk.Checkbutton(row, text=title, variable=variable, command=self._refresh_action)
            check.pack(anchor="w")
            self.plugin_controls.append(check)
            description = ttk.Label(row, text=detail, style="Card.TLabel", wraplength=210)
            description.pack(anchor="w", padx=(18, 0))
            row.bind("<Configure>", lambda event, label=description: label.configure(
                wraplength=max(1, event.width - 43)))
            for widget in (row, check, description):
                widget.bind("<MouseWheel>", self._scroll)
        self.canvas.yview_moveto(0)
        self.loaded = True
        self._show_status("")
        self._refresh_action()
        if self.plugin_controls:
            self.plugin_controls[0].focus_set()

    def _start_setup(self) -> None:
        host, operation = self._selected_host(), self.operation.get()
        chosen = tuple(name for name, selected in self.selected.items() if selected.get())
        title, _ = OPERATIONS[operation]
        self._show_status(f"{title} is running for {HOSTS[host]}…")
        self._background(lambda: native_setup.execute_setup(host, operation, chosen), self._finished, self._failed)

    def _failed(self, message: str) -> None:
        self.details = message
        self.detail_button.grid()
        self._show_status(message.splitlines()[0][:135], "Error.TLabel")

    def _finished(self, result: dict) -> None:
        self.details = "\n".join([
            f"Selected: {', '.join(result['selected']) or 'none'}",
            f"Plugins ready: {', '.join(result['plugins']) or 'none'}",
            f"Managed Python: {result['python']}",
            f"Shared runtime: {result['runtime']}",
            *(f"Created {name}" for name in result["defaults"]),
            *result["pending"], result["next"],
        ])
        self.detail_button.grid()
        self._show_status("Setup complete. Restart your Claude Code or Codex sessions.", "Done.TLabel")

    def _dialog(self, title: str) -> ttk.Frame:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        return frame

    def _show_details(self) -> None:
        frame = self._dialog("Setup Details")
        text = tk.Text(frame, width=72, height=12, wrap="word", padx=8, pady=8,
                       background=BACKGROUND, foreground=TEXT, font=font.nametofont("TkDefaultFont"))
        text.pack(fill="both", expand=True)
        text.insert("1.0", self.details)
        text.configure(state="disabled")

    def _show_settings(self) -> None:
        frame = self._dialog("Bootgear Settings")
        profile = hook_loader.profile_root(self._selected_host())
        names = [name for defaults in native_setup.DEFAULTS.values() for name in defaults]
        paths = [profile / name for name in names if (profile / name).is_file()]
        if not paths:
            ttk.Label(frame, text="Use Configure to create the missing settings.").pack(anchor="w")
        for path in paths:
            ttk.Button(frame, text=path.name, command=lambda path=path: self._open_setting(path)).pack(fill="x", pady=3)

    def _open_setting(self, path: Path) -> None:
        try:
            subprocess.run(["open", str(path)], check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            self._failed(str(exc))

    def _close(self) -> None:
        if self.busy:
            self._show_status("Setup is still running. Close this window after it finishes.")
        else:
            self.root.destroy()


def launch() -> int:
    root = tk.Tk()
    SetupWindow(root)
    root.mainloop()
    return 0
