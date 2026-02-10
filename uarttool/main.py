#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import threading
from typing import List
import serial
from serial.tools import list_ports
import queue
import signal
from time import sleep
import sys
from colorama import init, Fore, Style
# 初始化 colorama（Windows 下需要）
init(autoreset=True)

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


COLOR_OUTPUT_STR = Fore.LIGHTBLUE_EX
COLOR_OUTPUT_HEX = Fore.LIGHTCYAN_EX
COLOR_DBG_MSG = Fore.LIGHTGREEN_EX
# Precompute hex table for fast conversion
HEX_TABLE = [f"0x{b:02x}" for b in range(256)]

def print_with_color_internal(color, text, end='\n'):
    if sys.stdout is None:
        return
    sys.stdout.write(f"{color}{text}{Style.RESET_ALL}")
    if end:
        sys.stdout.write(end)
    sys.stdout.flush()

def print_wrapper(fmt, color=Fore.WHITE, *args, end='\n', **kwargs):
    try:
        if args or kwargs:
            try:
                text = str(fmt).format(*args, **kwargs)
            except Exception:
                text = str(fmt)
        else:
            text = str(fmt)
    except Exception:
        text = repr(fmt)
    print_with_color_internal(color, text, end)


def print_output_str(fmt, *args, **kwargs):
    print_wrapper(fmt, COLOR_OUTPUT_STR, *args, **kwargs, end='')


def print_output_hex(fmt, *args, **kwargs):
    print_wrapper(fmt, COLOR_OUTPUT_HEX, *args, **kwargs)


def print_dbg_msg(fmt, *args, **kwargs):
    print_wrapper(fmt, COLOR_DBG_MSG, *args, **kwargs)


class UartController:
    def __init__(self, port: str, baudrate: int, hex_mode=False, timeout=0.05, write_timeout=1, print_str=False, end=None, test_mode=False):
        self.ser = self.__open_serial(port, baudrate, timeout, write_timeout)
        self.last_sent_ts = 0
        self.hex_mode = hex_mode
        self.print_str = print_str
        self.log_queue = queue.Queue()
        self.end = bytes(end, 'utf-8').decode('unicode_escape') if end else None
        self.test_mode = test_mode
        self.stop_event = threading.Event()
        if self.test_mode:
            self.hex_mode = True
            self.print_str = False
            print_dbg_msg('Uart Controller started in TEST MODE, only support send hex commands.')

    def send_cmd(self, cmd: bytes):
        if not cmd or cmd == b'':
            return
        if self.hex_mode:
            if isinstance(cmd, str):
                cmd = cmd.replace(',', '')
                cmd = cmd.split()
                cmd = convert_cmd_to_bytes(cmd)
        else:
            if isinstance(cmd, str):
                cmd = cmd.encode('utf-8')
        try:
            if cmd:
                self.ser.write(cmd)
                self.ser.flush()
        except serial.SerialTimeoutException:
            print_dbg_msg(f'TX timeout error: Write operation timed out.')
        except Exception as e:
            print_dbg_msg(f'TX error: {e}')

    def test(self):
        print_dbg_msg("Starting test!")
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd(bytes([0x5a, 0xa6]))
        # wait for response
        sleep(5e-1)
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd(bytes([0x5a, 0xa6]))
        sleep(5e-1)
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd(bytes([0x5a, 0xa6]))
        sleep(5e-1)
        print_dbg_msg('send [0x5A, 0xA4, 0x0C, 0x00, 0x4B, 0x33, 0x07, 0x00, 0x00, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]')
        self.send_cmd(bytes([0x5A, 0xA4, 0x0C, 0x00, 0x4B, 0x33, 0x07, 0x00, 0x00, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
        sleep(5e-1)
        print_dbg_msg('send [0x5a, 0xa1]')
        self.send_cmd(bytes([0x5a, 0xa1]))
        sleep(2e-1)

    def __open_serial(self, port, baudrate, timeout, write_timeout):
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout, write_timeout=write_timeout)
            if ser.is_open:
                return ser
        except Exception as e:
            raise e
        raise RuntimeError('Cannot open port {}'.format(port))

    def read_ser_response_continuously(self):
        ser = self.ser
        qput = self.log_queue.put_nowait
        # read max chunk size
        max_read = 4096
        while not self.stop_event.is_set():
            try:
                waiting = ser.in_waiting
                if waiting:
                    to_read = min(waiting, max_read)
                    data = ser.read(to_read)
                else:
                    data = ser.read(1024)  # block until at least 1 byte or timeout
                if data:
                    try:
                        qput(data)
                    except queue.Full:
                        sleep(1e-2)
            except Exception:
                sleep(1e-2)
        self.stop()

    def log_serial_data(self):
        hex_mode = self.hex_mode
        print_str_flag = self.print_str
        while not self.stop_event.is_set():
            try:
                data = self.log_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if hex_mode:
                    hex_str = parse_bytes_to_hex_str(data)
                    # hex lines should have newline
                    print_output_hex(hex_str)
                if print_str_flag or not hex_mode:
                    txt = get_str_info(data)
                    if txt:
                        print_output_str(txt)
            except Exception as e:
                print_dbg_msg(f'log_serial_data error: {e}')
        self.stop()

    def trans_cmd_to_tx(self):
        """
        Read from stdin and send. Input is string; append end (string) if configured.
        """
        while not self.stop_event.is_set():
            try:
                cmd = input()
            except (EOFError, KeyboardInterrupt):
                break
            # cmd is a str; if empty, send only end (if configured)
            if cmd == '':
                real_cmds = self.end if self.end else ''
            else:
                real_cmds = cmd + (self.end if self.end else '')
            self.send_cmd(real_cmds)
        self.stop()

    def __start_rx_thread(self):
        rx_thread = threading.Thread(target=self.read_ser_response_continuously, daemon=True, name="uart-rx")
        rx_thread.start()

    def __start_tx_thread(self):
        tx_thread = threading.Thread(target=self.trans_cmd_to_tx, daemon=True, name="uart-tx")
        tx_thread.start()

    def __start_log_thread(self):
        log_thread = threading.Thread(target=self.log_serial_data, name="uart-log")
        log_thread.start()

    def run(self):
        self.__start_rx_thread()
        self.__start_tx_thread()
        self.__start_log_thread()
        if self.test_mode:
            self.test()

    def run_no_stdin(self):
        self.__start_rx_thread()
        if self.test_mode:
            self.test()

    def stop(self):
        self.stop_event.set()
        try:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
        except Exception:
            pass


def convert_cmd_to_bytes(datas: List[hex]):
    try:
        tmp_data = ''.join(f'{int(str(data), 16):02x}' for data in datas)
        byte_data = bytes.fromhex(tmp_data)
        return byte_data
    except ValueError as e:
        print_dbg_msg(f'convert_cmd_to_bytes error: {e}')

def get_str_info(response: bytes):
    try:
        return response.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def parse_bytes_to_hex_str(byte_data: bytes):
    # Use lookup table for speed
    return ' '.join(HEX_TABLE[b] for b in byte_data)


def parse_str_to_bytes(str_data: str):
    # Encode then show hex bytes
    try:
        b = str_data.encode('utf-8')
        return ' '.join(f"0x{byte:02x}" for byte in b)
    except Exception:
        return ''

def list_serial_ports():
    for p in list_ports.comports():
        uart_dsc = f' {p.device}: {p.description}'
        print_dbg_msg(uart_dsc)

def main():
    from uarttool.gui import run_gui
    run_gui()


if __name__ == '__main__':
    main()
