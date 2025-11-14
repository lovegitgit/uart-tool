#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import argparse
import functools
import threading
from typing import List
import serial
from serial.tools import list_ports
import queue
from threading import Lock
import signal

stop_event = threading.Event()

def signal_handler(sig, frame):
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)

from colorama import init, Fore, Style
# 初始化 colorama（Windows 下需要）
init(autoreset=True)

COLOR_OUTPUT_STR = Fore.LIGHTBLUE_EX
COLOR_OUTPUT_HEX = Fore.LIGHTCYAN_EX
COLOR_DBG_MSG = Fore.LIGHTGREEN_EX



# Global lock for synchronizing access to shared resources
globalLock = Lock()
def synchronized(func):
    """装饰器：让函数在同一时间只有一个线程能运行"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with globalLock:  # 加锁
            return func(*args, **kwargs)
    return wrapper

# 封装彩色打印函数
@synchronized
def cprintf(fmt, color=Fore.WHITE, *args, end='\n', **kwargs):
    """
    彩色打印函数（安全版）：
    - 只有在传入 args/kwargs 时才尝试使用 str.format
    - 否则直接将 fmt 转为字符串输出，避免因为未转义的大括号导致异常
    """
    try:
        if args or kwargs:
            # 仅在有格式参数时尝试 format，遇到异常回退到原始字符串
            try:
                text = str(fmt).format(*args, **kwargs)
            except Exception:
                text = str(fmt)
        else:
            text = str(fmt)
    except Exception:
        text = repr(fmt)
    print(f"{color}{text}{Style.RESET_ALL}", end=end)

def print_output_str(fmt, *args, **kwargs):
    """封装输出函数"""
    cprintf(fmt, COLOR_OUTPUT_STR, *args, end='', **kwargs)

def print_output_hex(fmt, *args, **kwargs):
    """封装输出十六进制函数"""
    cprintf(fmt, COLOR_OUTPUT_HEX, *args, **kwargs)

def print_dbg_msg(fmt, *args, **kwargs):
    """封装调试消息函数"""
    cprintf(fmt, COLOR_DBG_MSG, *args, **kwargs)

class UartController:
    def __init__(self, port: str, baudrate: int, hex_mode=False, timeout=3, print_str=False, no_end=False):
        self.ser = self.__open_serial(port, baudrate)
        self.last_sent_ts = 0
        self.hex_mode = hex_mode
        self.print_str = print_str
        self.ser.timeout = timeout
        self.is_sending = False
        self.log_queue = queue.Queue()
        self.no_end = no_end
        self.print_info()

    def send_cmd(self, cmd: bytes, test_mode=False):
        if not cmd:
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
                    print_output_str(get_str_info(response))
        except Exception as e:
            print('RX error:', e)

    def test(self):
        print("Starting test!")
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
            print_output_str(f"  Output String: 0xff")
        print_dbg_msg('')

    def __open_serial(self, port, baudrate):
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=3)
            if ser.is_open:
                return ser
        except Exception as e:
            raise(e)
        raise(RuntimeError('Cannot open port {}'.format(port)))

    def read_ser_response_continuously(self):
        while not stop_event.is_set():
            try:
                response = self.ser.read_all()
                if response:
                    self.log_queue.put_nowait(response)
            except Exception:
                pass
        self.stop()

    def log_serial_data(self):
        while not stop_event.is_set():
            try:
                data = self.log_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self.hex_mode:
                    print_output_hex(parse_bytes_to_hex_str(data))
                if self.print_str or not self.hex_mode:
                    print_output_str(get_str_info(data))
            except Exception as e:
                print_dbg_msg(f'log_serial_data error: {e}')
        self.stop()

    def trans_cmd_to_tx(self):
        while not stop_event.is_set():
            try:
                cmd = input()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd:
                real_cmds = '\n' if self.no_end else '\r'
            else:
                real_cmds = cmd + ('\n' if self.no_end else '\r')
            self.send_cmd(real_cmds)
        self.stop()

    def __start_rx_thread(self):
        rx_thread = threading.Thread(target=self.read_ser_response_continuously, daemon=True)
        rx_thread.start()

    def __start_tx_thread(self):
        tx_thread = threading.Thread(target=self.trans_cmd_to_tx)
        tx_thread.start()

    def __start_log_thread(self):
        log_thread = threading.Thread(target=self.log_serial_data, daemon=True)
        log_thread.start()

    def run(self):
        self.__start_rx_thread()
        self.__start_tx_thread()
        self.__start_log_thread()

    def stop(self):
        stop_event.set()
        try:
            if self.ser and self.ser.is_open:
                self.ser.flush()
                self.ser.close()
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
        return response.decode('utf-8')
    except:
        # print('decode RX[HEX] to String error!')
        pass
    return ''

def parse_bytes_to_hex_str(byte_data: bytes):
    return ' '.join(f"0x{byte:02x}" for byte in byte_data)


def parse_str_to_bytes(str_data: str):
    byte_data = [ord(chr(s)) for s in str_data]
    return ' '.join(f"0x{byte:02x}" for byte in byte_data)

def parse_bytes_to_bin(byte_data: bytes):
    binary = ''.join(format(byte, '08b') for byte in byte_data)
    return binary

def list_serial_ports():
    ports = []
    for p in list_ports.comports():
        uart_dsc = f' {p.device}: {p.description}'
        print_dbg_msg(uart_dsc)

def main():
    parser = argparse.ArgumentParser(description='uart tool 参数')
    parser.add_argument('-p', '--com_port', type=str, required = True, help='COM 串口名字')
    parser.add_argument('-b', '--baurate', type=int, default=115200, help='COM 口波特率配置,默认115200')
    parser.add_argument('-t', '--timeout', type=float, default=0.1, help='COM 读写消息间隔,默认0.1')
    parser.add_argument('--hex_mode', action='store_true', default=False, help='是否使用16进制模式')
    parser.add_argument('--print_str', action='store_true', default=False, help='是否打印字符串模式')
    parser.add_argument('--test_mode', action='store_true', default=False, help='是否进入测试模式')
    parser.add_argument('-ue', '--use_end', action='store_true', default=False, help=r'是否使用末尾字符: \n')
    args = parser.parse_args()
    uart_controler = UartController(args.com_port, args.baurate, args.hex_mode, args.timeout, args.print_str, args.use_end)
    if(args.test_mode):
        uart_controler.test()
    else:
        uart_controler.run()

if __name__ == '__main__':
    main()