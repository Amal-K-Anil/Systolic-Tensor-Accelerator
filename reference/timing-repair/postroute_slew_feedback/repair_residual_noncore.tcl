source "$::env(SCRIPTS_DIR)/openroad/common/io.tcl"
source "$::env(SCRIPTS_DIR)/openroad/common/resizer.tcl"

if {![info exists ::env(FB_OUT_DIR)]} {
    error "FB_OUT_DIR is not set"
}

if {![info exists ::env(FB_VIOLATOR_FILE)]} {
    error "FB_VIOLATOR_FILE is not set"
}

file mkdir $::env(FB_OUT_DIR)

read_current_odb

set block [ord::get_db_block]
set db [ord::get_db]

set_propagated_clock [all_clocks]
read_spefs

proc fb_find_inst {block target} {
    set inst [$block findInst $target]

    if {$inst ne "NULL"} {
        return $inst
    }

    foreach candidate [$block getInsts] {
        set db_name [$candidate getName]
        set normalized [string map [list "\\" ""] $db_name]

        if {$normalized eq $target} {
            return $candidate
        }
    }

    return "NULL"
}

proc fb_next_strength_master {db current_master} {
    set current_name [$current_master getName]

    if {![regexp {^(.*)_([0-9]+)$} $current_name -> prefix current_strength]} {
        return "NULL"
    }

    set current_height [$current_master getHeight]

    set best_master "NULL"
    set best_strength 2147483647

    foreach lib [$db getLibs] {
        foreach master [$lib getMasters] {
            set candidate_name [$master getName]

            if {![regexp {^(.*)_([0-9]+)$} \
                $candidate_name -> candidate_prefix candidate_strength]} {
                continue
            }

            if {$candidate_prefix ne $prefix} {
                continue
            }

            if {[$master getHeight] != $current_height} {
                continue
            }

            if {
                $candidate_strength > $current_strength
                && $candidate_strength < $best_strength
            } {
                set best_master $master
                set best_strength $candidate_strength
            }
        }
    }

    return $best_master
}

set fp [open $::env(FB_VIOLATOR_FILE) r]

set patch_path "$::env(FB_OUT_DIR)/residual_patch.txt"
set patch_fp [open $patch_path w]

array set seen_driver {}
set changed 0

while {[gets $fp endpoint] >= 0} {
    set endpoint [string trim $endpoint]

    if {$endpoint eq ""} {
        continue
    }

    set slash [string last "/" $endpoint]

    if {$slash < 1} {
        puts "FB_RESIDUAL_SKIP malformed_endpoint=$endpoint"
        continue
    }

    set load_inst_name [string range \
        $endpoint 0 [expr {$slash - 1}]]

    set load_pin_name [string range \
        $endpoint [expr {$slash + 1}] end]

    set load_inst [fb_find_inst $block $load_inst_name]

    if {$load_inst eq "NULL"} {
        puts "FB_RESIDUAL_SKIP endpoint=$endpoint reason=load_not_found"
        continue
    }

    set load_master_name [[$load_inst getMaster] getName]

    # This fallback is intentionally NOT for ordinary core cells.
    if {
        [info exists ::env(STD_CELL_LIBRARY)]
        && [string match \
            "$::env(STD_CELL_LIBRARY)__*" \
            $load_master_name]
    } {
        puts "FB_RESIDUAL_SKIP endpoint=$endpoint reason=core_load"
        continue
    }

    set load_iterm [$load_inst findITerm $load_pin_name]

    if {$load_iterm eq "NULL"} {
        puts "FB_RESIDUAL_SKIP endpoint=$endpoint reason=pin_not_found"
        continue
    }

    set net [$load_iterm getNet]

    if {$net eq "NULL"} {
        puts "FB_RESIDUAL_SKIP endpoint=$endpoint reason=no_net"
        continue
    }

    set driver_iterms {}

    foreach iterm [$net getITerms] {
        set mterm [$iterm getMTerm]

        if {[$mterm getIoType] eq "OUTPUT"} {
            lappend driver_iterms $iterm
        }
    }

    if {[llength $driver_iterms] != 1} {
        puts \
            "FB_RESIDUAL_SKIP endpoint=$endpoint reason=driver_count_[llength $driver_iterms]"
        continue
    }

    set driver_iterm [lindex $driver_iterms 0]
    set driver_inst [$driver_iterm getInst]
    set driver_name [$driver_inst getName]

    if {[info exists seen_driver($driver_name)]} {
        continue
    }

    set seen_driver($driver_name) 1

    set old_master [$driver_inst getMaster]
    set old_master_name [$old_master getName]

    set new_master [fb_next_strength_master $db $old_master]

    if {$new_master eq "NULL"} {
        puts \
            "FB_RESIDUAL_SKIP endpoint=$endpoint driver=$driver_name reason=no_stronger_family_cell"
        continue
    }

    set new_master_name [$new_master getName]

    puts \
        "FB_RESIDUAL_CHANGE $driver_name : $old_master_name -> $new_master_name"

    replace_cell $driver_name $new_master_name

    puts $patch_fp "$driver_name $new_master_name"
    incr changed
}

close $fp
close $patch_fp

puts "FB_RESIDUAL_CHANGE_COUNT $changed"
puts "FB_RESIDUAL_PATCH $patch_path"

puts ""
puts "========== FB AFTER RESIDUAL REPAIR =========="

report_check_types \
    -max_slew \
    -max_capacitance \
    -violators \
    -corner $::env(FB_CORNER)
