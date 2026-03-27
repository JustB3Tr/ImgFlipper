#!/usr/bin/env python3
"""
Zero-install entry point — works without pip install.

Usage:
    python run.py create --front front.jpg --back back.jpg -o card.flip
    python run.py info card.flip
    python run.py extract card.flip --outdir ./out
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flipformat.cli import main

main()
