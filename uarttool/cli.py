#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import signal
from serial.tools import list_ports


g_exit_callback = None


def register_exit_handler(fn):
    global g_exit_callback
    g_exit_callback = fn


def signal_handler(sig, frame):
    if g_exit_callback:
        try:
            g_exit_callback()
        except Exception:
            pass


signal.signal(signal.SIGINT, signal_handler)


def list_serial_ports():
    for p in list_ports.comports():
        uart_dsc = f' {p.device}: {p.description}'
        print(uart_dsc)


def main():
    from uarttool import gui
    gui.run_gui()


if __name__ == '__main__':
    main()
