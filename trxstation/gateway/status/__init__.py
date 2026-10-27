# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Publication de l'état de la passerelle (fichier lu par le superviseur et trx-monitor)."""
from .publisher import StatusPublisher

__all__ = ["StatusPublisher"]
