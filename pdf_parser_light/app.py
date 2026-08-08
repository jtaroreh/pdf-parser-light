import os
import queue
import sys
import threading
import traceback
import webbrowser
from tkinter import filedialog

import customtkinter as ctk

from .parse import parse_pdf

# Global lock handle to keep the file lock or mutex alive
_lock_handle = None

from . import config

CONFIG_FILE = os.path.join(config.CONFIG_DIR, "api_key.txt")

def save_api_key(key):
    try:
        os.makedirs(config.CONFIG_DIR, mode=0o700, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(config.CONFIG_DIR, 0o700)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        if sys.platform != "win32":
            os.chmod(CONFIG_FILE, 0o600)
    except Exception as e:
        print(f"Failed to save API key: {e}", file=sys.stderr)

def load_api_key():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        print(f"Failed to load API key: {e}", file=sys.stderr)
    return None

def delete_api_key():
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
    except Exception as e:
        print(f"Failed to delete API key: {e}", file=sys.stderr)

def get_log_path():
    if getattr(sys, 'frozen', False):
        if sys.platform == "darwin":
            return os.path.join(os.path.expanduser("~"), "Library/Logs/PDF_Parser_Light_run.log")
        elif sys.platform == "win32":
            return os.path.join(os.path.expandvars("%LOCALAPPDATA%"), "PDF_Parser_Light", "PDF_Parser_Light_run.log")
        else:
            return os.path.join(os.path.expanduser("~/.cache"), "PDF_Parser_Light", "PDF_Parser_Light_run.log")
    else:
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../app_run.log"))


# Fix Python 3.13+ compatibility where tkinter.tix was removed (PEP 594)
import tkinter
if not hasattr(tkinter, "tix"):
    class _TixMock:
        def __getattr__(self, name):
            class _Dummy:
                pass
            return _Dummy
    tix_mock = _TixMock()
    tkinter.tix = tix_mock
    sys.modules["tkinter.tix"] = tix_mock

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception as e:
    HAS_DND = False
    print(f"Notice: tkinterdnd2 import failed ({e}). Install via 'pip install tkinterdnd2-universal'", file=sys.stderr)

if HAS_DND:
    class BaseApp(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            ctk.CTk.__init__(self, *args, **kwargs)
            self.dnd_enabled = False
            TkinterDnD._tkinterdnd_default_root = self
            try:
                if getattr(sys, 'frozen', False):
                    meipass = getattr(sys, '_MEIPASS', '')
                    if meipass:
                        for path in (os.path.join(meipass, 'tkinterdnd2'), meipass):
                            if os.path.exists(path):
                                try:
                                    self.tk.call('lappend', 'auto_path', path)
                                except Exception:
                                    pass
                if hasattr(TkinterDnD, "_require"):
                    TkinterDnD._require(self)
                elif hasattr(self, "_require"):
                    self._require()
                else:
                    self.tk.eval('package require tkdnd')
                TkinterDnD.DnDWrapper.__init__(self)
                self.dnd_enabled = True
            except Exception as e:
                print(f"TkinterDnD wrapper init error: {e}", file=sys.stderr)
else:
    class BaseApp(ctk.CTk):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.dnd_enabled = False


class App(BaseApp):
    def __init__(self):
        super().__init__()

        # Resolve icon path based on platform preference
        icon_names = ["icon.icns", "icon.png"]
        if sys.platform == "win32":
            icon_names = ["icon.ico", "icon.png"]

        icon_path = None
        if getattr(sys, 'frozen', False):
            # Check PyInstaller bundle resources
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            for name in icon_names:
                test_path = os.path.join(base_path, name)
                if os.path.exists(test_path):
                    icon_path = test_path
                    break
        else:
            # Local fallbacks for development - check both local package dir and parent project root dir
            local_dir = os.path.dirname(os.path.abspath(__file__))
            for name in icon_names:
                for d in [local_dir, os.path.dirname(local_dir)]:
                    test_path = os.path.join(d, name)
                    if os.path.exists(test_path):
                        icon_path = test_path
                        break
                if icon_path:
                    break



        # Set Windows Titlebar Icon at runtime
        if sys.platform == "win32" and icon_path:
            try:
                if icon_path.endswith(".ico"):
                    self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Error setting Windows titlebar icon: {e}", file=sys.stderr)

        self.title("PDF Parser Light")
        self.geometry("550x580")
        self.resizable(True, True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(7, weight=1)  # The console textbox expands

        self.api_header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.api_header_frame.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="ew")
        self.api_header_frame.grid_columnconfigure(2, weight=1)

        self.api_key_label = ctk.CTkLabel(
            self.api_header_frame, 
            text="Gemini API Key:", 
            anchor="w",
            font=ctk.CTkFont(weight="bold")
        )
        self.api_key_label.grid(row=0, column=0, sticky="w")

        self.api_key_link = ctk.CTkLabel(
            self.api_header_frame,
            text="(Get free key ↗)",
            font=ctk.CTkFont(size=12, underline=True),
            text_color=("#1F6AA5", "#4C9BE8"),
            cursor="hand2"
        )
        self.api_key_link.grid(row=0, column=1, padx=(8, 0), sticky="w")

        def _open_free_key_url(e=None):
            self.after(10, lambda: webbrowser.open("https://aistudio.google.com/api-keys"))

        for widget in (self.api_key_link, getattr(self.api_key_link, "_label", None), getattr(self.api_key_link, "_canvas", None)):
            if widget:
                widget.bind("<Button-1>", _open_free_key_url)

        self.usage_label = ctk.CTkLabel(
            self.api_header_frame,
            text="",
            text_color="gray"
        )
        self.usage_label.grid(row=0, column=2, sticky="e")
        self.update_usage_label()

        self.api_key_entry = ctk.CTkEntry(
            self, 
            placeholder_text="First paste your API key here",
            placeholder_text_color=("gray60", "#757575"),
            text_color=("black", "white"),
            show=""
        )
        self.api_key_entry.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        try:
            caret_color = self.api_key_entry._apply_appearance_mode(("black", "white"))
            self.api_key_entry._entry.configure(insertbackground=caret_color)
        except Exception:
            pass

        def _on_api_key_change(event=None):
            if self.api_key_entry.get():
                self.api_key_entry.configure(show="*")
            else:
                self.api_key_entry.configure(show="")

        self.api_key_entry.bind("<KeyRelease>", _on_api_key_change)

        self.options_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.options_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.options_frame.grid_columnconfigure(0, weight=1)

        self.save_key_var = ctk.BooleanVar(value=False)
        self.save_key_checkbox = ctk.CTkCheckBox(
            self.options_frame,
            text="Remember API Key",
            variable=self.save_key_var,
            command=self.on_checkbox_toggle
        )
        self.save_key_checkbox.grid(row=0, column=0, pady=(0, 8), sticky="w")

        self.page_range_frame = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        self.page_range_frame.grid(row=1, column=0, sticky="ew")
        self.page_range_frame.grid_columnconfigure(1, weight=1)

        self.page_range_label = ctk.CTkLabel(
            self.page_range_frame,
            text="Page Range:",
            font=ctk.CTkFont(weight="bold")
        )
        self.page_range_label.grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.page_range_entry = ctk.CTkEntry(
            self.page_range_frame,
            placeholder_text="e.g. 1-5, 8 (empty = all pages)",
            placeholder_text_color=("gray60", "#757575"),
            text_color=("black", "white")
        )
        self.page_range_entry.grid(row=0, column=1, sticky="ew")
        try:
            caret_color = self.page_range_entry._apply_appearance_mode(("black", "white"))
            self.page_range_entry._entry.configure(insertbackground=caret_color)
        except Exception:
            pass

        # Prevent interaction/selection until a PDF file is uploaded
        for seq in ("<Button-1>", "<Key>", "<FocusIn>"):
            self.page_range_entry.bind(seq, self._on_page_range_interaction)

        self.selected_file_path = None
        self.file_path_var = ctk.StringVar(value="No file selected")

        # Drag and Drop dropzone card
        self.drop_frame = ctk.CTkFrame(
            self,
            fg_color=("gray92", "#2B2D30"),
            border_color=("gray75", "#45474A"),
            border_width=2,
            corner_radius=12
        )
        self.drop_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        self.drop_frame.grid_columnconfigure(0, weight=1)

        self.drop_content_frame = ctk.CTkFrame(self.drop_frame, fg_color="transparent")
        self.drop_content_frame.pack(fill="both", expand=True, padx=15, pady=14)

        self.drop_title_label = ctk.CTkLabel(
            self.drop_content_frame,
            text="Drag & Drop PDF file here",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.drop_title_label.pack(pady=(0, 2))

        self.drop_sub_label = ctk.CTkLabel(
            self.drop_content_frame,
            text="or click Browse to choose a file",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray70")
        )
        self.drop_sub_label.pack(pady=(0, 8))

        self.browse_btn = ctk.CTkButton(
            self.drop_content_frame,
            text="Browse File",
            width=110,
            command=self.browse_file
        )
        self.browse_btn.pack()

        # Make entire drop zone card clickable to browse file (ignore direct clicks on browse_btn to prevent double-invocation)
        def _on_dropzone_click(e=None):
            if e and hasattr(e, "widget"):
                w = e.widget
                if w in (self.browse_btn, getattr(self.browse_btn, "_canvas", None), getattr(self.browse_btn, "_label", None)):
                    return
            self.browse_file()

        for widget in (self.drop_frame, self.drop_content_frame, self.drop_title_label, self.drop_sub_label):
            widget.bind("<Button-1>", _on_dropzone_click)

        if getattr(self, "dnd_enabled", False):
            try:
                for widget in (self.drop_frame, self.drop_content_frame, self.drop_title_label, self.drop_sub_label):
                    targets = []
                    if hasattr(widget, "drop_target_register"):
                        targets.append(widget)
                    if hasattr(widget, "_canvas") and widget._canvas and hasattr(widget._canvas, "drop_target_register"):
                        targets.append(widget._canvas)
                    if hasattr(widget, "_label") and widget._label and hasattr(widget._label, "drop_target_register"):
                        targets.append(widget._label)
                    for tk_w in targets:
                        try:
                            tk_w.drop_target_register(DND_FILES)
                            tk_w.dnd_bind('<<Drop>>', self._on_file_drop)
                            tk_w.dnd_bind('<<DragEnter>>', self._on_drag_enter)
                            tk_w.dnd_bind('<<DragLeave>>', self._on_drag_leave)
                        except Exception as e:
                            print(f"DnD widget registration error: {e}", file=sys.stderr)
            except Exception as e:
                print(f"DnD registration warning: {e}", file=sys.stderr)

        self.process_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.process_frame.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        self.process_frame.grid_columnconfigure(0, weight=1)
        self.process_frame.grid_columnconfigure(1, weight=1)

        self.process_btn = ctk.CTkButton(
            self.process_frame, 
            text="Process", 
            command=self.start_processing
        )
        self.process_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.cancel_btn = ctk.CTkButton(
            self.process_frame,
            text="Cancel",
            command=self.cancel_processing,
            state="disabled"
        )
        self.cancel_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress_bar.grid(row=5, column=0, padx=20, pady=10, sticky="ew")
        self.progress_bar.set(0)

        # Store the default theme color of the progress bar for resetting later
        try:
            self.default_progress_color = self.progress_bar.cget("progress_color")
        except Exception:
            self.default_progress_color = getattr(self.progress_bar, "_progress_color", None)

        self.console_label = ctk.CTkLabel(
            self, 
            text="Console Log Output:", 
            anchor="w",
            font=ctk.CTkFont(weight="bold")
        )
        self.console_label.grid(row=6, column=0, padx=20, pady=(10, 5), sticky="w")

        self.log_textbox = ctk.CTkTextbox(self, state="disabled")
        self.log_textbox.grid(row=7, column=0, padx=20, pady=(0, 10), sticky="nsew")

        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.grid(row=8, column=0, padx=20, pady=(10, 20), sticky="ew")
        self.actions_frame.grid_columnconfigure(0, weight=1)
        self.actions_frame.grid_columnconfigure(1, weight=0)
        self.actions_frame.grid_columnconfigure(2, weight=1)

        self.save_btn = ctk.CTkButton(
            self.actions_frame, 
            text="Save File", 
            command=self.save_file, 
            state="disabled"
        )
        self.save_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.format_var = ctk.StringVar(value=".md")
        self.format_menu = ctk.CTkOptionMenu(
            self.actions_frame,
            values=[".md", ".txt"],
            variable=self.format_var,
            width=80
        )
        self.format_menu.grid(row=0, column=1, padx=(5, 10), sticky="ew")

        self.copy_btn = ctk.CTkButton(
            self.actions_frame,
            text="Copy to Clipboard",
            command=self.copy_to_clipboard,
            state="disabled"
        )
        self.copy_btn.grid(row=0, column=2, padx=(10, 0), sticky="ew")

        self.queue = queue.Queue()
        self.markdown_result = None
        self.cancel_event = None

        # Load API key if saved
        saved_key = load_api_key()
        if saved_key:
            self.api_key_entry.delete(0, "end")
            self.api_key_entry.insert(0, saved_key)
            self.api_key_entry.configure(show="*")
            self.save_key_var.set(True)

        # Force geometry refresh for macOS window initialization
        if sys.platform == "darwin":
            self.after(10, self._force_refresh)

        # Handle close window protocol to allow sleep cleanup
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Global binding to deselect/unfocus textboxes when clicking anywhere outside of them
        self.bind_all("<Button-1>", self._on_global_click, add="+")

    def _on_global_click(self, event=None):
        if event is None or not hasattr(event, "widget"):
            return
        if not self._is_interactive_widget(event.widget):
            self.after(10, self.deselect_textboxes)

    def _is_interactive_widget(self, widget):
        current = widget
        if isinstance(current, str):
            try:
                current = self.nametowidget(current)
            except Exception:
                return False

        while current is not None:
            if isinstance(current, (ctk.CTkButton, ctk.CTkCheckBox, ctk.CTkOptionMenu, ctk.CTkEntry, ctk.CTkTextbox, tkinter.Entry, tkinter.Text, tkinter.Button, tkinter.Checkbutton)):
                return True
            class_name = current.__class__.__name__
            if any(k in class_name for k in ("Button", "CheckBox", "OptionMenu", "Entry", "Textbox", "Text", "Menu")):
                return True
            try:
                cursor_val = current.cget("cursor") if hasattr(current, "cget") else None
                if cursor_val == "hand2":
                    return True
            except Exception:
                pass
            try:
                parent_name = current.winfo_parent()
                if not parent_name:
                    break
                current = current.nametowidget(parent_name)
            except Exception:
                current = getattr(current, "master", None)
        return False

    def deselect_textboxes(self):
        focused = self.focus_get()
        if focused and self._is_textbox_widget(focused):
            self.focus_set()
            def _clear_widget(w):
                if isinstance(w, (ctk.CTkEntry, tkinter.Entry)):
                    try:
                        target = getattr(w, "_entry", w)
                        if hasattr(target, "selection_clear"):
                            target.selection_clear()
                    except Exception:
                        pass
                elif isinstance(w, (ctk.CTkTextbox, tkinter.Text)):
                    try:
                        target = getattr(w, "_textbox", w)
                        if hasattr(target, "tag_remove"):
                            target.tag_remove("sel", "1.0", "end")
                    except Exception:
                        pass
                if hasattr(w, "winfo_children"):
                    try:
                        for child in w.winfo_children():
                            _clear_widget(child)
                    except Exception:
                        pass
            _clear_widget(self)

    def _force_refresh(self):
        try:
            if not getattr(self, "winfo_exists", lambda: False)():
                return
            self.deiconify()
            self.update_idletasks()
            self.lift()
            try:
                self.attributes("-topmost", True)
                self.after(100, lambda: self.winfo_exists() and self.attributes("-topmost", False))
                self.focus_force()
            except Exception:
                pass
            w = self.winfo_width()
            h = self.winfo_height()
            if w <= 1 or h <= 1:
                w, h = 550, 580
            self.geometry(f"{w+1}x{h+1}")
            if self.winfo_exists():
                self.after(30, lambda: self.winfo_exists() and (self.geometry(f"{w}x{h}"), self.update_idletasks()))
        except Exception:
            pass

    def prevent_sleep(self):
        self.caffeinate_proc = None
        if sys.platform == "darwin":
            try:
                import subprocess
                # -i prevents system idle sleep, -w <pid> binds life to current python process
                self.caffeinate_proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            except Exception as e:
                print(f"Failed to start caffeinate: {e}", file=sys.stderr)
        elif sys.platform == "win32":
            try:
                import ctypes
                # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            except Exception as e:
                print(f"Failed to set thread execution state: {e}", file=sys.stderr)

    def allow_sleep(self):
        if sys.platform == "darwin":
            if getattr(self, "caffeinate_proc", None) is not None:
                try:
                    self.caffeinate_proc.terminate()
                    self.caffeinate_proc.wait(timeout=1)
                except Exception:
                    pass
                self.caffeinate_proc = None
        elif sys.platform == "win32":
            try:
                import ctypes
                # Reset back to continuous default
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception as e:
                print(f"Failed to reset thread execution state: {e}", file=sys.stderr)

    def on_closing(self):
        if getattr(self, "cancel_event", None) is not None:
            self.cancel_event.set()
        try:
            from .parse import cleanup_active_uploads
            api_key = self.api_key_entry.get().strip() if hasattr(self, "api_key_entry") else None
            cleanup_active_uploads(api_key=api_key)
        except Exception:
            pass
        self.allow_sleep()
        self.destroy()

    def _on_drag_enter(self, event=None):
        self.drop_frame.configure(
            border_color="#3B82F6",
            fg_color=("gray85", "#1E293B")
        )

    def _on_drag_leave(self, event=None):
        if getattr(self, "selected_file_path", None):
            self.drop_frame.configure(
                border_color=("#3B82F6", "#2563EB"),
                fg_color=("gray90", "#1E293B")
            )
        else:
            self.drop_frame.configure(
                border_color=("gray75", "#45474A"),
                fg_color=("gray92", "#2B2D30")
            )

    def _on_page_range_interaction(self, event=None):
        if not getattr(self, "selected_file_path", None):
            self.focus_set()
            return "break"

    def _on_file_drop(self, event):
        self._on_drag_leave(event)
        data = getattr(event, "data", "")
        if not data:
            return

        paths = []
        if hasattr(self, "splitlist"):
            try:
                paths = list(self.splitlist(data))
            except Exception:
                pass
        if not paths:
            import shlex
            try:
                paths = shlex.split(data)
            except Exception:
                paths = [data.strip("{}'\"")]

        for p in paths:
            clean_p = p.strip("{}'\" ")
            if clean_p and clean_p.lower().endswith(".pdf"):
                self.set_selected_file(clean_p)
                return

        if paths:
            self.set_selected_file(paths[0].strip("{}'\" "))

    def browse_file(self, event=None):
        def _do_browse():
            file_path = filedialog.askopenfilename(
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
            )
            if file_path:
                self.set_selected_file(file_path)
        self.after(10, _do_browse)

    def set_selected_file(self, file_path):
        if not file_path or not os.path.exists(file_path):
            self.show_error("Selected file does not exist.")
            return

        if not file_path.lower().endswith(".pdf"):
            self.show_error("Please select a valid PDF file (.pdf).")
            return

        from .parse import validate_pdf
        try:
            total_pages = validate_pdf(file_path)
        except Exception as e:
            self.show_error(f"Selected file is not a valid PDF:\n\n{e}")
            return

        self.selected_file_path = file_path
        self.total_pages = total_pages
        self.file_path_var.set(file_path)
        filename = os.path.basename(file_path)

        # Update Dropzone UI for selected file state
        self.drop_title_label.configure(
            text=f"{filename}",
            text_color=("black", "white")
        )
        self.drop_sub_label.configure(
            text=f"{total_pages} page{'s' if total_pages != 1 else ''} total • Click or drag to change file",
            text_color=("gray30", "gray70")
        )
        self.drop_frame.configure(
            border_color=("#3B82F6", "#2563EB"),
            fg_color=("gray90", "#1E293B")
        )

        # Enable page range entry now that a file is uploaded, and autofill with full page range
        self.page_range_entry.configure(state="normal")
        self.page_range_entry.delete(0, "end")
        if total_pages and isinstance(total_pages, int) and total_pages > 0:
            default_range = "1" if total_pages == 1 else f"1-{total_pages}"
            self.page_range_entry.insert(0, default_range)

        # Clear previous result, disable buttons, and reset progress bar since a new file is chosen
        self.markdown_result = None
        self.save_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.progress_bar.configure(mode="indeterminate", progress_color=self.default_progress_color)
        self.progress_bar.set(0)

    def on_checkbox_toggle(self):
        if not self.save_key_var.get():
            delete_api_key()

    def update_usage_label(self):
        left = config.get_remaining_requests()
        if left <= 0:
            self.usage_label.configure(
                text=f"Free 3.5 Quota Left: 0 / {config.MAX_FREE_REQUESTS} (Using Fallback Models)",
                text_color="#E67E22"
            )
        else:
            self.usage_label.configure(
                text=f"Free 3.5 Quota Left: {left} / {config.MAX_FREE_REQUESTS}",
                text_color="gray"
            )

    def log_message(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def cancel_processing(self):
        if self.cancel_event and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.log_message("\nCancellation requested by user. Cleaning up...\n")
            self.cancel_btn.configure(state="disabled")

    def start_processing(self):
        api_key = self.api_key_entry.get().strip()
        file_path = self.file_path_var.get()

        if not api_key:
            self.show_error("Please enter your Gemini API Key.")
            return
        if file_path == "No file selected" or not file_path:
            self.show_error("Please select a PDF file first.")
            return

        total_pages = getattr(self, "total_pages", None)
        if total_pages is None:
            from .parse import validate_pdf
            try:
                total_pages = validate_pdf(file_path)
                self.total_pages = total_pages
            except Exception as e:
                self.show_error(f"Invalid PDF file:\n\n{e}")
                return

        page_range = self.page_range_entry.get().strip() or None
        from .parse import _parse_page_range
        try:
            s_idx, e_idx = _parse_page_range(page_range, total_pages)
            target_count = e_idx - s_idx
        except Exception as pre:
            self.show_error(f"Invalid Page Range:\n\n{pre}")
            return

        from .parse import _count_chunk_requests
        left = config.get_remaining_requests()
        total_chunks = _count_chunk_requests(target_count) if target_count > 0 else 1

        ignore_quota = False
        if total_chunks > left:
            import tkinter.messagebox as msgbox
            if left <= 0:
                quota_msg = (
                    f"Processing this PDF requires ~{total_chunks} API request(s), but 0 requests remain in your daily free 3.5-flash quota.\n\n"
                    f"Proceeding will process using Fallback Models (gemini-3.5-flash-lite / gemini-3.1-flash-lite).\n\n"
                    f"Do you want to proceed anyway?"
                )
            else:
                quota_msg = (
                    f"Processing this PDF requires ~{total_chunks} API request(s), but only {left} request(s) remain in your daily free quota.\n\n"
                    f"Do you want to proceed anyway?"
                )
            answer = msgbox.askyesno("Quota Warning", quota_msg)
            if not answer:
                return
            ignore_quota = True

        # Clear previous result and log textbox
        self.markdown_result = None
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

        # Disable buttons and option controls during execution
        self.process_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        self.save_key_checkbox.configure(state="disabled")
        self.page_range_entry.configure(state="disabled")

        # Enable Cancel button only for multi-chunk jobs where cancelling halts future chunk requests
        if total_chunks > 1:
            self.cancel_btn.configure(state="normal")
        else:
            self.cancel_btn.configure(state="disabled")
        
        # Reset progress bar to default animating blue
        self.progress_bar.configure(mode="indeterminate", progress_color=self.default_progress_color)
        self.progress_bar.set(0)
        self.progress_bar.start()

        self.cancel_event = threading.Event()
        save_key_checked = self.save_key_var.get()
        out_path = f"{os.path.splitext(file_path)[0]}.md"

        # Start processing in a background thread
        thread = threading.Thread(
            target=self.process_pdf_thread, 
            args=(api_key, file_path, save_key_checked, ignore_quota, page_range, True, out_path), 
            daemon=True
        )
        self.prevent_sleep()
        thread.start()
        
        # Start checking the queue
        self.after(100, self.check_queue)

    def process_pdf_thread(self, api_key, file_path, save_key_checked, ignore_quota=False, page_range=None, resume=False, output_path=None):
        from .parse import PartialParseError, CancellationError, QuotaExceededError
        try:
            result = parse_pdf(
                api_key, 
                file_path, 
                log_callback=lambda msg: self.queue.put(("stdout", msg)),
                usage_callback=lambda: self.queue.put(("usage_increment", None)),
                ignore_quota=ignore_quota,
                cancel_event=self.cancel_event,
                page_range=page_range,
                resume=resume,
                output_path=output_path
            )
            if save_key_checked:
                save_api_key(api_key)
            else:
                delete_api_key()
            self.queue.put(("success", result))
        except PartialParseError as ppe:
            self.queue.put(("partial_success", ppe.partial_text))
        except CancellationError:
            self.queue.put(("cancelled", None))
        except QuotaExceededError as qee:
            self.queue.put(("error", str(qee)))
        except Exception as e:
            traceback.print_exc()
            log_path = get_log_path()
            self.queue.put(("error", f"Processing failed: {e}\n\nLog file:\n{log_path}"))

    def check_queue(self):
        reschedule = True
        try:
            while True:
                try:
                    msg_type, data = self.queue.get_nowait()
                except queue.Empty:
                    break
                
                try:
                    if msg_type == "stdout":
                        self.log_message(data)
                        if "--- CHUNK_PROGRESS:" in data:
                            try:
                                parts = data.split("--- CHUNK_PROGRESS:")[1].split("---")[0].strip().split("/")
                                current = int(parts[0])
                                total = int(parts[1])
                                self.progress_bar.stop()
                                self.progress_bar.configure(mode="determinate")
                                self.progress_bar.set(current / total)
                            except Exception:
                                pass
                    elif msg_type == "usage_increment":
                        self.update_usage_label()
                    else:
                        self.process_btn.configure(state="normal")
                        self.cancel_btn.configure(state="disabled")
                        self.browse_btn.configure(state="normal")
                        self.save_key_checkbox.configure(state="normal")
                        self.page_range_entry.configure(state="normal")
                        self.allow_sleep()
                        self.update_usage_label()
                        reschedule = False
                        
                        if msg_type == "success":
                            self.markdown_result = data
                            self.save_btn.configure(state="normal")
                            self.copy_btn.configure(state="normal")
                            
                            self.progress_bar.stop()
                            self.progress_bar.configure(mode="determinate", progress_color="green")
                            self.progress_bar.set(1.0)
                            
                            self.show_success("PDF successfully processed! You can now save the file or copy the content.")
                        elif msg_type == "partial_success":
                            self.markdown_result = data
                            self.save_btn.configure(state="normal")
                            self.copy_btn.configure(state="normal")
                            
                            self.progress_bar.stop()
                            self.progress_bar.configure(mode="determinate", progress_color="orange")
                            self.progress_bar.set(1.0)
                            
                            self.show_error("Processing failed mid-way, but partial markdown content was recovered and can be saved below.")
                        elif msg_type == "cancelled":
                            self.progress_bar.stop()
                            self.progress_bar.configure(mode="determinate", progress_color="gray")
                            self.progress_bar.set(0)
                            self.log_message("Processing cancelled by user.\n")
                        elif msg_type == "error":
                            self.progress_bar.stop()
                            self.progress_bar.configure(mode="determinate", progress_color="red")
                            self.progress_bar.set(1.0)
                            
                            self.show_error(f"An error occurred during processing:\n\n{data}")
                except Exception as e:
                    print(f"Error handling queue message: {e}", file=sys.stderr)
                    self.process_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.browse_btn.configure(state="normal")
                    self.save_key_checkbox.configure(state="normal")
                    self.page_range_entry.configure(state="normal")
                    self.allow_sleep()
                    reschedule = False
        finally:
            if reschedule:
                self.after(100, self.check_queue)


    def save_file(self):
        if not self.markdown_result:
            return
            
        def _do_save():
            selected_ext = self.format_var.get()
            
            if selected_ext == ".md":
                file_types = [("Markdown files", "*.md"), ("All files", "*.*")]
            else:
                file_types = [("Text files", "*.txt"), ("All files", "*.*")]

            save_path = filedialog.asksaveasfilename(
                defaultextension=selected_ext,
                filetypes=file_types
            )
            
            if save_path:
                if not os.path.splitext(save_path)[1]:
                    save_path += selected_ext

                try:
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(self.markdown_result)
                    self.show_success(f"File successfully saved to:\n{save_path}")
                except Exception as e:
                    traceback.print_exc()
                    self.show_error("Failed to save file. Please check the log for details.")
        self.after(10, _do_save)

    def copy_to_clipboard(self):
        if not self.markdown_result:
            return
            
        try:
            self.clipboard_clear()
            self.clipboard_append(self.markdown_result)
            self.update()
            self.show_success("Content successfully copied to clipboard!")
        except Exception as e:
            traceback.print_exc()
            self.show_error("Failed to copy to clipboard. Please check the log for details.")

    def _close_modal(self, win):
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    def show_error(self, message):
        error_window = ctk.CTkToplevel(self)
        error_window.title("Error")
        error_window.geometry("480x280")
        error_window.attributes("-topmost", True)
        error_window.grab_set()
        
        textbox = ctk.CTkTextbox(error_window, wrap="word")
        textbox.pack(pady=(20, 10), padx=20, fill="both", expand=True)
        textbox.insert("1.0", message)
        textbox.configure(state="disabled")
        
        btn = ctk.CTkButton(error_window, text="OK", command=lambda: self._close_modal(error_window), width=100)
        btn.pack(pady=(0, 15))

    def show_success(self, message):
        success_window = ctk.CTkToplevel(self)
        success_window.title("Success")
        success_window.geometry("350x150")
        success_window.attributes("-topmost", True)
        success_window.grab_set()
        
        lbl = ctk.CTkLabel(success_window, text=message, wraplength=300)
        lbl.pack(pady=20, padx=20, expand=True)
        
        btn = ctk.CTkButton(success_window, text="OK", command=lambda: self._close_modal(success_window), width=100)
        btn.pack(pady=10)


def _acquire_instance_lock():
    """Returns a lock handle, or None if another instance is running."""
    lock_path = os.path.join(config.CONFIG_DIR, "app.lock")
    os.makedirs(config.CONFIG_DIR, mode=0o700, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(config.CONFIG_DIR, 0o700)

    if sys.platform == "win32":
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "PDFParserSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return mutex
    else:
        import fcntl
        try:
            lock_file = open(lock_path, "a+")
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file.seek(0)
            lock_file.truncate(0)
            lock_file.write(str(os.getpid()))
            lock_file.flush()
            return lock_file
        except OSError:
            return None


def main():
    # Redirect stdout/stderr to a local log file to capture Finder launch errors first
    log_path = get_log_path()

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception as e:
        try:
            print(f"Warning: Failed to redirect output to log file {log_path}: {e}", file=sys.stderr)
        except Exception:
            pass

    print("\n--- Application Launch Attempt ---")

    # Single-instance lock via platform-native methods
    global _lock_handle
    _lock_handle = _acquire_instance_lock()
    if _lock_handle is None:
        print("Warning: Another instance of PDF Parser Light is already running. Exiting.")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            root.lift()
            root.attributes("-topmost", True)
            messagebox.showwarning("PDF Parser Light", "PDF Parser Light is already running.\n\nPlease close the existing instance or check Activity Monitor / Task Manager.")
            root.destroy()
        except Exception as e:
            print(f"Error showing instance lock warning: {e}")
        sys.exit(0)

    try:
        try:
            ctk.set_appearance_mode("System")
        except Exception as e:
            print(f"Warning: Could not set System appearance mode ({e}), falling back to Dark.")
            try:
                ctk.set_appearance_mode("Dark")
            except Exception:
                pass

        try:
            ctk.set_default_color_theme("blue")
        except Exception as e:
            print(f"Warning: Could not set blue color theme ({e}).")

        app = App()
        app.update_idletasks()
        app.update()
        app.mainloop()
    except Exception as e:
        print(f"CRITICAL RUNTIME ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
