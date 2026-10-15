"""The Windows client must not drag the speech-engine stack in at import time.

The `client` extra deliberately omits faster-whisper/torch, so an accidental
import of the server or engine from client code would crash a client-only
install (and bloat the PyInstaller bundle).
"""

import json
import subprocess
import sys

HEAVY = ["torch", "faster_whisper", "ctranslate2",
         "wispr_dragon.engine", "wispr_dragon.server", "wispr_dragon.ui"]


def test_client_app_import_stays_lean():
    code = (
        "import json, sys; import wispr_dragon.client.app; "
        f"print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=120, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []
