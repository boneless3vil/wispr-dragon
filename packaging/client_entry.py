"""PyInstaller entry point for the Wispr Dragon Windows client.

PyInstaller freezes a real script, not `python -m wispr_dragon.client`. The
package's own ``__main__.py`` uses a relative import (``from .app import main``)
that only resolves under ``-m``, so this shim imports absolutely instead.
"""

import sys

from wispr_dragon.client.app import main

if __name__ == "__main__":
    sys.exit(main())
