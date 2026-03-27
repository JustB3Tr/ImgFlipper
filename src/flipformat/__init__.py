"""
flipformat — Create, read, and manipulate .flip dual-sided image files.
"""

from flipformat.flip_file import FlipFile
from flipformat.autocrop import autocrop, autocrop_pair
from flipformat.smartmeta import auto_label, estimate_size_and_type

__version__ = "1.2.0"
__all__ = ["FlipFile", "autocrop", "autocrop_pair", "auto_label", "estimate_size_and_type"]
