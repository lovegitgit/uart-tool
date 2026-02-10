#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

from typing import List

# Precompute hex table for fast conversion
HEX_TABLE = [f"0x{b:02x}" for b in range(256)]


def convert_cmd_to_bytes(datas: List[hex]):
    try:
        tmp_data = ''.join(f'{int(str(data), 16):02x}' for data in datas)
        byte_data = bytes.fromhex(tmp_data)
        return byte_data
    except ValueError:
        pass


def parse_bytes_to_hex_str(byte_data: bytes):
    # Use lookup table for speed
    return ' '.join(HEX_TABLE[b] for b in byte_data)


def get_str_info(response: bytes):
    try:
        return response.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def parse_str_to_bytes(str_data: str):
    # Encode then show hex bytes
    try:
        b = str_data.encode('utf-8')
        return ' '.join(f"0x{byte:02x}" for byte in b)
    except Exception:
        return ''
