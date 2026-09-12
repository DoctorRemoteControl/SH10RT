#!/bin/sh
# Finder launcher for macOS. Keep the terminal open after a startup error.
SH10RT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 2
/bin/sh "$SH10RT_ROOT/sh10rt.sh" "$@"
SH10RT_EXIT=$?
if [ "$#" -eq 0 ] && [ "$SH10RT_EXIT" -ne 0 ] && [ -t 0 ]; then
    printf '\nPress Enter to close...'
    read -r SH10RT_REPLY
fi
exit "$SH10RT_EXIT"
