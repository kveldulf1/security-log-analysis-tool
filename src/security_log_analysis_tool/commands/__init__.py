"""Auto-discovered CLI subcommands.

Each module in this package exposes ``register(subparsers)`` which adds one
subcommand and wires its handler via ``set_defaults(func=...)``. ``cli.py``
discovers them at startup; adding a command means adding a file here, never
editing ``cli.py``.
"""
