# Makefile
# Shared cocotb testbench runner for Systolic-Tensor-Accelerator
#
# Usage:
#   make TOPLEVEL=<module>   -- run one module's testbench
#   make run-all             -- run every module's testbench, in order
#
# Modules:
#   mac_unit  systolic_array  feeder  output_processor
#   accelerator_core  chip_top
#
# chip_top-specific variables, each independently defaulted so this
# Makefile runs standalone; a parent Makefile may override any of them
# by exporting the same-named variable before invoking:
#   SLOT      ?= a        -- selects -DSLOT_<SLOT, uppercased>
#   PDK_ROOT  ?= <repo>/gf180mcu
#   PDK       ?= gf180mcuD
#   GL        ?= (unset)  -- set to 1 for gate-level sim against the
#                             post-synthesis netlist instead of RTL

# ========================
# Simulator Configuration
# ========================
SIM           ?= icarus
TOPLEVEL_LANG ?= verilog

COMPILE_ARGS += -g2012
COMPILE_ARGS += -DFUNCTIONAL

# ========================
# Project Paths
# ========================
PROJECT_ROOT := $(abspath ..)

TIMESCALE   := $(abspath timescale.v)
CORE_DIR    := $(PROJECT_ROOT)/src/core
WRAPPER_DIR := $(PROJECT_ROOT)/src/chipathon_wrapper
AXI_DIR     := $(PROJECT_ROOT)/src/axi_wrapper
IP_DIR      := $(PROJECT_ROOT)/ip
FINAL_DIR   := $(PROJECT_ROOT)/final

SLOT     ?= a
PDK_ROOT ?= $(PROJECT_ROOT)/gf180mcu
PDK      ?= gf180mcuD
SCL      := gf180mcu_fd_sc_mcu7t5v0

GF180_PDK_ROOT := $(PDK_ROOT)/$(PDK)
GF180_IO_DIR   := $(GF180_PDK_ROOT)/libs.ref/gf180mcu_fd_io/verilog
GF180_SCL_DIR  := $(GF180_PDK_ROOT)/libs.ref/$(SCL)/verilog

GF180_IO_MODEL       := $(GF180_IO_DIR)/gf180mcu_fd_io.v
GF180_WS_IO_MODEL    := $(GF180_IO_DIR)/gf180mcu_ws_io__blackbox.v
GF180_CHIP_ID_MODEL  := $(IP_DIR)/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v
GF180_LOGO_MODEL     := $(IP_DIR)/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v

GF180_SCL_MODEL        := $(GF180_SCL_DIR)/$(SCL).v
GF180_PRIMITIVES_MODEL := $(GF180_SCL_DIR)/primitives.v
CHIP_TOP_NETLIST        := $(FINAL_DIR)/pnl/chip_top.pnl.v

# Allows chip_top.sv to resolve `include "slot_defines.svh"
COMPILE_ARGS += -I$(WRAPPER_DIR)

# ========================
# Shared Sources
# ========================
VERILOG_SOURCES := $(TIMESCALE)

BOOTH_SOURCES := \
	$(CORE_DIR)/booth_encoder.sv \
	$(CORE_DIR)/ppdt_booth.sv \
	$(CORE_DIR)/booth_multiplier.sv

MAC_SOURCES := \
	$(BOOTH_SOURCES) \
	$(CORE_DIR)/mac_unit.sv

ACCELERATOR_SOURCES := \
	$(MAC_SOURCES) \
	$(CORE_DIR)/systolic_array.sv \
	$(CORE_DIR)/feeder.sv \
	$(CORE_DIR)/output_processor.sv \
	$(CORE_DIR)/accelerator_core.sv

ALL_MODULES := \
	mac_unit \
	systolic_array \
	feeder \
	output_processor \
	accelerator_core \
	chip_top

