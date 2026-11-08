# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
/***************************************************************************
 Wind Site Select
                                 A QGIS plugin
 GIS-based Wind Energy Site Selection
                             -------------------
        begin                : 2025-06-11
        copyright            : (C) 2025 by Mehrdad Fard
        email                : greensite.ai@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.

 Package identifier: wind_site_select
 Public display name: Wind Site Select
 Internal module entry: wind_suitability.WindSuitability (stable technical name)
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load the Wind Site Select plugin class.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .wind_suitability import WindSuitability
    return WindSuitability(iface)
