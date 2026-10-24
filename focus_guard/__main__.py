import io
import sys

from .cli import main

for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):  # pythonw has no console streams
        stream.reconfigure(encoding="utf-8", errors="replace")

sys.exit(main())