# ========================
# Per-Module Configuration
# ========================
ifeq ($(TOPLEVEL),mac_unit)

	COCOTB_TEST_MODULES = tb_mac_unit
	VERILOG_SOURCES += $(MAC_SOURCES)

else ifeq ($(TOPLEVEL),systolic_array)

	COCOTB_TEST_MODULES = tb_systolic_array
	VERILOG_SOURCES += $(MAC_SOURCES)
	VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv

else ifeq ($(TOPLEVEL),feeder)

	COCOTB_TEST_MODULES = tb_feeder
	VERILOG_SOURCES += $(CORE_DIR)/feeder.sv

else ifeq ($(TOPLEVEL),output_processor)

	COCOTB_TEST_MODULES = tb_output_processor
	VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv

else ifeq ($(TOPLEVEL),accelerator_core)

	COCOTB_TEST_MODULES = tb_accelerator_core
	VERILOG_SOURCES += $(ACCELERATOR_SOURCES)

else ifeq ($(TOPLEVEL),chip_top)

	COCOTB_TEST_MODULES = chip_top_tb
	COMPILE_ARGS += -DSLOT_$(shell echo $(SLOT) | tr a-z A-Z)
	COMPILE_ARGS += -I$(GF180_IO_DIR)

	VERILOG_SOURCES += $(GF180_IO_MODEL)
	VERILOG_SOURCES += $(GF180_WS_IO_MODEL)
	VERILOG_SOURCES += $(GF180_CHIP_ID_MODEL)
	VERILOG_SOURCES += $(GF180_LOGO_MODEL)

	ifeq ($(GL),1)
		# Gate-level: the post-synthesis netlist, plus the cell
		# library's own behavioral models and the primitives they
		# depend on. Requires `make librelane` to have already
		# produced final/pnl/chip_top.pnl.v.
		VERILOG_SOURCES += $(GF180_SCL_MODEL)
		VERILOG_SOURCES += $(GF180_PRIMITIVES_MODEL)
		VERILOG_SOURCES += $(CHIP_TOP_NETLIST)
	else
		# RTL: chip_top -> chip_core -> host_interface -> accelerator_core
		VERILOG_SOURCES += $(ACCELERATOR_SOURCES)
		VERILOG_SOURCES += $(WRAPPER_DIR)/host_interface.sv
		VERILOG_SOURCES += $(WRAPPER_DIR)/chip_core.sv
		VERILOG_SOURCES += $(WRAPPER_DIR)/chip_top.sv
	endif

else ifeq ($(TOPLEVEL),accelerator_axi_wrapper)

	COCOTB_TEST_MODULES = tb_axi_wrapper
	VERILOG_SOURCES += $(ACCELERATOR_SOURCES)
	VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_slave.sv
	VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_master.sv
	VERILOG_SOURCES += $(AXI_DIR)/accelerator_axi_wrapper.sv

else ifdef TOPLEVEL

	$(error Unknown TOPLEVEL='$(TOPLEVEL)'. Valid options: \
	mac_unit systolic_array feeder output_processor \
	accelerator_core chip_top accelerator_axi_wrapper)

endif

# ========================
# cocotb Makefile Include
# ========================
include $(shell cocotb-config --makefiles)/Makefile.sim
.DEFAULT_GOAL := sim

# ========================
# Run-Everything / Housekeeping
# ========================
.PHONY: run-all clean help

run-all: ## Run every module's testbench, in order
	@for m in $(ALL_MODULES); do \
		echo ""; \
		echo "========================================"; \
		echo " Running: $$m"; \
		echo "========================================"; \
		$(MAKE) clean; \
		$(MAKE) TOPLEVEL=$$m || exit 1; \
	done

clean:: ## Remove all simulation build artifacts
	rm -rf sim_build __pycache__ results.xml *.vcd *.fst

help: ## Show this help message
	@echo "Usage: make TOPLEVEL=<module>"
	@echo ""
	@echo "Modules:"
	@for m in $(ALL_MODULES); do echo "  $$m"; done
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
