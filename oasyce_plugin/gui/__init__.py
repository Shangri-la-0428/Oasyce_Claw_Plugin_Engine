"""
Oasyce GUI - Web-based dashboard for Oasyce nodes.

Usage:
    from oasyce_plugin.gui import OasyceGUI, set_global_state

    gui = OasyceGUI()
    gui.start(open_browser=True)
"""

from .server import OasyceGUI, set_global_state, OasyceHandler

__all__ = [
    "OasyceGUI",
    "set_global_state",
    "OasyceHandler",
]
