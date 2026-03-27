"""
flipformat — Create, read, and manipulate .flip dual-sided image files.
"""

from flipformat.flip_file import FlipFile
from flipformat.autocrop import autocrop, autocrop_pair

__version__ = "1.1.0"
__all__ = ["FlipFile", "autocrop", "autocrop_pair"]
