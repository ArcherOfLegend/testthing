"""Compatibility shim - the recovered card frame moved to
`io_umvc3_css.frame_data` so the addon ships it.

`import_portraits.py` and `fixportraits.py` import this by name. Regenerate with
`frame_template.py`, writing into the package copy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_umvc3_css import frame_data as _frame_data

globals().update({k: v for k, v in vars(_frame_data).items() if not k.startswith("__")})

del os, sys
