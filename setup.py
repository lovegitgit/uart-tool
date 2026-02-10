#!/usr/bin/env python3

from setuptools import setup, find_packages
import os


this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name='uart-tool',
    version='0.0.7',
    description='uart 工具',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author="nobitaqaq",
    author_email="xiaoleigs@gmail.com",
    keywords=["uart", "uart-tool"],
    packages=find_packages(include=['uarttool']),
    entry_points={
        'console_scripts': [
            'uart-tool = uarttool.cli:main',
            'lsuart = uarttool.cli:list_serial_ports',
        ]
    },
    python_requires=">=3.8",
    install_requires=[
        'pyserial',
    ],
)
