#!/bin/sh
set -eu

FB_SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

: "${FB_CORNER:=max_ss_125C_4v50}"
: "${FB_MAX_ITERATIONS:=8}"
: "${FB_WORK_DIR:=/tmp/postroute_slew_feedback}"

fb_require_var()
{
    eval "fb_value=\${$1:-}"
    if [ -z "$fb_value" ]; then
        echo "ERROR: required environment variable $1 is not set" >&2
        exit 2
    fi
}

fb_require_file()
{
    if [ ! -f "$1" ]; then
        echo "ERROR: required file does not exist: $1" >&2
        exit 2
    fi
}

fb_append_lib_corner()
{
    fb_target=$1
    fb_var=$2
    fb_corner=$3
    fb_file=$4

    printf 'set ::env(%s) [list {%s}' \
        "$fb_var" "$fb_corner" >> "$fb_target"

    while IFS= read -r fb_lib
    do
        case "$fb_lib" in
            ""|\#*) continue ;;
        esac

        printf ' {%s}' "$fb_lib" >> "$fb_target"
    done < "$fb_file"

    printf ']\n' >> "$fb_target"
}

fb_append_excluded_cells()
{
    fb_target=$1

    if [ -z "${FB_PNR_EXCLUDED_CELLS_FILE:-}" ]; then
        return
    fi

    printf 'set ::env(_PNR_EXCLUDED_CELLS) [list' >> "$fb_target"

    while IFS= read -r fb_cell || [ -n "$fb_cell" ]
    do
        case "$fb_cell" in
            ""|\#*) continue ;;
        esac

        printf ' {%s}' "$fb_cell" >> "$fb_target"
    done < "$FB_PNR_EXCLUDED_CELLS_FILE"

    printf ']\n' >> "$fb_target"
}

fb_make_route()
{
    fb_iter=$1
    fb_iter_dir="$FB_WORK_DIR/iter_$fb_iter"
    fb_replay_dir="$fb_iter_dir/replay"
    fb_drt_dir="$fb_iter_dir/drt"
    fb_rcx_dir="$fb_iter_dir/rcx_max"

    mkdir -p \
        "$fb_replay_dir" \
        "$fb_drt_dir" \
        "$fb_rcx_dir"

    fb_replay_env="$fb_replay_dir/env.tcl"

    cat > "$fb_replay_env" <<EOT
source "$FB_PNR_ENV"

set ::env(CURRENT_ODB) "$FB_BASE_ODB"
set ::env(STEP_DIR) "$fb_replay_dir"

set ::env(ECO_PATCH) "$FB_CUMULATIVE_PATCH"

set ::env(PL_OPTIMIZE_MIRRORING) 0

set ::env(_SDC_IN) "$FB_SDC"

set ::env(SAVE_ODB) "$fb_replay_dir/chip_top.odb"
set ::env(SAVE_DEF) "$fb_replay_dir/chip_top.def"
EOT

    fb_append_lib_corner \
        "$fb_replay_env" \
        "_LIB_CORNER_0" \
        "$FB_PNR_CORNER" \
        "$FB_PNR_LIBS_FILE"

    fb_append_excluded_cells "$fb_replay_env"

    cat > "$fb_replay_dir/run.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_replay_env"

source "$FB_SELF_DIR/replay_and_grt.tcl"
EOT

    echo ""
    echo "===== FB iteration $fb_iter: replay + GRT ====="

    (
        cd "$fb_replay_dir"
        openroad -exit -no_splash run.tcl > replay.log 2>&1
    )

    fb_drt_env="$fb_drt_dir/env.tcl"

    cat > "$fb_drt_env" <<EOT
source "$FB_DRT_ENV"

set ::env(CURRENT_ODB) "$fb_replay_dir/chip_top.odb"

set ::env(STEP_DIR) "$fb_drt_dir"

# Feedback DRT must not overwrite the parent LibreLane step's
# netlist/SDC or other output views.
unset -nocomplain ::env(SAVE_NL)
unset -nocomplain ::env(SAVE_PNL)
unset -nocomplain ::env(SAVE_LOGICAL_NL)
unset -nocomplain ::env(SAVE_LOGICAL_PNL)
unset -nocomplain ::env(SAVE_SDC)
unset -nocomplain ::env(SAVE_SDF)
unset -nocomplain ::env(SAVE_SDF_PNL)
unset -nocomplain ::env(SAVE_OPENROAD_LEF)
unset -nocomplain ::env(SAVE_GUIDE)

set ::env(SAVE_ODB) "$fb_drt_dir/chip_top.odb"
set ::env(SAVE_DEF) "$fb_drt_dir/chip_top.def"

set ::env(_SDC_IN) "$FB_SDC"
EOT

    fb_append_lib_corner \
        "$fb_drt_env" \
        "_LIB_CORNER_0" \
        "$FB_PNR_CORNER" \
        "$FB_PNR_LIBS_FILE"

    fb_append_excluded_cells "$fb_drt_env"

    cat > "$fb_drt_dir/run.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_drt_env"

source "$SCRIPTS_DIR/openroad/drt.tcl"
EOT

    echo "===== FB iteration $fb_iter: DRT ====="

    (
        cd "$fb_drt_dir"
        openroad -exit -no_splash run.tcl > drt.log 2>&1
    )

    fb_rcx_env="$fb_rcx_dir/env.tcl"

    cat > "$fb_rcx_env" <<EOT
source "$FB_MAX_RCX_ENV"

set ::env(CURRENT_DEF) "$fb_drt_dir/chip_top.def"
set ::env(STEP_DIR) "$fb_rcx_dir"

unset -nocomplain ::env(SAVE_ODB)
unset -nocomplain ::env(SAVE_DEF)
unset -nocomplain ::env(SAVE_NL)
unset -nocomplain ::env(SAVE_PNL)
unset -nocomplain ::env(SAVE_LOGICAL_NL)
unset -nocomplain ::env(SAVE_LOGICAL_PNL)
unset -nocomplain ::env(SAVE_SDC)
unset -nocomplain ::env(SAVE_SDF)
unset -nocomplain ::env(SAVE_SDF_PNL)
unset -nocomplain ::env(SAVE_OPENROAD_LEF)
unset -nocomplain ::env(SAVE_GUIDE)

set ::env(SAVE_SPEF) "$fb_rcx_dir/chip_top.max.spef"
EOT

    cat > "$fb_rcx_dir/run.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_rcx_env"

source "$SCRIPTS_DIR/openroad/rcx.tcl"
EOT

    echo "===== FB iteration $fb_iter: MAX RCX ====="

    (
        cd "$fb_rcx_dir"
        openroad -exit -no_splash run.tcl > rcx.log 2>&1
    )

    FB_CURRENT_ODB="$fb_drt_dir/chip_top.odb"
    FB_CURRENT_DEF="$fb_drt_dir/chip_top.def"
    FB_CURRENT_SPEF="$fb_rcx_dir/chip_top.max.spef"
}

