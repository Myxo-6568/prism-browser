"""Shared persistent QWebEngine profile configuration."""

from __future__ import annotations

import platform
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings

CHROME_STABLE_MAJOR = 158


def _chrome_user_agent() -> str:
    """Return a reduced desktop Chrome user agent for the current OS."""
    system = platform.system()
    if system == "Darwin":
        platform_token = "Macintosh; Intel Mac OS X 10_15_7"
    elif system == "Windows":
        platform_token = "Windows NT 10.0; Win64; x64"
    else:
        platform_token = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_token}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_STABLE_MAJOR}.0.0.0 Safari/537.36"
    )


def create_web_profile(parent=None) -> QWebEngineProfile:
    """Create Prism's shared persistent profile in the OS app-data directory."""
    app_data = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    )
    storage_path = app_data / "web-profile"
    cache_path = app_data / "http-cache"
    storage_path.mkdir(parents=True, exist_ok=True)
    cache_path.mkdir(parents=True, exist_ok=True)

    profile = QWebEngineProfile("prism", parent)
    profile.setPersistentStoragePath(str(storage_path))
    profile.setCachePath(str(cache_path))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    profile.setHttpUserAgent(_chrome_user_agent())

    settings = profile.settings()
    for attribute in (
        QWebEngineSettings.WebAttribute.JavascriptEnabled,
        QWebEngineSettings.WebAttribute.LocalStorageEnabled,
        QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
        QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
    ):
        settings.setAttribute(attribute, True)
    return profile
