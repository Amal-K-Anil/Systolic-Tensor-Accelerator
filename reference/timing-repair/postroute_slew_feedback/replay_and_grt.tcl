source "$::env(SCRIPTS_DIR)/openroad/common/io.tcl"

if {![info exists ::env(ECO_PATCH)]} {
    error "ECO_PATCH is not set"
}

if {![info exists ::env(SAVE_ODB)]} {
    error "SAVE_ODB is not set"
}

if {![info exists ::env(SAVE_DEF)]} {
    error "SAVE_DEF is not set"
}

read_current_odb

set block [ord::get_db_block]

puts ""
puts "========== FB REPLAY CUMULATIVE PATCH =========="

set fp [open $::env(ECO_PATCH) r]
set replayed 0

while {[gets $fp line] >= 0} {
    set line [string trim $line]

    if {$line eq ""} {
        continue
    }

    lassign $line inst new_master

    set db_inst [$block findInst $inst]

    if {$db_inst eq "NULL"} {
        close $fp
        error "Patch instance '$inst' does not exist in clean checkpoint"
    }

    puts "FB_REPLAY_CHANGE $inst -> $new_master"

    replace_cell $inst $new_master
    incr replayed
}

close $fp

puts "FB_REPLAY_COUNT $replayed"

puts ""
puts "========== FB LEGALIZE =========="

source "$::env(SCRIPTS_DIR)/openroad/common/dpl.tcl"

puts ""
puts "========== FB FRESH FULL GLOBAL ROUTE =========="

source "$::env(SCRIPTS_DIR)/openroad/common/grt.tcl"

write_db $::env(SAVE_ODB)
write_def $::env(SAVE_DEF)

puts "FB_REPLAY_COMPLETE"