fb_check_current()
{
    fb_iter=$1
    fb_iter_dir="$FB_WORK_DIR/iter_$fb_iter"
    fb_check_dir="$fb_iter_dir/check"

    mkdir -p "$fb_check_dir"

    fb_netlist_env="$fb_check_dir/netlist_env.tcl"

    cat > "$fb_netlist_env" <<EOT
source "$FB_DRT_ENV"

set ::env(CURRENT_ODB) "$FB_CURRENT_ODB"
set ::env(_SDC_IN) "$FB_SDC"
EOT

    fb_append_lib_corner \
        "$fb_netlist_env" \
        "_LIB_CORNER_0" \
        "$FB_PNR_CORNER" \
        "$FB_PNR_LIBS_FILE"

    fb_append_excluded_cells "$fb_netlist_env"

    cat > "$fb_check_dir/write_netlist.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_netlist_env"

source "$SCRIPTS_DIR/openroad/common/io.tcl"

read_current_odb

write_verilog "$fb_check_dir/chip_top.nl.v"
EOT

    if ! (
        cd "$fb_check_dir"
        openroad -exit -no_splash write_netlist.tcl \
            > write_netlist.log 2>&1
    ); then
        echo "ERROR: failed to generate STA netlist; see $fb_check_dir/write_netlist.log" >&2
        exit 7
    fi

    if [ ! -s "$fb_check_dir/chip_top.nl.v" ]; then
        echo "ERROR: STA netlist was not produced: $fb_check_dir/chip_top.nl.v" >&2
        exit 7
    fi

    fb_sta_env="$fb_check_dir/sta_env.tcl"

    cat > "$fb_sta_env" <<EOT
source "$FB_MAXSS_ENV"

set ::env(_CURRENT_CORNER_NAME) "$FB_CORNER"
set ::env(_CURRENT_CORNER_NETLISTS) [list]

set ::env(CURRENT_NL) "$fb_check_dir/chip_top.nl.v"
set ::env(_CURRENT_SPEF_BY_CORNER) "$FB_CURRENT_SPEF"

set ::env(_SDC_IN) "$FB_SDC"
EOT

    fb_append_lib_corner \
        "$fb_sta_env" \
        "_CURRENT_CORNER_LIBS" \
        "" \
        "$FB_MAXSS_LIBS_FILE"

    # _CURRENT_CORNER_LIBS is not a corner-name-prefixed list.
    # Rewrite the line produced above into a plain Tcl list.
    sed -i \
        's#set ::env(_CURRENT_CORNER_LIBS) \[list {}#set ::env(_CURRENT_CORNER_LIBS) [list#' \
        "$fb_sta_env"

    cat > "$fb_check_dir/run_sta.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_sta_env"

source "$SCRIPTS_DIR/openroad/sta/corner.tcl"
EOT

    echo "===== FB iteration $fb_iter: extracted-RC STA ====="

    (
        cd "$fb_check_dir"
        sta -exit -no_splash run_sta.tcl > sta.log 2>&1
    )

    fb_sta_log="$fb_check_dir/sta.log"

    if ! grep -q 'max slew violation count' "$fb_sta_log"; then
        echo "ERROR: no max-slew metric found in $fb_sta_log" >&2
        exit 3
    fi

    FB_SLEW_COUNT=$(awk '
        /max slew violation count/ {
            value=$5
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    FB_CAP_COUNT=$(awk '
        /max cap violation count/ {
            value=$5
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    FB_SETUP_WS=$(awk '
        /timing__setup__ws__corner:/ {
            value=$NF
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    FB_HOLD_WS=$(awk '
        /timing__hold__ws__corner:/ {
            value=$NF
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    FB_SETUP_VIO=$(awk '
        /timing__setup_vio__count__corner:/ {
            value=$NF
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    FB_HOLD_VIO=$(awk '
        /timing__hold_vio__count__corner:/ {
            value=$NF
            found=1
        }
        END {
            if (!found) exit 1
            print value
        }
    ' "$fb_sta_log")

    awk '
        $0 == "max slew" {
            in_slew=1
            next
        }

        $0 == "max fanout" {
            if (in_slew) {
                exit
            }
        }

        in_slew && /\(VIOLATED\)/ {
            print $1
        }
    ' "$fb_sta_log" > "$fb_check_dir/slew_violators.txt"

    echo \
        "FB_STATUS iteration=$fb_iter slew=$FB_SLEW_COUNT cap=$FB_CAP_COUNT setup_ws=$FB_SETUP_WS hold_ws=$FB_HOLD_WS setup_vio=$FB_SETUP_VIO hold_vio=$FB_HOLD_VIO"

    if [ "$FB_SETUP_VIO" -ne 0 ] || [ "$FB_HOLD_VIO" -ne 0 ]; then
        echo "ERROR: setup/hold violation introduced by feedback loop" >&2
        exit 4
    fi

    if awk "BEGIN { exit !($FB_SETUP_WS < 0.0) }"; then
        echo "ERROR: negative setup slack: $FB_SETUP_WS" >&2
        exit 4
    fi

    if awk "BEGIN { exit !($FB_HOLD_WS < 0.0) }"; then
        echo "ERROR: negative hold slack: $FB_HOLD_WS" >&2
        exit 4
    fi

    if [ "$FB_SLEW_COUNT" -eq 0 ] && [ "$FB_CAP_COUNT" -eq 0 ]; then
        return 0
    fi

    return 1
}

fb_repair_current()
{
    fb_iter=$1
    fb_iter_dir="$FB_WORK_DIR/iter_$fb_iter"
    fb_repair_dir="$fb_iter_dir/repair"

    mkdir -p "$fb_repair_dir"

    fb_repair_env="$fb_repair_dir/env.tcl"

    cat > "$fb_repair_env" <<EOT
source "$FB_PNR_ENV"

set ::env(CURRENT_ODB) "$FB_CURRENT_ODB"

set ::env(_CURRENT_CORNER_NAME) "$FB_CORNER"
set ::env(_CURRENT_SPEF_BY_CORNER) "$FB_CURRENT_SPEF"

set ::env(_SDC_IN) "$FB_SDC"

set ::env(RSZ_DONT_TOUCH_RX) {\$^}

set ::env(FB_CORNER) "$FB_CORNER"
set ::env(FB_OUT_DIR) "$fb_repair_dir"
EOT

    fb_append_lib_corner \
        "$fb_repair_env" \
        "_LIB_CORNER_0" \
        "$FB_CORNER" \
        "$FB_MAXSS_LIBS_FILE"

    fb_append_excluded_cells "$fb_repair_env"

    cat > "$fb_repair_dir/run.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_repair_env"

source "$FB_SELF_DIR/repair_extracted.tcl"
EOT

    echo "===== FB iteration $fb_iter: repair_design ====="

    (
        cd "$fb_repair_dir"
        openroad -exit -no_splash run.tcl > repair.log 2>&1
    )

    fb_new_patch="$fb_repair_dir/new_patch.txt"

    fb_primary_count=$(awk 'NF >= 2 {n++} END {print n+0}' "$fb_new_patch")

    fb_after_slew="$fb_repair_dir/after_slew_violators.txt"

    awk '
        /^========== FB AFTER REPAIR ==========/ {
            after=1
            next
        }

        after && $0 == "max slew" {
            in_slew=1
            next
        }

        after && in_slew && /^max cap/ {
            in_slew=0
        }

        after && in_slew && /\(VIOLATED\)/ {
            print $1
        }
    ' "$fb_repair_dir/repair.log" > "$fb_after_slew"

    fb_residual_patch="$fb_repair_dir/residual_patch.txt"
    : > "$fb_residual_patch"

    # Do not mix ordinary core repairs and the non-core fallback
    # in the same physical iteration. First let repair_design settle
    # the core. Use the fallback only when repair_design itself made
    # no master changes.
    if [ "$fb_primary_count" -eq 0 ] && [ -s "$fb_after_slew" ]; then
        fb_residual_dir="$fb_repair_dir/residual"
        mkdir -p "$fb_residual_dir"

        fb_residual_env="$fb_residual_dir/env.tcl"

        cat > "$fb_residual_env" <<EOT
source "$FB_PNR_ENV"

set ::env(CURRENT_ODB) "$fb_repair_dir/repaired.odb"

set ::env(_CURRENT_CORNER_NAME) "$FB_CORNER"
set ::env(_CURRENT_SPEF_BY_CORNER) "$FB_CURRENT_SPEF"

set ::env(_SDC_IN) "$FB_SDC"

set ::env(FB_CORNER) "$FB_CORNER"
set ::env(FB_OUT_DIR) "$fb_residual_dir"
set ::env(FB_VIOLATOR_FILE) "$fb_after_slew"
EOT

        fb_append_lib_corner \
            "$fb_residual_env" \
            "_LIB_CORNER_0" \
            "$FB_CORNER" \
            "$FB_MAXSS_LIBS_FILE"

        fb_append_excluded_cells "$fb_residual_env"

        cat > "$fb_residual_dir/run.tcl" <<EOT
set ::env(SCRIPTS_DIR) "$SCRIPTS_DIR"
set ::env(_TCL_ENV_IN) "$fb_residual_env"

source "$FB_SELF_DIR/repair_residual_noncore.tcl"
EOT

        echo "===== FB iteration $fb_iter: residual non-core repair ====="

        (
            cd "$fb_residual_dir"
            openroad -exit -no_splash run.tcl > residual.log 2>&1
        )

        cp "$fb_residual_dir/residual_patch.txt" "$fb_residual_patch"
    fi

    fb_residual_count=$(awk 'NF >= 2 {n++} END {print n+0}' "$fb_residual_patch")

    echo \
        "FB_REPAIR_RESULT primary_changes=$fb_primary_count residual_changes=$fb_residual_count"

    if [ "$fb_primary_count" -eq 0 ] && [ "$fb_residual_count" -eq 0 ]; then
        echo "ERROR: violations remain but no repairable master change was found" >&2
        exit 5
    fi

    if [ "$fb_primary_count" -gt 0 ]; then
        "$FB_SELF_DIR/merge_patch.sh" \
            "$FB_CUMULATIVE_PATCH" \
            "$fb_new_patch" \
            "$FB_CUMULATIVE_PATCH"
    fi

    if [ "$fb_residual_count" -gt 0 ]; then
        "$FB_SELF_DIR/merge_patch.sh" \
            "$FB_CUMULATIVE_PATCH" \
            "$fb_residual_patch" \
            "$FB_CUMULATIVE_PATCH"
    fi

    echo "===== FB cumulative patch ====="
    cat "$FB_CUMULATIVE_PATCH"
}

for fb_cmd in openroad sta awk grep sed
do
    if ! command -v "$fb_cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found in PATH: $fb_cmd" >&2
        exit 127
    fi
done

fb_require_var SCRIPTS_DIR
fb_require_var FB_BASE_ODB
fb_require_var FB_PNR_ENV
fb_require_var FB_DRT_ENV
fb_require_var FB_MAX_RCX_ENV
fb_require_var FB_MAXSS_ENV
fb_require_var FB_PNR_CORNER
fb_require_var FB_PNR_LIBS_FILE
fb_require_var FB_MAXSS_LIBS_FILE
fb_require_var FB_SDC

fb_require_file "$FB_BASE_ODB"
fb_require_file "$FB_PNR_ENV"
fb_require_file "$FB_DRT_ENV"
fb_require_file "$FB_MAX_RCX_ENV"
fb_require_file "$FB_MAXSS_ENV"
fb_require_file "$FB_PNR_LIBS_FILE"
fb_require_file "$FB_MAXSS_LIBS_FILE"
fb_require_file "$FB_SDC"

if [ -n "${FB_PNR_EXCLUDED_CELLS_FILE:-}" ]; then
    fb_require_file "$FB_PNR_EXCLUDED_CELLS_FILE"
fi

rm -rf "$FB_WORK_DIR"
mkdir -p "$FB_WORK_DIR"

FB_CUMULATIVE_PATCH="$FB_WORK_DIR/cumulative_patch.txt"

if [ -n "${FB_INITIAL_PATCH:-}" ]; then
    fb_require_file "$FB_INITIAL_PATCH"
    cp "$FB_INITIAL_PATCH" "$FB_CUMULATIVE_PATCH"
else
    : > "$FB_CUMULATIVE_PATCH"
fi

fb_have_seed=0

if [ -n "${FB_SEED_DRT_ODB:-}" ] \
    || [ -n "${FB_SEED_DRT_DEF:-}" ] \
    || [ -n "${FB_SEED_MAX_SPEF:-}" ]; then

    if [ -z "${FB_SEED_DRT_ODB:-}" ] \
        || [ -z "${FB_SEED_DRT_DEF:-}" ] \
        || [ -z "${FB_SEED_MAX_SPEF:-}" ]; then
        echo \
            "ERROR: FB_SEED_DRT_ODB, FB_SEED_DRT_DEF and FB_SEED_MAX_SPEF must be supplied together" \
            >&2
        exit 2
    fi

    fb_require_file "$FB_SEED_DRT_ODB"
    fb_require_file "$FB_SEED_DRT_DEF"
    fb_require_file "$FB_SEED_MAX_SPEF"

    fb_have_seed=1
fi

FB_ITER=0

if [ "$fb_have_seed" -eq 1 ]; then
    mkdir -p "$FB_WORK_DIR/iter_0"

    FB_CURRENT_ODB="$FB_SEED_DRT_ODB"
    FB_CURRENT_DEF="$FB_SEED_DRT_DEF"
    FB_CURRENT_SPEF="$FB_SEED_MAX_SPEF"
else
    fb_make_route "$FB_ITER"
fi

while :
do
    if fb_check_current "$FB_ITER"; then
        echo ""
        echo "=============================================="
        echo "POST-ROUTE SLEW FEEDBACK CONVERGED"
        echo "iterations=$FB_ITER"
        echo "slew=$FB_SLEW_COUNT"
        echo "cap=$FB_CAP_COUNT"
        echo "setup_ws=$FB_SETUP_WS"
        echo "hold_ws=$FB_HOLD_WS"
        echo "final_odb=$FB_CURRENT_ODB"
        echo "final_def=$FB_CURRENT_DEF"
        echo "final_max_spef=$FB_CURRENT_SPEF"
        echo "patch=$FB_CUMULATIVE_PATCH"
        echo "=============================================="

        cat > "$FB_WORK_DIR/result.env" <<EOT
FB_RESULT=success
FB_ITERATIONS=$FB_ITER
FB_FINAL_ODB=$FB_CURRENT_ODB
FB_FINAL_DEF=$FB_CURRENT_DEF
FB_FINAL_MAX_SPEF=$FB_CURRENT_SPEF
FB_FINAL_PATCH=$FB_CUMULATIVE_PATCH
FB_FINAL_SLEW_COUNT=$FB_SLEW_COUNT
FB_FINAL_CAP_COUNT=$FB_CAP_COUNT
FB_FINAL_SETUP_WS=$FB_SETUP_WS
FB_FINAL_HOLD_WS=$FB_HOLD_WS
EOT

        exit 0
    fi

    if [ "$FB_ITER" -ge "$FB_MAX_ITERATIONS" ]; then
        echo \
            "ERROR: feedback did not converge within $FB_MAX_ITERATIONS repair iterations" \
            >&2
        exit 6
    fi

    fb_repair_current "$FB_ITER"

    FB_ITER=$((FB_ITER + 1))

    fb_make_route "$FB_ITER"
done
