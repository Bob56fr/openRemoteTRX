# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Point d'entrée de l'EXE d'openRemoteTRX-Autotest (mode B), compilé par scripts/build_autotest_exe.py."""
import sys

from trxstation.autotest.main import main

sys.exit(main())
