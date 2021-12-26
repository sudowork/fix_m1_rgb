#!/usr/bin/env python3
# Copyright 2021
# Author: Kevin Gao @sudowork
"""
Script that attempts to force M1 macs into RGB mode when used with monitors that
are defaulting to YPbPr.
No warranty provided for using this script. Use at your own risk.

Usage: ./fix_m1_rgb.py [--dry-run]
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional

import argparse
import collections
import curses
import curses.ascii
import datetime
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET

options: argparse.Namespace


def main() -> None:
    if options.dry_run:
        logging.info("Running in Dry Run mode.")
    check_os()
    paths = get_possible_paths()
    logging.info("Looking for preferences in:\n" +
                 "\n".join(f"\t{path}" for path in paths))

    found_paths = [path for path in paths if os.path.exists(path)]
    if not found_paths:
        logging.warning(
            "Could not find any display preferences. Try "
            "rotating your screen in Display preferences to create the file.")
        sys.exit(1)

    for path in found_paths:
        logging.info(f"Found `{path}`.")
        fix_display_prefs(path)

    # backup and remove ByHost file if exists
    byhost_path = get_byhost_path()
    if byhost_path and os.path.exists(byhost_path):
        logging.info(f"Found ByHost preferences at {byhost_path} - removing")
        backup(byhost_path)
        remove(byhost_path)
    else:
        logging.info("Did not find ByHost preferences")


def check_os() -> None:
    os_ver = subprocess.check_output(["sw_vers",
                                      "-productVersion"]).decode().strip()
    parts = os_ver.split(".")
    if parts[0] != "11":
        if parts[0] == "12":
            logging.warning(
                "This script has not fully been tested on OS X 12 Monterey.")
            if options.dry_run:
                return
            answer = input("Do you want to continue? [yN] ")
            if answer.strip().lower() == "y":
                return
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
    return [
        os.path.join("/", *relative_path_parts),
        os.path.join(os.path.expanduser("~"), *relative_path_parts),
    ]


def get_byhost_path() -> Optional[str]:
    host_uuid = get_host_uuid()
    if host_uuid:
        byhost_path = os.path.join(
            os.path.expanduser("~"), "Library", "Preferences", "ByHost",
            f"com.apple.windowserver.displays.{host_uuid}.plist")
        return byhost_path
    return None


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

    logging.info(f"Resulting XML output for `{path}`:")
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
    if not options.dry_run:
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
    if not options.dry_run:
        # Use sudo for root
        backup_args = ["cp", "-v", path, backup_path]
        if should_sudo(path):
            subprocess.check_call(["sudo"] + backup_args)
        else:
            subprocess.check_call(backup_args)


def remove(path: str) -> None:
    logging.info(f"Removing file {path}")
    if not options.dry_run:
        # Use sudo for root
        remove_args = ["rm", "-v", path]
        if should_sudo(path):
            subprocess.check_call(["sudo"] + remove_args)
        else:
            subprocess.check_call(remove_args)


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


def revert(stdscr: curses._CursesWindow) -> None:
    init_curses()
    backups_by_path = get_backup_locations()
    paths = list(backups_by_path.keys())

    selection = 0
    key = None
    while key != "q":
        # Redraw and handle key
        stdscr.clear()
        # Handle up-down navigation
        if key == "KEY_UP":
            selection = max(selection - 1, 0)
        if key == "KEY_DOWN":
            selection = min(selection + 1, len(backups_by_path) - 1)
        selected_path = paths[selection]
        if key == "\n":
            # Go to screen to restore backup
            restore_file(stdscr, selected_path, backups_by_path[selected_path])
            # Re-initialize backups_by_path since we may have new backups.
            backups_by_path = get_backup_locations()
            paths = list(backups_by_path.keys())

        # Print display
        stdscr.addstr("Select file to restore:\n")
        for index, (path, backups) in enumerate(backups_by_path.items()):
            selected = selection == index
            marker = "❯" if selected else " "
            num_backups = len(backups)
            stdscr.addstr(f"  {marker} {path} ({num_backups} backups)\n",
                          curses.color_pair(1) if selected else 0)
        stdscr.addstr("\n")
        stdscr.addstr(f"Press <Enter> to view backups for `{selected_path}`.\n")
        stdscr.addstr("Press 'q' to exit at any time.\n")

        key = stdscr.getkey()


def get_backup_locations() -> collections.OrderedDict[str, List[str]]:
    paths = get_possible_paths()
    backups_by_path = {path: get_backups(path) for path in paths}
    # Filter out files without backups
    backups_by_path = {
        path: backups for path, backups in backups_by_path.items() if backups
    }
    return collections.OrderedDict(backups_by_path)


def get_backups(path: str) -> List[str]:
    filepath = pathlib.Path(path)
    filename = os.path.split(filepath)[-1]
    directory = filepath.parent
    return [
        "/Users/kgao/Library/Preferences/ByHost/com.apple.windowserver.13369FFC-A6CC-5162-B380-00A9E5A7BDEA.plist.bak.1623016550"
    ]  # TODO: REMOVE ME
    return [str(path) for path in directory.glob(f"{filename}.bak.*")]


def restore_file(stdscr: curses._CursesWindow, path: str,
                 backup_paths: List[str]) -> None:
    selection = 0
    key = None
    while key != "q":
        # Redraw and handle key
        stdscr.clear()
        # Handle up-down navigation
        if key == "KEY_UP":
            selection = max(selection - 1, 0)
        if key == "KEY_DOWN":
            selection = min(selection + 1, len(backup_paths) - 1)
        if key in ("v", "\n"):
            view_xml(stdscr, backup_paths[selection])

        # Print display
        stdscr.addstr(f"Backups for {path}\n")
        for index, backup_path in enumerate(backup_paths):
            filename = os.path.split(backup_path)[-1]
            timestamp = filename.split(".")[-1]
            try:
                dt = datetime.datetime.fromtimestamp(int(timestamp))
                timestamp = dt.isoformat()
            except:
                pass

            marker = "↠" if selection == index else " "
            stdscr.addstr(f"  {marker} [{timestamp}] {filename}\n")

        stdscr.addstr("\n")
        stdscr.addstr("Press 'v' or <ENTER> to view the file as XML.\n")
        stdscr.addstr("Press 'j' to view the file as JSON.\n")
        stdscr.addstr("Press 'q' to return to previous screen.\n")

        key = stdscr.getkey()
    stdscr.clear()


def view_xml(stdscr: curses._CursesWindow, path: str) -> None:
    stdscr.clear()
    xml = plutil_convert(path, "xml1").decode()
    lines = xml.splitlines()
    display(stdscr, lines)


def display(stdscr: curses._CursesWindow, lines: List[str]) -> None:
    # Init pad
    width = max(len(line) for line in lines)
    height = len(lines)
    pad = curses.newpad(height, width)
    # Populate pad with content
    for i, line in enumerate(lines):
        pad.addstr(i, 0, line)
    stdscr.refresh()

    win_height, win_width = stdscr.getmaxyx()
    pad_left = 0
    pad_top = 0

    CTRL_U, CTRL_D, CTRL_B, CTRL_F = [
        curses.ascii.ctrl(ch) for ch in ("U", "D", "B", "F")
    ]

    key = None
    while key != "q":
        # Get dimensions again in case window has changed
        win_height, win_width = stdscr.getmaxyx()

        # Handle screen movement
        move_amount = 1
        # half- and full-page navigation
        if key in (CTRL_U, CTRL_D):
            move_amount = win_height // 2
        elif key in (CTRL_B, CTRL_F):
            move_amount = win_height // 2

        if key in ("KEY_UP", CTRL_U, CTRL_B):
            pad_top = max(0, pad_top - move_amount)
        elif key in ("KEY_DOWN", CTRL_D, CTRL_F):
            # Bound by end of content
            pad_top = min(height - win_height, pad_top + move_amount)
        elif key == "KEY_LEFT":
            pad_left = max(0, pad_left - move_amount)
        elif key == "KEY_RIGHT":
            # Bound by end of content
            pad_left = min(width - win_width, pad_left + move_amount)

        # Re-render pad content in screen
        win_start = (0, 0)
        # Leave 1 row for printing status line
        win_end = (win_height - 2, win_width - 1)
        pad.refresh(pad_top, pad_left, *win_start, *win_end)

        # Status line
        stdscr.addnstr(
            win_height - 1, 0,
            "'q' to return, arrows to move, ^D/^U scroll half-page, ^F/^B scroll full-page "
            + str(key), win_width - 1)

        key = stdscr.getkey()
    stdscr.clear()


def init_curses() -> None:
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s %(levelname)7s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser(
        description=("Script that attempts to force M1 Macs into RGB mode "
                     "when used with monitors that are defaulting to YPbPr."))
    parser.add_argument(
        "--dry-run",
        default=False,
        action="store_true",
        help="prints what would be done without modifying any files")
    parser.add_argument("command",
                        nargs="?",
                        choices=["revert"],
                        help=f"optionally run `{__file__} revert` to "
                        "restore from a backup")
    options = parser.parse_args()

    if options.command == "revert":
        curses.wrapper(revert)
    else:
        main()
