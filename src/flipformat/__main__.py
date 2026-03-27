"""
Allow running as: python -m flipformat

This works on every OS without needing the Scripts/ directory on PATH.
"""

import sys
import os

if __name__ == "__main__":
    from flipformat.cli import main
    main()
