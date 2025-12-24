#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import argparse
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

g_stop_event = threading.Event()

def signal_handler(sig, frame):
    g_stop_event.set()

signal.signal(signal.SIGINT, signal_handler)


COLOR_OUTPUT_STR = Fore.LIGHTBLUE_EX
COLOR_OUTPUT_HEX = Fore.LIGHTCYAN_EX
COLOR_DBG_MSG = Fore.LIGHTGREEN_EX
# Precompute hex table for fast conversion
HEX_TABLE = [f"0x{b:02x}" for b in range(256)]

def print_with_color_internal(color, text, end='\n'):
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
    def __init__(self, port: str, baudrate: int, hex_mode=False, timeout=3, print_str=False, end=None):
        self.ser = self.__open_serial(port, baudrate)
        self.last_sent_ts = 0
        self.hex_mode = hex_mode
        self.print_str = print_str
        self.ser.timeout = timeout
        self.is_sending = False
        self.log_queue = queue.Queue()
        self.end = bytes(end, 'utf-8').decode('unicode_escape') if end else None
        self.print_info()

    def send_cmd(self, cmd: bytes, test_mode=False):
        if not cmd or cmd == b'':
            return
        self.is_sending = True
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
        except Exception as e:
            print_dbg_msg(f'TX error: {e}')
        if test_mode:
            self.read_cmd_res()
        self.is_sending = False

    def read_cmd_res(self):
        try:
            response = self.ser.read(1024)
            if response:
                print_output_hex(parse_bytes_to_hex_str(response))
                if self.print_str or not self.hex_mode:
                    s = get_str_info(response)
                    if s:
                        print_output_str(s)
        except Exception as e:
            print_dbg_msg(f'RX error: {e}')

    def test(self):
        print_dbg_msg("Starting test!")
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd([0x5a, 0xa6], True)
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd([0x5a, 0xa6], True)
        print_dbg_msg('send [0x5a, 0xa6]')
        self.send_cmd([0x5a, 0xa6], True)
        print_dbg_msg('send [0x5A, 0xA4, 0x0C, 0x00, 0x4B, 0x33, 0x07, 0x00, 0x00, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]')
        self.send_cmd([0x5A, 0xA4, 0x0C, 0x00, 0x4B, 0x33, 0x07, 0x00, 0x00, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], True)
        print_dbg_msg('send [0x5a, 0xa1]')
        self.send_cmd([0x5a, 0xa1], False)

    def print_info(self):
        print_dbg_msg("UART Info:")
        print_dbg_msg(f"  Port: {self.ser.portstr}")
        print_dbg_msg(f"  Baudrate: {self.ser.baudrate}")
        print_dbg_msg(f"  Timeout: {self.ser.timeout}")
        print_dbg_msg(f"  Hex Mode: {self.hex_mode}")
        print_dbg_msg(f"  总是尝试打印字符串: {self.print_str}")
        if self.hex_mode:
            print_output_hex(f"  Output Hex: 0xff")
        if self.print_str or not self.hex_mode:
            print_output_str(f"  Output String: 0xff\n")

    def __open_serial(self, port, baudrate):
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=3)
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
        while not g_stop_event.is_set():
            try:
                waiting = getattr(ser, 'in_waiting', None)
                if waiting:
                    to_read = min(waiting, max_read)
                    data = ser.read(to_read)
                else:
                    data = ser.read(1024)
                if data:
                    try:
                        qput(data)
                    except queue.Full:
                        sleep(1e-3)
                else:
                    sleep(1e-3)
            except Exception:
                sleep(1e-3)
        self.stop()

    def log_serial_data(self):
        hex_mode = self.hex_mode
        print_str_flag = self.print_str
        while not g_stop_event.is_set():
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
        while not g_stop_event.is_set():
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

    def stop(self):
        g_stop_event.set()
        try:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.flush()
                except Exception:
                    pass
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
    parser = argparse.ArgumentParser(description='uart tool 参数')
    parser.add_argument('-p', '--com_port', type=str, required=True, help='COM 串口名字')
    parser.add_argument('-b', '--baurate', type=int, default=115200, help='COM 口波特率配置,默认115200')
    parser.add_argument('-t', '--timeout', type=float, default=0.1, help='COM 读写消息间隔,默认0.1')
    parser.add_argument('--hex_mode', action='store_true', default=False, help='是否使用16进制模式')
    parser.add_argument('--print_str', action='store_true', default=False, help='是否打印字符串模式')
    # allow `-e` with no value or explicit empty string to mean "no end/newline"
    parser.add_argument('-e', '--end', type=str, default='\r', nargs='?', const='', help=r"换行字符\r或者\n, 默认\r (使用 -e '' 或 -e 传空字符串表示不追加换行)")
    args = parser.parse_args()
    uart_controler = UartController(args.com_port, args.baurate, args.hex_mode, args.timeout, args.print_str, args.end)
    uart_controler.run()


if __name__ == '__main__':
    main()