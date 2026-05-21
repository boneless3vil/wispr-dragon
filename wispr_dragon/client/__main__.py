"""Entry point for running Wispr Dragon client as a module."""

from .app import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
