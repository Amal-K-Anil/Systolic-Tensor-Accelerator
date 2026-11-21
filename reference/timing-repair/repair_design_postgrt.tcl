# Copyright 2020-2023 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl

read_current_odb

set_propagated_clock [all_clocks]

set_dont_touch_objects

# set rc values
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl

# (Re-)GRT and Estimate Parasitics
# Temporarily always enabled: https://github.com/The-OpenROAD-Project/OpenROAD/issues/5590
#if { $::env(GRT_DESIGN_REPAIR_RUN_GRT) } {
source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl
#}
estimate_parasitics -global_routing

# Repair Design
set repair_design_args [list]
lappend repair_design_args -verbose
lappend repair_design_args -max_wire_length $::env(GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH)
lappend repair_design_args -slew_margin $::env(GRT_DESIGN_REPAIR_MAX_SLEW_PCT)
lappend repair_design_args -cap_margin $::env(GRT_DESIGN_REPAIR_MAX_CAP_PCT)
if { [info exists ::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)] } {
    lappend repair_design_args -max_utilization $::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)
}
if { [info exists ::env(GRT_DESIGN_REPAIR_BUFFER_GAIN)] } {
    lappend repair_design_args -buffer_gain $::env(GRT_DESIGN_REPAIR_BUFFER_GAIN)
}
log_cmd repair_design {*}$repair_design_args

# Re-DPL and GRT after first repair
source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl
unset_dont_touch_objects

if { $::env(GRT_DESIGN_REPAIR_RUN_GRT) } {
    source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl

    # Re-estimate parasitics after first repair + reroute
    estimate_parasitics -global_routing

    # Second generic design-repair pass with a slightly stronger slew margin
    set repair_design_args_pass2 [list]
    lappend repair_design_args_pass2 -verbose
    lappend repair_design_args_pass2 -max_wire_length $::env(GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH)
    lappend repair_design_args_pass2 -slew_margin 31
    lappend repair_design_args_pass2 -cap_margin $::env(GRT_DESIGN_REPAIR_MAX_CAP_PCT)

    if { [info exists ::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)] } {
        lappend repair_design_args_pass2 -max_utilization $::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)
    }
    if { [info exists ::env(GRT_DESIGN_REPAIR_BUFFER_GAIN)] } {
        lappend repair_design_args_pass2 -buffer_gain $::env(GRT_DESIGN_REPAIR_BUFFER_GAIN)
    }

    set_dont_touch_objects
    log_cmd repair_design {*}$repair_design_args_pass2

    # Legalize cells inserted/resized by second repair
    source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl
    unset_dont_touch_objects

    # Final GRT after second repair
    source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl
}

write_views
