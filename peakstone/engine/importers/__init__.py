"""Importers that convert public benchmark suites into peakstone challenges.

Each importer reads an external benchmark in its native format and emits the
standard challenge layout (meta.toml + spec.md + tests/ + reference/) under
challenges/<suite>/, so the corpus loader and runner treat imported problems
identically to hand-authored ones. Once written, each challenge is pinned by
its content hash like any other.
"""
