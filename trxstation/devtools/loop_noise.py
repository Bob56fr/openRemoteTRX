"""Compatibilité : le gestionnaire vit maintenant dans trxstation.asyncio_noise."""
from ..asyncio_noise import install_quiet_handler as install_quiet_reset_handler  # noqa: F401
