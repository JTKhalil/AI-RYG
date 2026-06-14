"""通过 GitHub Releases 检查 CodingLight 更新。"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass

from app_paths import (
    APP_NAME,
    APP_VERSION,
    GITHUB_REPO,
    GITHUB_REPO_OWNER,
    SETUP_ASSET_NAME,
    update_check_cache_path,
)

UPDATE_CHECK_INTERVAL = 24 * 3600
_GITHUB_API = (
    f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO}/releases/latest"
)
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    download_url: str
    release_notes: str

    @property
    def has_update(self) -> bool:
        return is_newer(self.latest_version, self.current_version)


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    message: str
    info: UpdateInfo | None = None


def parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    main = cleaned.split("-", 1)[0]
    parts: list[int] = []
    for piece in main.split("."):
        match = re.match(r"(\d+)", piece)
        if match:
            parts.append(int(match.group(1)))
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def normalize_version(version: str) -> str:
    return version.strip().lstrip("vV")


def _load_cache() -> dict:
    path = update_check_cache_path()
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict) -> None:
    path = update_check_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _should_skip_check(force: bool) -> bool:
    if force:
        return False
    cache = _load_cache()
    last_check = float(cache.get("last_check", 0))
    return (time.time() - last_check) < UPDATE_CHECK_INTERVAL


def _pick_setup_asset(assets: list[dict]) -> str:
    for asset in assets:
        if asset.get("name") == SETUP_ASSET_NAME:
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url:
                return url
    return ""


def fetch_latest_release() -> UpdateInfo:
    request = urllib.request.Request(
        _GITHUB_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)

    tag_name = str(payload.get("tag_name", "")).strip()
    if not tag_name:
        raise ValueError("Release 缺少 tag_name")

    release_url = str(payload.get("html_url", "")).strip()
    assets = payload.get("assets")
    if not isinstance(assets, list):
        assets = []

    download_url = _pick_setup_asset(assets) or release_url
    notes = str(payload.get("body") or "").strip()
    if len(notes) > 500:
        notes = notes[:497] + "..."

    return UpdateInfo(
        current_version=APP_VERSION,
        latest_version=normalize_version(tag_name),
        release_url=release_url,
        download_url=download_url,
        release_notes=notes,
    )


def check_for_update(*, force: bool = False) -> UpdateCheckResult:
    with _cache_lock:
        if _should_skip_check(force):
            return UpdateCheckResult(ok=True, message="最近已检查过更新")

        try:
            info = fetch_latest_release()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return UpdateCheckResult(
                    ok=False,
                    message="GitHub 上尚无正式发布，请稍后再试。",
                )
            return UpdateCheckResult(
                ok=False,
                message=f"检查更新失败（HTTP {exc.code}）",
            )
        except urllib.error.URLError as exc:
            return UpdateCheckResult(ok=False, message=f"无法连接 GitHub：{exc.reason}")
        except (TimeoutError, ValueError, json.JSONDecodeError) as exc:
            return UpdateCheckResult(ok=False, message=f"检查更新失败：{exc}")

        cache = _load_cache()
        cache["last_check"] = time.time()
        cache["latest_version"] = info.latest_version
        _save_cache(cache)

        if info.has_update:
            return UpdateCheckResult(
                ok=True,
                message=f"发现新版本 {info.latest_version}",
                info=info,
            )
        return UpdateCheckResult(
            ok=True,
            message=f"当前已是最新版本（{APP_VERSION}）",
            info=info,
        )


def open_download_url(info: UpdateInfo) -> None:
    webbrowser.open(info.download_url or info.release_url)


def _show_message_box(title: str, message: str, flags: int = 0x40) -> int:
    import sys

    if sys.platform != "win32":
        print(f"{title}: {message}")
        return 1
    import ctypes

    return ctypes.windll.user32.MessageBoxW(0, message, title, flags)


def _ask_yes_no(title: str, message: str) -> bool:
    # MB_YESNO | MB_ICONQUESTION
    return _show_message_box(title, message, 0x24) == 6


def present_update_result(result: UpdateCheckResult, *, notify_if_available: bool) -> None:
    if not result.ok:
        if notify_if_available:
            return
        _show_message_box(APP_NAME, result.message, 0x10)
        return

    info = result.info
    if info and info.has_update:
        notes = f"\n\n{info.release_notes}" if info.release_notes else ""
        prompt = (
            f"发现新版本 {info.latest_version}（当前 {info.current_version}）。"
            f"{notes}\n\n是否打开下载页面？"
        )
        if _ask_yes_no(f"{APP_NAME} 更新", prompt):
            open_download_url(info)
        return

    if not notify_if_available:
        _show_message_box(APP_NAME, result.message)


def run_update_check_ui(*, force: bool = False, notify_if_available: bool = False) -> None:
    result = check_for_update(force=force)
    if result.message == "最近已检查过更新" and notify_if_available:
        return
    present_update_result(result, notify_if_available=notify_if_available)


def schedule_startup_update_check() -> None:
    thread = threading.Thread(
        target=run_update_check_ui,
        kwargs={"force": False, "notify_if_available": True},
        daemon=True,
        name="update-check",
    )
    thread.start()
