# fix_m1_rgb

Script that attempts to force M1 macs into RGB mode when used with monitors that
are defaulting to YPbPr.

No warranty provided for using this script. Use at your own risk.

## Instructions

### Prerequisites

1. Make sure you are on Mac OS X 11.4 or higher. Upgrade if you haven't.
1. Open System Preferences > Displays > Rotate the monitor that's in YPbPr
   mode in order to force it to write to the relevant plist file. You can
   unrotate it immediately or allow it to auto-revert.

### Running the Script

From your Terminal, run:

```bash
# Download the script
curl -o ~/Downloads/fix_m1_rgb.py https://raw.githubusercontent.com/sudowork/fix_m1_rgb/main/fix_m1_rgb.py
# Run a dry run and validate the results
python3 ~/Downloads/fix_m1_rgb.py --dry-run
# Once the results are validated, apply the changes.
python3 ~/Downloads/fix_m1_rgb.py
```

Restart your computer after you're done, and if all worked out well, then your monitor should be in RGB mode.

Note: The script will backup your original plist files. In addition, the script
does not try to discriminate between various displays, so it will write the
PixelEncoding and Range values for all displays with a LinkDescription field.

## Kudos

Kudos to [@GetVladimir](https://github.com/GetVladimir) for identifying the plist changes that need to be made.
