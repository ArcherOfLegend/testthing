"""Compatibility shim.

The formats and the generic archive round-trip moved into the addon package as
`io_umvc3_css.mod`, so that the addon is one installable folder rather than a
handful of loose modules. Every headless script here still does

    sys.path.insert(0, TOOLS)
    import io_umvc3_mod as M

and this keeps that working: it re-exports the real module's namespace verbatim,
including the `_u16`/`_u32`/`_u64` helpers the scripts reach for by name.

Nothing mutates module attributes through `M`, so re-exporting by value rather
than proxying is safe. Import `io_umvc3_css.mod` directly in new code.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_umvc3_css import mod as _mod

globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})

del os, sys
