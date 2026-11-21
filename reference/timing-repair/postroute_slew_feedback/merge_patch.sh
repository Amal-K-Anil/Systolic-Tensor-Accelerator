#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 OLD_PATCH NEW_PATCH OUTPUT_PATCH" >&2
    exit 2
fi

OLD_PATCH=$1
NEW_PATCH=$2
OUTPUT_PATCH=$3

TMP="${OUTPUT_PATCH}.tmp"

awk '
{
    inst=$1
    master=$2

    if (inst == "" || master == "") {
        next
    }

    if (!(inst in seen)) {
        order[++n]=inst
        seen[inst]=1
    }

    latest[inst]=master
}
END {
    for (i=1; i<=n; i++) {
        inst=order[i]
        print inst, latest[inst]
    }
}
' "$OLD_PATCH" "$NEW_PATCH" > "$TMP"

mv "$TMP" "$OUTPUT_PATCH"
