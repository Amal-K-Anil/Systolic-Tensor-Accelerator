# Makefile
# Shared cocotb testbench runner for Systolic-Tensor-Accelerator
#
# Usage:
#   make TOPLEVEL=<module>         Run testbench for specific module
#   make all                       Run all unit testbenches
#   make all-integration           Run all integration testbenches
#
# Examples:
#   make TOPLEVEL=mac_unit
#   make TOPLEVEL=controller
#   make TOPLEVEL=accelerator_core

# ========================
# Simulator Configuration
# ========================
SIM          ?= icarus
COMPILE_ARGS += -g2012
COMPILE_ARGS += -DFUNCTIONAL

# ========================
# Shared Sources
# ========================
TIMESCALE     = $(abspath timescale.v)
CORE_DIR      = $(abspath ../src/core)
WRAPPER_DIR   = $(abspath ../src/chipathon_wrapper)
AXI_DIR       = $(abspath ../src/axi_wrapper)

VERILOG_SOURCES = $(TIMESCALE)

# ========================
# Per-Module Configuration
# ========================
ifeq ($(TOPLEVEL), mac_unit)
    MODULE           = tb_mac_unit
    VERILOG_SOURCES += $(CORE_DIR)/booth_encoder.sv
    VERILOG_SOURCES += $(CORE_DIR)/ppdt_booth.sv
    VERILOG_SOURCES += $(CORE_DIR)/booth_multiplier.sv
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv

else ifeq ($(TOPLEVEL), systolic_array)
    MODULE           = tb_systolic_array
    VERILOG_SOURCES += $(CORE_DIR)/booth_encoder.sv
    VERILOG_SOURCES += $(CORE_DIR)/ppdt_booth.sv
    VERILOG_SOURCES += $(CORE_DIR)/booth_multiplier.sv
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv

else ifeq ($(TOPLEVEL), feeder)
    MODULE           = tb_feeder
    VERILOG_SOURCES += $(CORE_DIR)/feeder.sv

else ifeq ($(TOPLEVEL), memory)
    MODULE           = tb_memory
    VERILOG_SOURCES += /foss/pdks/ciel/gf180mcu/versions/7b70722e33c03fcb5dabcf4d479fb0822d9251c9/gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram128x8m8wm1.v
    VERILOG_SOURCES += $(CORE_DIR)/memory.sv

else ifeq ($(TOPLEVEL), controller)
    MODULE           = tb_controller
    VERILOG_SOURCES += $(CORE_DIR)/controller.sv

else ifeq ($(TOPLEVEL), output_processor)
    MODULE           = tb_output_processor
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv
    VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv

else ifeq ($(TOPLEVEL), accelerator_core)
    MODULE           = tb_accelerator_core

    # Feeder simulation-only debug ports.
    COMPILE_ARGS    += -DFEEDER_DEBUG

    # Excel and current architecture use the 8x8 configuration.
    COMPILE_ARGS    += -Paccelerator_core.ARRAY_SIZE=8

   # VERILOG_SOURCES += $(CURDIR)/models/gf180_sram128x8_functional.v
    VERILOG_SOURCES += /foss/pdks/ciel/gf180mcu/versions/7b70722e33c03fcb5dabcf4d479fb0822d9251c9/gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram128x8m8wm1.v

    VERILOG_SOURCES += $(CORE_DIR)/booth_encoder.sv
    VERILOG_SOURCES += $(CORE_DIR)/ppdt_booth.sv
    VERILOG_SOURCES += $(CORE_DIR)/booth_multiplier.sv
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv
    VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv
    VERILOG_SOURCES += $(CORE_DIR)/memory.sv
    VERILOG_SOURCES += $(CORE_DIR)/feeder.sv
    VERILOG_SOURCES += $(CORE_DIR)/controller.sv
    VERILOG_SOURCES += $(CORE_DIR)/accelerator_core.sv


else ifeq ($(TOPLEVEL), accelerator_top)
    MODULE           = tb_accelerator_top
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv
    VERILOG_SOURCES += $(CORE_DIR)/feeder.sv
    VERILOG_SOURCES += $(CORE_DIR)/memory.sv
    VERILOG_SOURCES += $(CORE_DIR)/controller.sv
    VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv
    VERILOG_SOURCES += $(CORE_DIR)/accelerator_core.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/host_interface.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/accelerator_top.sv

else ifeq ($(TOPLEVEL), chip_top)
    MODULE           = chip_top_tb
    VERILOG_SOURCES += $(WRAPPER_DIR)/slot_defines.svh
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv
    VERILOG_SOURCES += $(CORE_DIR)/feeder.sv
    VERILOG_SOURCES += $(CORE_DIR)/memory.sv
    VERILOG_SOURCES += $(CORE_DIR)/controller.sv
    VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv
    VERILOG_SOURCES += $(CORE_DIR)/accelerator_core.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/host_interface.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/accelerator_top.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/chip_core.sv
    VERILOG_SOURCES += $(WRAPPER_DIR)/chip_top.sv

else ifeq ($(TOPLEVEL), accelerator_axi_wrapper)
    MODULE           = tb_axi_wrapper
    VERILOG_SOURCES += $(CORE_DIR)/mac_unit.sv
    VERILOG_SOURCES += $(CORE_DIR)/systolic_array.sv
    VERILOG_SOURCES += $(CORE_DIR)/feeder.sv
    VERILOG_SOURCES += $(CORE_DIR)/memory.sv
    VERILOG_SOURCES += $(CORE_DIR)/controller.sv
    VERILOG_SOURCES += $(CORE_DIR)/output_processor.sv
    VERILOG_SOURCES += $(CORE_DIR)/accelerator_core.sv
    VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_slave.sv
    VERILOG_SOURCES += $(AXI_DIR)/axi4_stream_master.sv
    VERILOG_SOURCES += $(AXI_DIR)/accelerator_axi_wrapper.sv

else ifdef TOPLEVEL
    $(error Unknown TOPLEVEL='$(TOPLEVEL)'. \
        Valid options: mac_unit systolic_array feeder memory \
        controller output_processor accelerator_core \
        accelerator_top chip_top accelerator_axi_wrapper)
endif

# ========================
# Run All Targets
# ========================
UNIT_MODULES = mac_unit systolic_array feeder memory \
               controller output_processor

INTEGRATION_MODULES = accelerator_core accelerator_top \
                      chip_top accelerator_axi_wrapper

.PHONY: all all-integration clean help

all: ## Run all unit testbenches
	@for m in $(UNIT_MODULES); do \
		echo ""; \
		echo "========================================"; \
		echo " Running: $$m"; \
		echo "========================================"; \
		$(MAKE) TOPLEVEL=$$m || exit 1; \
	done

all-integration: ## Run all integration testbenches
	@for m in $(INTEGRATION_MODULES); do \
		echo ""; \
		echo "========================================"; \
		echo " Running: $$m"; \
		echo "========================================"; \
		$(MAKE) TOPLEVEL=$$m || exit 1; \
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
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# ========================
# cocotb Makefile Include
# ========================
include $(shell cocotb-config --makefiles)/Makefile.sim
