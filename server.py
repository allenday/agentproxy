#!/usr/bin/env python3
"""
Backward compatibility shim for 'python server.py'.

This file maintains backward compatibility with the old entry point.
New installations should use 'sf-server' command or 'python -m sf.server' instead.
"""
import sys

if __name__ == "__main__":
    from sf.server import main
    sys.exit(main())
