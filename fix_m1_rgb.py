#!/usr/bin/env python3
# Copyright 2021
# Author: Kevin Gao @sudowork
"""
Script that attempts to force M1 macs into RGB mode when used with monitors that
are defaulting to YPbPr.
No warranty provided for using this script. Use at your own risk.

Usage: ./fix_m1_rgb.py [--dry-run]
"""

from typing import Any, Dict, List, Optional

import json
import logging
import os
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET

_DRY_RUN = "--dry-run" in sys.argv


def main() -> None:
    if _DRY_RUN:
        logging.info("Running in Dry Run mode.")
    check_os()
    paths = get_possible_paths()
    logging.info("Looking for preferences in:\n" +
                 "\n".join(f"\t{path}" for path in paths))

    found_paths = [path for path in paths if os.path.exists(path)]
    if not found_paths:
        logging.warning(
            "Could not find any display preferences. "
            "Try rotating your screen in Display preferences to create the file."
        )
        sys.exit(1)

    for path in found_paths:
        logging.info(f"Found `{path}`.")
        fix_display_prefs(path)


def check_os() -> None:
    os_ver = subprocess.check_output(["sw_vers",
                                      "-productVersion"]).decode().strip()
    parts = os_ver.split(".")
    if parts[0] != "11":
        logging.error("Only tested to work on OS X 11 Big Sur.")
        sys.exit(1)
    if int(parts[1]) < 4:
        logging.error(f"Requires OS X 11.4 or higher (found {os_ver}). "
                      "Please update your OS first.")
        sys.exit(1)


def get_possible_paths() -> List[str]:
    relative_path_parts = [
        "Library", "Preferences", "com.apple.windowserver.displays.plist"
    ]
    paths = [
        os.path.join("/", *relative_path_parts),
        os.path.join(os.path.expanduser("~"), *relative_path_parts),
    ]
    host_uuid = get_host_uuid()
    if host_uuid:
        byhost_path = os.path.join(
            os.path.expanduser("~"), "Library", "Preferences", "ByHost",
            f"com.apple.windowserver.displays.{host_uuid}.plist")
        paths.append(byhost_path)
    return paths


def get_host_uuid() -> Optional[str]:
    output = subprocess.check_output(
        ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"]).decode()
    for line in output.splitlines():
        if "IOPlatformUUID" in line:
            return line.split(" ")[-1].strip('"')
    logging.warning("Could not identify Mac UUID")
    return None


def fix_display_prefs(path: str) -> None:
    backup(path)
    logging.info(f"Fixing {path}")
    try:
        xml = ET.fromstring(plutil_convert(path, "xml1"))
        json_data = json.loads(plutil_convert(path, "json"))
    except Exception as e:
        logging.error(f"Failed to fix {path}: {e}")

    if not has_any_link_description(json_data):
        logging.info(f"Skipping `{path}`. "
                     "No `LinkDescription` found in display config. "
                     "Try rotating your display from Display settings to "
                     "generate the field in the plist.")
        return

    # Get all configs with LinkDescription field
    configs_to_fix = list(xml.findall('.//dict[key="LinkDescription"]'))
    num_fixed = 0
    for config in configs_to_fix:
        uuid_elem = get_dict_value(config, "UUID")
        if uuid_elem is None:
            continue
        uuid = uuid_elem.text
        logging.info(f"Fixing config for Display {uuid}")
        fixed = fix_config(config)
        if fixed:
            logging.info(f"Fixed Display {uuid}")
            num_fixed += 1
        else:
            logging.info(f"Did not fix Display {uuid}. "
                         "Values for PixelEncoding and Range not as expected.")

    logging.info("Resulting XML output:")
    print(ET.tostring(xml).decode())

    write_output(path, xml)


def has_any_link_description(data: Dict[str, Any]) -> bool:
    # Checks for the presence of at least one LinkDescription field in a config.
    # This only gets written on OS X 11.4 and higher from testing.
    configs = data.get("DisplayAnyUserSets", {}).get("Configs", [])
    for config in configs:
        if config and config[0] and "LinkDescription" in config[0]:
            return True
    return False


def fix_config(config: ET.Element) -> bool:
    link_description_dict = get_dict_value(config, "LinkDescription")
    assert link_description_dict and link_description_dict.tag == "dict"

    pixel_encoding = get_dict_value(link_description_dict, "PixelEncoding")
    range = get_dict_value(link_description_dict, "Range")
    assert pixel_encoding is not None and range is not None

    if pixel_encoding.text != "1" or range.text != "0":
        return False
    pixel_encoding.text = "0"
    range.text = "1"
    return True


def get_dict_value(plist_dict: ET.Element, key: str) -> Optional[ET.Element]:
    prev_key: Optional[str] = None
    for elem in plist_dict.iter():
        if prev_key == key:
            return elem
        if elem.tag == "key":
            prev_key = elem.text
        else:
            prev_key = None
    return None


def write_output(path: str, xml: ET.Element) -> None:
    logging.info(f"Writing output to {path}")
    if not _DRY_RUN:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(ET.tostring(xml))
            tmp.flush()
            sudo = should_sudo(path)
            plutil_convert(tmp.name, "binary1", path, sudo=sudo)
        logging.info(f"Finished writing output to {path}")


def backup(path: str) -> None:
    ts = str(int(time.time()))
    backup_path = f"{path}.bak.{ts}"
    logging.info(f"Backing up file {path} -> {backup_path}")
    if not _DRY_RUN:
        # Use sudo for root
        backup_args = ["cp", "-v", path, backup_path]
        if should_sudo(path):
            subprocess.check_call(["sudo"] + backup_args)
        else:
            subprocess.check_call(backup_args)


def should_sudo(path: str) -> bool:
    return path.startswith("/Library")


def plutil_convert(path: str,
                   format: str,
                   output_path: str = None,
                   sudo: bool = False) -> bytes:
    # -o - will write to STDOUT
    if output_path is None:
        output_path = "-"
    args = ["plutil", "-convert", format, "-o", output_path, path]
    if sudo:
        args = ["sudo"] + args
    return subprocess.check_output(args)


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    main()
