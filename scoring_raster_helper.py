# SPDX-License-Identifier: GPL-2.0-or-later
"""
Helper functions for raster scoring with improved error handling.
Addresses issues with raster calculator failures and disk space errors.
"""

import os
import shutil
from qgis.core import (
    QgsRasterLayer,
    QgsProcessingException,
    QgsMessageLog,
    Qgis,
    QgsRasterBandStats
)
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry


def cleanup_temp_files(directory, keep_recent=5):
    """
    Clean up temporary files in a directory, keeping only the most recent N files.
    
    Args:
        directory: Directory path to clean
        keep_recent: Number of recent files to keep (default: 5)
    """
    if not os.path.exists(directory):
        return
    
    try:
        files = []
        for f in os.listdir(directory):
            filepath = os.path.join(directory, f)
            if os.path.isfile(filepath):
                files.append((filepath, os.path.getmtime(filepath)))
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x[1], reverse=True)
        
        # Remove old files
        for filepath, _ in files[keep_recent:]:
            try:
                os.remove(filepath)
            except Exception:
                pass
    except Exception:
        pass


def check_disk_space(path, required_mb=100):
    """
    Check if there's enough disk space available.
    
    Args:
        path: Path to check disk space for
        required_mb: Required space in MB (default: 100)
        
    Returns:
        tuple: (has_space, available_mb, total_mb)
    """
    try:
        stat = shutil.disk_usage(os.path.dirname(path))
        available_mb = stat.free / (1024 * 1024)
        total_mb = stat.total / (1024 * 1024)
        has_space = available_mb >= required_mb
        
        return has_space, available_mb, total_mb
    except Exception:
        # Assume we have space if we can't check
        return True, 0, 0




