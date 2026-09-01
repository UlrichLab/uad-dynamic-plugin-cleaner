#!/usr/bin/env python3
"""Dynamic, safe cleanup assistant for Universal Audio plug-ins on macOS."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

def invoking_user() -> pwd.struct_passwd:
    sudo_uid = os.environ.get("SUDO_UID", "")
    if os.geteuid() == 0 and sudo_uid.isdigit():
        return pwd.getpwuid(int(sudo_uid))
    return pwd.getpwuid(os.getuid())


INVOKING_USER = invoking_user()
USER_HOME = Path(INVOKING_USER.pw_dir)
HELPER_URL = "http://127.0.0.1:4793/auth/plugins/cloud/user"
UAD_METER_BINARY = Path("/Applications/Universal Audio/UAD Meter & Control Panel.app/Contents/MacOS/UAD Meter & Control Panel")
GENERATED_PROFILE = USER_HOME / "Desktop" / "UADSystemProfile.txt"
DEFAULT_ALLOWLIST = Path(__file__).with_name("uad-static-fallback-allowlist.txt")
SYSTEM_PLUGIN_DIRS = (
    Path("/Library/Audio/Plug-Ins/Components"),
    Path("/Library/Audio/Plug-Ins/VST"),
    Path("/Library/Audio/Plug-Ins/VST3"),
    Path("/Library/Application Support/Avid/Audio/Plug-Ins"),
)
USER_PLUGIN_DIRS = (
    USER_HOME / "Library/Audio/Plug-Ins/Components",
    USER_HOME / "Library/Audio/Plug-Ins/VST",
    USER_HOME / "Library/Audio/Plug-Ins/VST3",
    USER_HOME / "Library/Application Support/Avid/Audio/Plug-Ins",
)
VALID_SUFFIXES = {".component", ".vst", ".vst3", ".aaxplugin"}


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class HelperPlugin:
    plugin_id: str
    name: str
    license_state: str
    licensed: bool
    names: tuple[str, ...]


@dataclass(frozen=True)
class DiskPlugin:
    plugin_id: str
    plugin_type: str
    local_name: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class UAD2Authorization:
    name: str
    status: str
    licensed: bool


@dataclass(frozen=True)
class Decision:
    path: str
    action: str
    reason: str


def property_value(properties: dict[str, Any], key: str, default: Any = None) -> Any:
    item = properties.get(key)
    return item.get("value", default) if isinstance(item, dict) else default


def normalize_name(value: str) -> str:
    value = Path(value).name
    value = re.sub(r"\.(?:component|vst|vst3|aaxplugin)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(m\)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:uad|uaudio)[\s._-]+", "", value, flags=re.IGNORECASE)
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_helper_plugin(plugin_id: str, payload: dict[str, Any]) -> HelperPlugin:
    props = payload.get("data", {}).get("properties", {})
    name = str(property_value(props, "plugin_name", "") or "")
    state = str(property_value(props, "license_state", "") or "")
    licenses = property_value(props, "cloud_licenses", []) or []
    manifest = property_value(props, "manifest", {}) or {}
    has_qualifying_license = any(
        isinstance(license_, dict)
        and license_.get("name") == "full"
        and license_.get("is_demo") is False
        and license_.get("deposit_status") == "deposited"
        for license_ in licenses
    )
    names = [name]
    if isinstance(manifest, dict):
        names.append(str(manifest.get("name", "") or ""))
        short_names = manifest.get("short_names", []) or []
        if isinstance(short_names, list):
            names.extend(str(item) for item in short_names if item)
    normalized = tuple(sorted({normalize_name(item) for item in names if normalize_name(item)}))
    return HelperPlugin(plugin_id, name, state, state == "full_active" and has_qualifying_license, normalized)


def read_helper(base_url: str, timeout: float) -> list[HelperPlugin]:
    root = get_json(base_url, timeout)
    children = root.get("data", {}).get("children", [])
    if not isinstance(children, list):
        raise SafetyError("UA Helper returned no valid plug-in list")
    results: list[HelperPlugin] = []
    for child in children:
        plugin_id = child.get("path") if isinstance(child, dict) else None
        if not plugin_id or "/" in plugin_id or plugin_id in {".", ".."}:
            continue
        detail_url = base_url.rstrip("/") + "/" + urllib.parse.quote(plugin_id, safe="")
        results.append(parse_helper_plugin(plugin_id, get_json(detail_url, timeout)))
    if not results:
        raise SafetyError("UA Helper returned an empty plug-in list; refusing to classify files")
    return results


def disk_helper_url(cloud_url: str) -> str:
    marker = "/auth/plugins/"
    if marker not in cloud_url:
        raise SafetyError("Cannot derive the UA Helper disk inventory URL")
    return cloud_url.split(marker, 1)[0] + marker + "disk"


def parse_disk_plugin(plugin_id: str, payload: dict[str, Any]) -> DiskPlugin:
    props = payload.get("data", {}).get("properties", {})
    plugin_type = str(property_value(props, "plugin_type", "") or "")
    plugin_name = str(property_value(props, "plugin_name", "") or "")
    manifest = property_value(props, "manifest", {}) or {}
    names = [plugin_name]
    if isinstance(manifest, dict):
        for key in ("name", "meter_display_name"):
            names.append(str(manifest.get(key, "") or ""))
        for key in ("shortNames", "short_names"):
            values = manifest.get(key, []) or []
            if isinstance(values, list):
                names.extend(str(item) for item in values if item)
    normalized = tuple(sorted({normalize_name(item) for item in names if normalize_name(item)}))
    return DiskPlugin(plugin_id, plugin_type, normalize_name(plugin_name), normalized)


def read_disk_plugins(cloud_url: str, timeout: float) -> list[DiskPlugin]:
    base_url = disk_helper_url(cloud_url)
    root = get_json(base_url, timeout)
    children = root.get("data", {}).get("children", [])
    if not isinstance(children, list):
        return []
    results: list[DiskPlugin] = []
    for child in children:
        plugin_id = child.get("path") if isinstance(child, dict) else None
        if not plugin_id or "/" in plugin_id or plugin_id in {".", ".."}:
            continue
        detail_url = base_url.rstrip("/") + "/" + urllib.parse.quote(plugin_id, safe="")
        plugin = parse_disk_plugin(plugin_id, get_json(detail_url, timeout))
        if plugin.plugin_type.casefold() == "uad2":
            results.append(plugin)
    return results


def parse_uad2_profile(content: str) -> list[UAD2Authorization]:
    in_section = False
    results: list[UAD2Authorization] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if "UAD-2 Plug-in Authorizations" in line:
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("---"):
            break
        if ":" not in line:
            continue
        name, status = (part.strip() for part in line.rsplit(":", 1))
        if name and status:
            results.append(UAD2Authorization(name, status, status.casefold().startswith("authorized for")))
    if not results:
        raise SafetyError("UAD-2 authorization section is missing or empty")
    if all(item.status.casefold() == "no uad-2 devices found" for item in results):
        raise SafetyError("No UAD-2 devices found; connect and power on Apollo/UAD-2 hardware or use --uad2-profile with a current profile")
    return results


def explicitly_negative_uad2_status(status: str) -> bool:
    normalized = status.casefold().strip()
    return (
        normalized.startswith("demo")
        or normalized.startswith("not authorized")
        or normalized.startswith("unauthorized")
        or normalized.startswith("auth update required")
    )


def explicitly_negative_helper_state(state: str) -> bool:
    return state.casefold().strip() in {"not_licensed", "demo_available"}


def generate_uad2_profile(binary: Path = UAD_METER_BINARY, profile_path: Path = GENERATED_PROFILE, timeout: float = 30.0) -> list[UAD2Authorization]:
    if not binary.is_file():
        return []
    if profile_path.exists():
        raise SafetyError(f"Move or rename the existing profile before automatic refresh: {profile_path}")
    process: subprocess.Popen[bytes] | None = None
    try:
        demote = None
        if os.geteuid() == 0 and INVOKING_USER.pw_uid != 0:
            def demote() -> None:
                os.initgroups(INVOKING_USER.pw_name, INVOKING_USER.pw_gid)
                os.setgid(INVOKING_USER.pw_gid)
                os.setuid(INVOKING_USER.pw_uid)
        child_env = os.environ.copy()
        child_env["HOME"] = str(USER_HOME)
        process = subprocess.Popen(
            [str(binary), "-gsp", "-quit"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=demote,
            env=child_env,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if profile_path.is_file() and profile_path.stat().st_size:
                return parse_uad2_profile(profile_path.read_text(encoding="utf-8", errors="replace"))
            if process.poll() is not None and process.returncode not in (0, None):
                break
            time.sleep(0.25)
        raise SafetyError("UAD Meter did not generate a current UAD-2 profile")
    finally:
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
        if profile_path.is_file():
            profile_path.unlink()


def load_allowlist(path: Path) -> set[str]:
    if not path.is_file():
        raise SafetyError(f"Allowlist not found: {path}")
    names = {
        normalize_name(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    names.discard("")
    return names


def scan_plugins(scan_dirs: Iterable[Path]) -> list[Path]:
    found: set[Path] = set()
    for directory in scan_dirs:
        if not directory.is_dir():
            continue
        for current, directory_names, _ in os.walk(directory, topdown=True, followlinks=False):
            for directory_name in list(directory_names):
                path = Path(current) / directory_name
                if path.suffix.casefold() not in VALID_SUFFIXES:
                    continue
                directory_names.remove(directory_name)
                if path.name.casefold().startswith(("uad ", "uaudio_")):
                    found.add(path)
    return sorted(found, key=lambda item: str(item).casefold())


def classify(
    paths: Iterable[Path],
    allowlist: set[str],
    helper: list[HelperPlugin],
    uad2_authorizations: Iterable[UAD2Authorization] = (),
    disk_plugins: Iterable[DiskPlugin] = (),
) -> list[Decision]:
    dynamic_names = {name for plugin in helper if plugin.licensed for name in plugin.names}
    explicitly_unlicensed_names = {
        name
        for plugin in helper
        if explicitly_negative_helper_state(plugin.license_state)
        for name in plugin.names
    }
    helper_by_id = {plugin.plugin_id.casefold(): plugin for plugin in helper}
    uad2_licensed = {normalize_name(item.name) for item in uad2_authorizations if item.licensed}
    uad2_unlicensed = {
        normalize_name(item.name)
        for item in uad2_authorizations
        if not item.licensed and explicitly_negative_uad2_status(item.status)
    }
    disk_by_local_name: dict[str, set[str]] = {}
    for plugin in disk_plugins:
        if plugin.local_name:
            disk_by_local_name.setdefault(plugin.local_name, set()).update(plugin.names)
    decisions: list[Decision] = []
    for path in paths:
        name = normalize_name(path.name)
        package_id = re.sub(r"\.(?:component|vst|vst3|aaxplugin)$", "", path.name, flags=re.IGNORECASE).casefold()
        direct_helper = helper_by_id.get(package_id)
        disk_names = disk_by_local_name.get(name, {name})
        if name in allowlist:
            decisions.append(Decision(str(path), "keep", "static DSP fallback allowlist"))
        elif direct_helper and direct_helper.licensed:
            decisions.append(Decision(str(path), "keep", "UA Helper package ID: verified full/deposited/non-demo license"))
        elif name in dynamic_names:
            decisions.append(Decision(str(path), "keep", "UA Helper: verified full/deposited/non-demo license"))
        elif disk_names & uad2_licensed:
            decisions.append(Decision(str(path), "keep", "UAD-2/Apollo: currently authorized on connected hardware"))
        elif direct_helper and explicitly_negative_helper_state(direct_helper.license_state):
            decisions.append(Decision(str(path), "candidate", "UA Helper package ID: explicitly not licensed or demo only"))
        elif name in explicitly_unlicensed_names:
            decisions.append(Decision(str(path), "candidate", "UA Helper: explicitly not licensed or demo only"))
        elif disk_names & uad2_unlicensed:
            decisions.append(Decision(str(path), "candidate", "UAD-2/Apollo: explicitly not authorized or demo only"))
        else:
            decisions.append(Decision(str(path), "unknown", "no conclusive Cloud or UAD-2 license; manual review required"))
    return decisions


def write_reports(report_dir: Path, helper: list[HelperPlugin], decisions: list[Decision], mode: str, helper_url: str, uad2_authorizations: Iterable[UAD2Authorization] = ()) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"uad-cleanup-{mode}-{stamp}.json"
    text_path = report_dir / f"uad-cleanup-{mode}-{stamp}.txt"
    document = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "helper_url": helper_url,
        "helper_plugins": [asdict(plugin) for plugin in helper],
        "uad2_authorizations": [asdict(item) for item in uad2_authorizations],
        "decisions": [asdict(decision) for decision in decisions],
    }
    json_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sections = []
    for action, heading in (("keep", "WOULD KEEP"), ("candidate", "REMOVE CANDIDATES"), ("unknown", "UNKNOWN / MANUAL REVIEW"), ("moved", "MOVED TO BACKUP")):
        rows = [f"{item.reason}\t{item.path}" for item in decisions if item.action == action]
        sections.append(f"===== {heading} =====\n" + ("\n".join(rows) if rows else "(none)"))
    unlicensed = [f"{p.plugin_id}\t{p.name}\t{p.license_state}" for p in helper if not p.licensed]
    sections.append("===== HELPER NOT QUALIFYING =====\n" + ("\n".join(unlicensed) if unlicensed else "(none)"))
    text_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return text_path, json_path


def move_candidates(decisions: list[Decision], backup_root: Path) -> list[Decision]:
    candidates = [item for item in decisions if item.action == "candidate"]
    if not candidates:
        return decisions
    if os.geteuid() != 0 and any(Path(item.path).is_relative_to("/Library") for item in candidates):
        raise SafetyError("System plug-ins require sudo; nothing was changed")
    backup_root.mkdir(parents=True, exist_ok=False)
    updated: list[Decision] = []
    candidate_paths = {item.path for item in candidates}
    for item in decisions:
        if item.path not in candidate_paths:
            updated.append(item)
            continue
        source = Path(item.path)
        if not source.exists() or source.is_symlink():
            raise SafetyError(f"Candidate changed or is a symlink; stopped before moving it: {source}")
        relative = Path(*source.parts[1:]) if source.is_absolute() else source
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        updated.append(Decision(str(source), "moved", f"backup: {destination}"))
    return updated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely preview or quarantine unlicensed UAD AU, VST2, VST3, and AAX plug-ins.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="preview only (default)")
    mode.add_argument("--delete", action="store_true", help="move candidates into a recoverable backup")
    parser.add_argument("--yes", action="store_true", help="required with --delete; confirms the displayed candidate set")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--report-dir", type=Path, default=USER_HOME / "Desktop" / "UAD Cleanup Reports")
    parser.add_argument("--backup-dir", type=Path, default=USER_HOME / "Desktop" / "UAD Cleanup Backups")
    parser.add_argument("--helper-url", default=HELPER_URL)
    parser.add_argument("--uad2-profile", type=Path, help="read an existing UADSystemProfile.txt instead of generating a fresh temporary profile")
    parser.add_argument("--skip-uad2", action="store_true", help="skip dynamic UAD-2/Apollo authorization detection")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--scan-dir", action="append", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.delete and not args.yes:
        raise SafetyError("--delete requires --yes after reviewing a preview; nothing was changed")
    scan_dirs = args.scan_dir or [*SYSTEM_PLUGIN_DIRS, *USER_PLUGIN_DIRS]
    try:
        helper = read_helper(args.helper_url, args.timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise SafetyError(f"UA Helper unavailable or invalid ({error}); nothing was changed") from error
    disk_plugins: list[DiskPlugin] = []
    uad2_authorizations: list[UAD2Authorization] = []
    if not args.skip_uad2:
        try:
            disk_plugins = read_disk_plugins(args.helper_url, args.timeout)
            if args.uad2_profile:
                uad2_authorizations = parse_uad2_profile(args.uad2_profile.read_text(encoding="utf-8", errors="replace"))
            else:
                uad2_authorizations = generate_uad2_profile(timeout=max(args.timeout, 30.0))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise SafetyError(f"UAD-2 authorization source unavailable ({error}); nothing was changed") from error
    allowlist = load_allowlist(args.allowlist)
    decisions = classify(scan_plugins(scan_dirs), allowlist, helper, uad2_authorizations, disk_plugins)
    candidates = [item for item in decisions if item.action == "candidate"]
    unknown = [item for item in decisions if item.action == "unknown"]
    preview_text, preview_json = write_reports(args.report_dir, helper, decisions, "preview", args.helper_url, uad2_authorizations)
    print(f"Installed UAD AU/VST2/VST3/AAX found: {len(decisions)}")
    print(f"Would keep: {sum(item.action == 'keep' for item in decisions)}")
    print(f"Remove candidates: {len(candidates)}")
    print(f"Unknown / manual review: {len(unknown)}")
    print(f"Current UAD-2/Apollo authorizations read: {len(uad2_authorizations)}")
    for item in candidates:
        print(f"  {item.path}")
    print(f"Report: {preview_text}\nData:   {preview_json}")
    if args.delete:
        backup = args.backup_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
        decisions = move_candidates(decisions, backup)
        delete_text, delete_json = write_reports(args.report_dir, helper, decisions, "delete", args.helper_url, uad2_authorizations)
        print(f"Moved to backup: {sum(item.action == 'moved' for item in decisions)}")
        print(f"Backup: {backup}\nReport: {delete_text}\nData:   {delete_json}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as error:
        print(f"Safety stop: {error}", file=sys.stderr)
        raise SystemExit(2)
