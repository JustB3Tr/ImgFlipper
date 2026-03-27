"""
flipformat — Create, read, and manipulate .flip dual-sided image files.
"""

from flipformat.flip_file import FlipFile
from flipformat.autocrop import autocrop

__version__ = "1.0.0"
__all__ = ["FlipFile", "autocrop"]
