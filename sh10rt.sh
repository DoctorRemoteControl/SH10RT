#!/bin/sh
# Linux launcher; also usable from a macOS terminal.
SH10RT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 2
for SH10RT_PYTHON in python3 python; do
    if command -v "$SH10RT_PYTHON" >/dev/null 2>&1 &&
       "$SH10RT_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        exec "$SH10RT_PYTHON" "$SH10RT_ROOT/scripts/launch_sh10rt.py" "$@"
    fi
done
echo 'Python 3.10 or later is required. Install Python, then run this launcher again.' >&2
exit 2
