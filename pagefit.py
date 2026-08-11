"""Compatibility shim - the page surface moved to `io_umvc3_css.pagefit`.

See `io_umvc3_mod.py` for why. `buildgrid.py` and `clearance.py` import this by
name; new code should import the package module directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_umvc3_css import pagefit as _pagefit

globals().update({k: v for k, v in vars(_pagefit).items() if not k.startswith("__")})

del os, sys
