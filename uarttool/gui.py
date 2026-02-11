#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import tkinter as tk
import os
import traceback
from datetime import datetime
import queue
import threading
import re
from tkinter import ttk, messagebox, filedialog
from typing import Optional
from tkinter import font as tkfont

from serial.tools import list_ports

from uarttool.uart import UartController
from uarttool.utils import convert_cmd_to_bytes, parse_bytes_to_hex_str, get_str_info
from uarttool.cli import register_exit_handler


class UartTab(ttk.Frame):
    def __init__(self, app: "UartGuiApp", notebook: ttk.Notebook, label: str):
        super().__init__(notebook)
        self.app = app
        self.notebook = notebook
        self.label = label
        self.mono_font = self._init_mono_font()
        self.app.apply_global_font(self.mono_font)
        self.rx_font_size = tk.IntVar(value=12)

        self.controller: Optional[UartController] = None
        self.tx_history = []
        self.tx_history_index = 0
        self.rx_thread_stop = None
        self.rx_update_pending = False
        self.rx_gui_queue = queue.Queue()
        self.ansi_carry = ""
        self.rx_autoscroll = True
        self.rx_force_scroll_once = False
        self._rx_internal_scroll = False

        self._build_ui()
        self._apply_rx_font_size()
        self.rx_default_fg = self.rx_text.cget("foreground")
        try:
            self.rx_default_disabled_fg = self.rx_text.cget("disabledforeground")
        except tk.TclError:
            self.rx_default_disabled_fg = None
        self._refresh_ports()
        self._set_connected(False)
        self._apply_hex_child_state()
        self._apply_rx_color()
        self.bind("<<RxData>>", self._on_rx_event)

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Port").pack(side=tk.LEFT)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=24, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Refresh", command=self._refresh_ports).pack(side=tk.LEFT)

        ttk.Label(top, text="Baud").pack(side=tk.LEFT, padx=(14, 0))
        self.baud_var = tk.StringVar(value="115200")
        self.baud_entry = ttk.Combobox(
            top,
            textvariable=self.baud_var,
            width=10,
            values=[
                "1200",
                "2400",
                "4800",
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
                "230400",
                "460800",
                "500000",
                "576000",
                "921600",
                "1000000",
                "1152000",
                "1500000",
                "2000000",
                "3000000",
                "4000000",
            ],
        )
        self.baud_entry.configure(state="normal")
        self.baud_entry.pack(side=tk.LEFT, padx=6)

        self.connect_btn = ttk.Button(top, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side=tk.LEFT, padx=(10, 0))


        cfg = ttk.Labelframe(main, text="Options", padding=10)
        cfg.pack(fill=tk.X, pady=(10, 0))

        self.hex_var = tk.BooleanVar(value=False)
        self.print_str_var = tk.BooleanVar(value=False)

        self.hex_chk = ttk.Checkbutton(cfg, text="Hex Mode", variable=self.hex_var, command=self._on_hex_toggle)
        self.hex_chk.pack(side=tk.LEFT)
        self.print_str_chk = ttk.Checkbutton(cfg, text="Print String", variable=self.print_str_var, command=self._on_print_str_toggle)
        self.print_str_chk.pack(side=tk.LEFT, padx=10)

        ttk.Label(cfg, text="Timeout").pack(side=tk.LEFT, padx=(14, 0))
        self.timeout_var = tk.StringVar(value="0.1")
        self.timeout_entry = ttk.Entry(cfg, textvariable=self.timeout_var, width=8)
        self.timeout_entry.pack(side=tk.LEFT, padx=6)

        ttk.Label(cfg, text="Write Timeout").pack(side=tk.LEFT, padx=(14, 0))
        self.wtimeout_var = tk.StringVar(value="1.0")
        self.wtimeout_entry = ttk.Entry(cfg, textvariable=self.wtimeout_var, width=8)
        self.wtimeout_entry.pack(side=tk.LEFT, padx=6)

        ttk.Label(cfg, text="End").pack(side=tk.LEFT, padx=(14, 0))
        self.end_var = tk.StringVar(value="\\r")
        self.end_entry = ttk.Combobox(
            cfg,
            textvariable=self.end_var,
            width=8,
            values=["", "\\r", "\\n", "\\r\\n", "\\t", "\\0"],
        )
        self.end_entry.configure(state="normal")
        self.end_entry.pack(side=tk.LEFT, padx=6)
        self.end_entry.bind("<<ComboboxSelected>>", lambda _e: self._on_end_change())
        self.end_entry.bind("<KeyRelease>", lambda _e: self._on_end_change())

        ttk.Label(cfg, text="Poll ms").pack(side=tk.LEFT, padx=(14, 0))
        self.poll_ms_var = tk.StringVar(value="50")
        self.poll_ms_entry = ttk.Entry(cfg, textvariable=self.poll_ms_var, width=6)
        self.poll_ms_entry.pack(side=tk.LEFT, padx=6)

        ttk.Label(cfg, text="RX Font").pack(side=tk.LEFT, padx=(14, 0))
        self.rx_font_entry = ttk.Spinbox(
            cfg,
            from_=8,
            to=24,
            width=4,
            textvariable=self.rx_font_size,
            command=self._apply_rx_font_size,
        )
        self.rx_font_entry.pack(side=tk.LEFT, padx=6)
        self.rx_font_entry.bind("<KeyRelease>", lambda _e: self._apply_rx_font_size())

        # encoding + ANSI/CR-BS normalization use defaults (no UI)
        self.encoding_var = tk.StringVar(value="utf-8")
        self.strip_ansi_var = tk.BooleanVar(value=True)
        self.normalize_ctrl_var = tk.BooleanVar(value=True)

        ttk.Label(cfg, text="RX Color").pack(side=tk.LEFT, padx=(14, 0))
        self.rx_color_var = tk.StringVar(value="Default")
        self.rx_color_entry = ttk.Combobox(
            cfg,
            textvariable=self.rx_color_var,
            width=10,
            values=["Default", "Black", "Blue", "Green", "Orange", "Red", "Gray"],
            state="readonly",
        )
        self.rx_color_entry.pack(side=tk.LEFT, padx=6)
        self.rx_color_entry.bind("<<ComboboxSelected>>", lambda _e: self._apply_rx_color())

        io = ttk.Frame(main)
        io.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        rx_frame = ttk.Labelframe(io, text="", padding=4)
        rx_frame.pack(fill=tk.BOTH, expand=True)

        rx_header = ttk.Frame(rx_frame)
        rx_header.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(rx_header, text="RX Log").pack(side=tk.LEFT)
        ttk.Button(rx_header, text="Export", command=self._export_rx).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(rx_header, text="Clear", command=self._clear_rx).pack(side=tk.RIGHT)

        self.rx_text = tk.Text(rx_frame, wrap="word", height=18, state="disabled", font=self.mono_font)
        self.rx_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rx_scroll = ttk.Scrollbar(rx_frame, command=self._on_rx_scrollbar)
        rx_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.rx_text.configure(yscrollcommand=rx_scroll.set)
        self.rx_text.bind("<MouseWheel>", self._on_rx_user_scroll)
        self.rx_text.bind("<Button-4>", self._on_rx_user_scroll)
        self.rx_text.bind("<Button-5>", self._on_rx_user_scroll)
        self.rx_text.bind("<KeyRelease>", self._on_rx_user_scroll)

        tx_frame = ttk.Labelframe(io, text="TX", padding=4)
        tx_frame.pack(fill=tk.X, pady=(10, 0))

        self.tx_var = tk.StringVar()
        self.tx_entry = ttk.Entry(tx_frame, textvariable=self.tx_var, font=self.mono_font)
        self.tx_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.tx_entry.bind("<Return>", lambda _e: self._send_tx())
        self.tx_entry.bind("<Up>", self._on_tx_history_up)
        self.tx_entry.bind("<Down>", self._on_tx_history_down)
        ttk.Button(tx_frame, text="Send", command=self._send_tx).pack(side=tk.LEFT, padx=6)

        note = ttk.Label(main, text="Tip: Select RX text and press Ctrl+C to copy selection.")
        note.pack(anchor="w", pady=(8, 0))

    def _init_mono_font(self):
        candidates = ["DejaVu Sans Mono", "Consolas", "Cascadia Mono", "Courier New"]
        available = set(tkfont.families())
        for name in candidates:
            if name in available:
                return tkfont.Font(family=name, size=10)
        return tkfont.Font(family="TkFixedFont", size=10)

    def _set_connected(self, connected: bool):
        state = "disabled" if connected else "normal"
        self.port_combo.configure(state="disabled" if connected else "readonly")
        self.baud_entry.configure(state=state)
        self.hex_chk.configure(state="normal")
        self.print_str_chk.configure(state="normal")
        self.timeout_entry.configure(state=state)
        self.wtimeout_entry.configure(state=state)
        # end can be toggled while connected
        self.end_entry.configure(state="normal")
        self.poll_ms_entry.configure(state=state)
        # encoding/strip/normalize are fixed defaults (no UI)
        self.connect_btn.configure(text="Disconnect" if connected else "Connect")
        self.hex_var.set(self.hex_var.get())
        self.print_str_var.set(self.print_str_var.get())
        self._apply_hex_child_state()

    def _refresh_ports(self):
        ports = []
        for p in list_ports.comports():
            ports.append(p.device)
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        if self.controller:
            self._disconnect()
        else:
            self._connect()

    def clone_settings_from(self, other: "UartTab"):
        self.port_var.set(other.port_var.get())
        self.baud_var.set(other.baud_var.get())
        self.timeout_var.set(other.timeout_var.get())
        self.wtimeout_var.set(other.wtimeout_var.get())
        self.hex_var.set(other.hex_var.get())
        self.print_str_var.set(other.print_str_var.get())
        self.end_var.set(other.end_var.get())
        self.poll_ms_var.set(other.poll_ms_var.get())
        self.rx_color_var.set(other.rx_color_var.get())
        self._apply_hex_child_state()
        self._apply_rx_color()

    def _connect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("UART Tool", "Please select a port.")
            return
        try:
            baud = int(self.baud_var.get().strip())
            timeout = float(self.timeout_var.get().strip())
            wtimeout = float(self.wtimeout_var.get().strip())
        except ValueError:
            messagebox.showerror("UART Tool", "Invalid baudrate/timeout value.")
            return

        try:
            self.controller = UartController(
                port=port,
                baudrate=baud,
                hex_mode=self.hex_var.get(),
                timeout=timeout,
                write_timeout=wtimeout,
                print_str=self.print_str_var.get(),
                end=self.end_var.get(),
            )
            self.controller.run_no_stdin()
        except Exception as e:
            self.controller = None
            self.app.log_error("open_port", e)
            messagebox.showerror("UART Tool", f"Open port failed: {e}\nDetails in uarttool_gui_error.log")
            return

        self._start_rx_thread()
        self._set_connected(True)
        self.app.rename_tab(self, port)

    def _disconnect(self):
        if self.controller:
            try:
                self.controller.stop()
            except Exception:
                pass
        self.controller = None
        if self.rx_thread_stop is not None:
            self.rx_thread_stop.set()
        self.rx_thread_stop = None
        self._set_connected(False)

    def _send_tx(self):
        if not self.controller:
            messagebox.showwarning("UART Tool", "Not connected.")
            return
        text = self.tx_var.get()
        self._push_history(text)
        self._send_payload(text)
        # Treat the next RX chunk as the response to latest TX and follow to bottom once.
        self.rx_force_scroll_once = True
        self.tx_var.set("")
        self.tx_history_index = len(self.tx_history)

    def _send_payload(self, text: str):
        end_str = self.end_var.get()
        if self.controller.hex_mode:
            try:
                tokens = text.replace(",", " ").split()
                if not tokens:
                    payload = b""
                else:
                    payload = convert_cmd_to_bytes(tokens)
                if payload is None:
                    return
                if end_str:
                    payload += bytes(end_str, "utf-8").decode("unicode_escape").encode("utf-8")
                self.controller.send_cmd(payload)
            except Exception as e:
                messagebox.showerror("UART Tool", f"Send hex failed: {e}")
        else:
            if end_str:
                text = text + bytes(end_str, "utf-8").decode("unicode_escape")
            self.controller.send_cmd(text)

    def _apply_rx_font_size(self):
        try:
            size = int(self.rx_font_size.get())
            size = max(8, min(24, size))
        except Exception:
            return
        self.mono_font.configure(size=size)
        self.rx_text.configure(font=self.mono_font)
        self.tx_entry.configure(font=self.mono_font)

    def _on_end_change(self):
        if self.controller:
            end_str = self.end_var.get()
            self.controller.end = bytes(end_str, "utf-8").decode("unicode_escape") if end_str else None

    def _on_hex_toggle(self):
        if not self.hex_var.get():
            self.print_str_var.set(False)
        self._apply_hex_child_state()
        if self.controller:
            self.controller.hex_mode = self.hex_var.get()
            self.controller.print_str = self.print_str_var.get()

    def _on_print_str_toggle(self):
        if self.controller:
            self.controller.print_str = self.print_str_var.get()

    def _apply_hex_child_state(self):
        if self.hex_var.get():
            self.print_str_chk.configure(state="normal")
        else:
            self.print_str_chk.configure(state="disabled")

    def _start_rx_thread(self):
        if not self.controller:
            return
        if self.rx_thread_stop is not None:
            self.rx_thread_stop.set()
        self.rx_thread_stop = threading.Event()
        ctrl = self.controller
        stop_evt = self.rx_thread_stop

        def _worker():
            while not stop_evt.is_set():
                try:
                    data = ctrl.log_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                batch = [data]
                try:
                    while True:
                        batch.append(ctrl.log_queue.get_nowait())
                except queue.Empty:
                    pass
                try:
                    self.rx_gui_queue.put_nowait(batch)
                except queue.Full:
                    pass
                try:
                    self.event_generate("<<RxData>>", when="tail")
                except Exception:
                    pass

        t = threading.Thread(target=_worker, daemon=True, name="uart-gui-rx")
        t.start()

    def _on_rx_event(self, _event):
        if self.rx_update_pending:
            return
        self.rx_update_pending = True
        self.after(self._get_poll_ms(), self._flush_rx_queue)

    def _get_poll_ms(self):
        try:
            v = int(self.poll_ms_var.get().strip())
            return max(10, min(1000, v))
        except Exception:
            return 50

    def _flush_rx_queue(self):
        self.rx_update_pending = False
        if not self.controller:
            return
        hex_mode = self.controller.hex_mode
        print_str = self.controller.print_str
        chunks = []
        try:
            while True:
                batch = self.rx_gui_queue.get_nowait()
                for data in batch:
                    if hex_mode:
                        chunks.append(parse_bytes_to_hex_str(data) + "\n")
                    if print_str or not hex_mode:
                        txt = self._decode_bytes(data)
                        if txt:
                            chunks.append(txt)
        except queue.Empty:
            pass
        if chunks:
            self._append_rx("".join(chunks))

    def _append_rx(self, text: str):
        self.rx_text.configure(state="normal")
        self.rx_text.insert(tk.END, text)
        should_scroll = self.rx_autoscroll or self.rx_force_scroll_once
        if should_scroll:
            self._rx_internal_scroll = True
            self.rx_text.see(tk.END)
            self._rx_internal_scroll = False
            self.rx_autoscroll = True
            self.rx_force_scroll_once = False
        self.rx_text.configure(state="disabled")

    def _clear_rx(self):
        self.rx_text.configure(state="normal")
        self.rx_text.delete("1.0", tk.END)
        self.rx_text.configure(state="disabled")
        self.rx_autoscroll = True
        self.rx_force_scroll_once = False

    def _export_rx(self):
        port = self.port_var.get().strip() or "uart"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{port}_{ts}.log"
        path = filedialog.asksaveasfilename(
            title="Export RX Log",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("Log Files", "*.log"), ("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.rx_text.configure(state="normal")
            data = self.rx_text.get("1.0", tk.END)
            self.rx_text.configure(state="disabled")
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception as e:
            messagebox.showerror("UART Tool", f"Export failed: {e}")

    def _apply_rx_color(self):
        name = self.rx_color_var.get()
        color_map = {
            "Default": None,
            "Black": "#000000",
            "Blue": "#1f4aa8",
            "Green": "#1a7f37",
            "Orange": "#c05600",
            "Red": "#b42318",
            "Gray": "#5b5b5b",
        }
        color = color_map.get(name, None)
        if color is None:
            self.rx_text.configure(foreground=self.rx_default_fg)
            if self.rx_default_disabled_fg is not None:
                self.rx_text.configure(disabledforeground=self.rx_default_disabled_fg)
        else:
            self.rx_text.configure(foreground=color)
            try:
                self.rx_text.configure(disabledforeground=color)
            except tk.TclError:
                pass

    def _decode_bytes(self, data: bytes) -> str:
        enc = self.encoding_var.get().strip() or "utf-8"
        try:
            text = data.decode(enc, errors="ignore")
        except Exception:
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                return ""
        if self.strip_ansi_var.get():
            text = self._strip_ansi_with_carry(text)
        if self.normalize_ctrl_var.get():
            text = self._normalize_cr_bs(text)
        return text

    def _strip_ansi_with_carry(self, text: str) -> str:
        if self.ansi_carry:
            text = self.ansi_carry + text
            self.ansi_carry = ""
        # If trailing ESC sequence is incomplete, keep it for next chunk
        last_esc = text.rfind("\x1b")
        if last_esc != -1:
            tail = text[last_esc:]
            if not self._ansi_sequence_complete(tail):
                self.ansi_carry = tail
                text = text[:last_esc]
        return self._strip_ansi(text)

    def _ansi_sequence_complete(self, text: str) -> bool:
        if not text.startswith("\x1b"):
            return True
        patterns = [
            r"^\x1B\[[0-?]*[ -/]*[@-~]",  # CSI ... Cmd
            r"^\x1B\][^\x07]*(?:\x07|\x1B\\)",  # OSC ... BEL or ST
            r"^\x1B[@-Z\\-_]",  # 2-byte sequences
            r"^\x1B7",  # DECSC
            r"^\x1B8",  # DECRC
        ]
        for pat in patterns:
            if re.match(pat, text):
                return True
        return False

    def _strip_ansi(self, text: str) -> str:
        # CSI and OSC sequences
        ansi_re = re.compile(
            r"\x1B\[[0-?]*[ -/]*[@-~]|"  # CSI ... Cmd
            r"\x1B\][^\x07]*(?:\x07|\x1B\\)|"  # OSC ... BEL or ST
            r"\x1B[@-Z\\-_]|"  # 2-byte sequences
            r"\x1B7|\x1B8"  # DECSC/DECRC
        )
        text = ansi_re.sub("", text)
        # Normalize stray carriage returns
        text = text.replace("\r\n", "\n")
        return text

    def _normalize_cr_bs(self, text: str) -> str:
        # Remove carriage returns and apply backspaces in-place
        text = text.replace("\r", "")
        out = []
        for ch in text:
            if ch == "\b":
                if out:
                    out.pop()
            else:
                out.append(ch)
        return "".join(out)

    def _push_history(self, text: str):
        if self.tx_history and self.tx_history[-1] == text:
            return
        self.tx_history.append(text)
        if len(self.tx_history) > 200:
            self.tx_history = self.tx_history[-200:]
        self.tx_history_index = len(self.tx_history)

    def _on_tx_history_up(self, _event):
        if not self.tx_history:
            return "break"
        if self.tx_history_index > 0:
            self.tx_history_index -= 1
        self.tx_var.set(self.tx_history[self.tx_history_index])
        self.tx_entry.icursor(tk.END)
        return "break"

    def _on_tx_history_down(self, _event):
        if not self.tx_history:
            return "break"
        if self.tx_history_index < len(self.tx_history) - 1:
            self.tx_history_index += 1
            self.tx_var.set(self.tx_history[self.tx_history_index])
        else:
            self.tx_history_index = len(self.tx_history)
            self.tx_var.set("")
        self.tx_entry.icursor(tk.END)
        return "break"

    def _on_rx_scrollbar(self, *args):
        self.rx_text.yview(*args)
        if not self._rx_internal_scroll:
            self._update_rx_autoscroll_state()

    def _on_rx_user_scroll(self, event=None):
        # Wheel up means user intent to inspect history; stop auto-follow
        # immediately so incoming RX data does not snap view back to bottom.
        if event is not None:
            num = getattr(event, "num", None)
            delta = getattr(event, "delta", 0)
            is_scroll_up = (num == 4) or (delta > 0)
            if is_scroll_up:
                self.rx_autoscroll = False
        self.after_idle(self._update_rx_autoscroll_state)

    def _update_rx_autoscroll_state(self):
        if self._rx_internal_scroll:
            return
        try:
            _first, last = self.rx_text.yview()
            self.rx_autoscroll = float(last) >= 0.999
        except Exception:
            self.rx_autoscroll = True

    def on_close(self):
        self._disconnect()


class UartGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("UART Tool")
        self.root.geometry("980x680")
        self.root.minsize(820, 520)

        self.global_font = None
        self.exit_requested = False

        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(container, padding=6)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="New Tab", command=self._new_tab).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Close Tab", command=self._close_current_tab).pack(side=tk.LEFT, padx=6)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tabs = []
        self._new_tab()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _new_tab(self):
        tab = UartTab(self, self.notebook, label=f"Tab {len(self.tabs) + 1}")
        self.tabs.append(tab)
        self.notebook.add(tab, text=tab.label)
        self.notebook.select(tab)

    def create_tab(self) -> UartTab:
        tab = UartTab(self, self.notebook, label=f"Tab {len(self.tabs) + 1}")
        self.tabs.append(tab)
        self.notebook.add(tab, text=tab.label)
        return tab

    def select_tab(self, tab: UartTab):
        self.notebook.select(tab)

    def rename_tab(self, tab: UartTab, name: str):
        idx = self.notebook.index(tab)
        self.notebook.tab(idx, text=name)

    def log_error(self, tag: str, err: Exception):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("uarttool_gui_error.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {tag}: {err}\n")
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception:
            pass

    def apply_global_font(self, font_obj: tkfont.Font):
        if self.global_font is not None:
            return
        self.global_font = font_obj
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
        ):
            try:
                tkfont.nametofont(name).configure(family=font_obj.cget("family"), size=font_obj.cget("size"))
            except Exception:
                pass

    def _on_close(self):
        for tab in self.tabs:
            tab.on_close()
        self.root.destroy()

    def request_exit(self):
        if self.exit_requested:
            return
        self.exit_requested = True
        try:
            self._on_close()
        except Exception:
            pass
        try:
            self.root.after(200, lambda: os._exit(0))
        except Exception:
            os._exit(0)

    def _close_current_tab(self):
        if not self.tabs:
            return
        current = self.notebook.select()
        if not current:
            return
        for tab in list(self.tabs):
            if str(tab) == current:
                tab.on_close()
                idx = self.notebook.index(tab)
                self.notebook.forget(tab)
                self.tabs.remove(tab)
                if self.tabs:
                    self.notebook.select(self.tabs[min(idx, len(self.tabs) - 1)])
                break


def run_gui():
    root = tk.Tk()
    app = UartGuiApp(root)
    register_exit_handler(app.request_exit)

    # Hard-exit on Ctrl+C/Ctrl+Break in Windows console
    if os.name == "nt":
        try:
            import ctypes

            CTRL_C_EVENT = 0
            CTRL_BREAK_EVENT = 1
            HANDLER = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

            def _console_handler(ctrl_type):
                if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
                    app.request_exit()
                return False

            run_gui._console_handler = HANDLER(_console_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(run_gui._console_handler, True)
        except Exception:
            pass

    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.request_exit()
