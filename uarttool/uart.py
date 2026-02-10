#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import threading
import queue
from time import sleep
import serial

from uarttool.utils import convert_cmd_to_bytes, parse_bytes_to_hex_str, get_str_info


class UartController:
    def __init__(self, port: str, baudrate: int, hex_mode=False, timeout=0.1, write_timeout=1, print_str=False, end=None):
        self.ser = self.__open_serial(port, baudrate, timeout, write_timeout)
        self.last_sent_ts = 0
        self.hex_mode = hex_mode
        self.print_str = print_str
        self.log_queue = queue.Queue()
        self.end = bytes(end, 'utf-8').decode('unicode_escape') if end else None
        self.stop_event = threading.Event()

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
            pass
        except Exception:
            pass

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
                    print(hex_str)
                if print_str_flag or not hex_mode:
                    txt = get_str_info(data)
                    if txt:
                        print(txt, end='')
            except Exception:
                pass
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

    def run_no_stdin(self):
        self.__start_rx_thread()

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

