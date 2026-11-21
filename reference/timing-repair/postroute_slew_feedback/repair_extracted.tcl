source "$::env(SCRIPTS_DIR)/openroad/common/io.tcl"
source "$::env(SCRIPTS_DIR)/openroad/common/resizer.tcl"

if {![info exists ::env(FB_OUT_DIR)]} {
    error "FB_OUT_DIR is not set"
}

if {![info exists ::env(FB_CORNER)]} {
    error "FB_CORNER is not set"
}

file mkdir $::env(FB_OUT_DIR)

read_current_odb

set block [ord::get_db_block]

array set master_before {}

foreach inst [$block getInsts] {
    set name [$inst getName]
    set master_before($name) [[$inst getMaster] getName]
}

set_propagated_clock [all_clocks]
set_dont_touch_objects

# Reads the extracted SPEF supplied through
# _CURRENT_SPEF_BY_CORNER.
read_spefs

puts ""
puts "========== FB BEFORE REPAIR =========="

report_check_types \
    -max_slew \
    -max_capacitance \
    -violators \
    -corner $::env(FB_CORNER)

puts ""
puts "========== FB REPAIR DESIGN =========="

repair_design \
    -verbose \
    -max_wire_length 0 \
    -slew_margin 0 \
    -cap_margin 10

unset_dont_touch_objects

set patch_file "$::env(FB_OUT_DIR)/new_patch.txt"
set patch_fp [open $patch_file w]

set changed 0

foreach inst [$block getInsts] {
    set name [$inst getName]
    set new_master [[$inst getMaster] getName]

    if {
        [info exists master_before($name)]
        && $master_before($name) ne $new_master
    } {
        puts "FB_MASTER_CHANGE $name : $master_before($name) -> $new_master"
        puts $patch_fp "$name $new_master"
        incr changed
    }
}

close $patch_fp

puts "FB_MASTER_CHANGE_COUNT $changed"
puts "FB_PATCH_FILE $patch_file"

puts ""
puts "========== FB AFTER REPAIR =========="

report_check_types \
    -max_slew \
    -max_capacitance \
    -violators \
    -corner $::env(FB_CORNER)

write_db "$::env(FB_OUT_DIR)/repaired.odb"
