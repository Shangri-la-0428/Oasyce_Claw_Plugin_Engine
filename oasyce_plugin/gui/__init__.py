"""
Oasyce GUI - Web-based dashboard for Oasyce nodes.

Usage:
    from oasyce_plugin.gui.app import OasyceGUI

    gui = OasyceGUI()
    gui.run()
"""

from .app import OasyceGUI

__all__ = ["OasyceGUI"]
