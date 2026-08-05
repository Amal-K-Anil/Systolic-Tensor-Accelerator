# Makefile
# Shared cocotb testbench runner for Systolic-Tensor-Accelerator
#
# Usage:
#   make TOPLEVEL=<module>
#   make all
#   make all-integration
#
# Examples:
#   make TOPLEVEL=mac_unit
#   make TOPLEVEL=accelerator_core
#   make TOPLEVEL=chip_top

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

# Local PDK clone created with:
#   cd $(PROJECT_ROOT) && make clone-pdk
GF180_PDK_ROOT := $(PROJECT_ROOT)/gf180mcu/gf180mcuD
GF180_IO_DIR   := $(GF180_PDK_ROOT)/libs.ref/gf180mcu_fd_io/verilog

GF180_IO_MODEL := $(GF180_IO_DIR)/gf180mcu_fd_io.v
GF180_WS_IO_MODEL := $(GF180_IO_DIR)/gf180mcu_ws_io__blackbox.v

GF180_CHIP_ID_MODEL := \
	$(IP_DIR)/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v

GF180_LOGO_MODEL := \
	$(IP_DIR)/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v

# Allows chip_top.sv to resolve:
#   `include "slot_defines.svh"
COMPILE_ARGS += -I$(WRAPPER_DIR)

# ========================
# Shared Sources
# ========================
VERILOG_SOURCES := $(TIMESCALE)

# ========================
# Reusable Source Groups
# ========================
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

	# Select the Slot A definitions in slot_defines.svh.
	COMPILE_ARGS += -DSLOT_A

	# Allow includes used by the GF180 I/O model.
	COMPILE_ARGS += -I$(GF180_IO_DIR)

	# Functional signal-pad model and wafer.space physical macro views.
	VERILOG_SOURCES += $(GF180_IO_MODEL)
	VERILOG_SOURCES += $(GF180_WS_IO_MODEL)
	VERILOG_SOURCES += $(GF180_CHIP_ID_MODEL)
	VERILOG_SOURCES += $(GF180_LOGO_MODEL)

	# Full hierarchy:
	# chip_top -> chip_core -> host_interface -> accelerator_core
	VERILOG_SOURCES += $(ACCELERATOR_SOURCES)
	VERILOG_SOURCES += $(WRAPPER_DIR)/host_interface.sv
	VERILOG_SOURCES += $(WRAPPER_DIR)/chip_core.sv
	VERILOG_SOURCES += $(WRAPPER_DIR)/chip_top.sv

else ifeq ($(TOPLEVEL),accelerator_axi_wrapper)

	COCOTB_TEST_MODULES = tb_axi_wrapper
	VERILOG_SOURCES += $(ACCELERATOR_SOURCES)
	VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_slave.sv
	VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_master.sv
	VERILOG_SOURCES += $(AXI_DIR)/accelerator_axi_wrapper.sv

else ifdef TOPLEVEL

	$(error Unknown TOPLEVEL='$(TOPLEVEL)'. \
	Valid options: mac_unit systolic_array feeder \
	output_processor accelerator_core chip_top \
	accelerator_axi_wrapper)

endif

# ========================
# Run All Targets
# ========================
UNIT_MODULES := \
	mac_unit \
	systolic_array \
	feeder \
	output_processor

INTEGRATION_MODULES := \
	accelerator_core \
	chip_top \
	accelerator_axi_wrapper

.PHONY: all all-integration clean help

all: ## Run all unit testbenches
	@for m in $(UNIT_MODULES); do \
		echo ""; \
		echo "========================================"; \
		echo " Running: $$m"; \
		echo "========================================"; \
		$(MAKE) clean; \
		$(MAKE) TOPLEVEL=$$m sim || exit 1; \
	done

all-integration: ## Run all integration testbenches
	@for m in $(INTEGRATION_MODULES); do \
		echo ""; \
		echo "========================================"; \
		echo " Running: $$m"; \
		echo "========================================"; \
		$(MAKE) clean; \
		$(MAKE) TOPLEVEL=$$m sim || exit 1; \
	done

clean:: ## Remove all simulation build artifacts
	rm -rf sim_build __pycache__ results.xml *.vcd *.fst

help: ## Show this help message
	@echo "Usage: make TOPLEVEL=<module>"
	@echo ""
	@echo "Unit modules:"
	@for m in $(UNIT_MODULES); do echo "  $$m"; done
	@echo ""
	@echo "Integration modules:"
	@for m in $(INTEGRATION_MODULES); do echo "  $$m"; done
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  %-20s %s\n", $$1, $$2}'

# ========================
# cocotb Makefile Include
# ========================
include $(shell cocotb-config --makefiles)/Makefile.sim
