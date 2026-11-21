// SPDX-FileCopyrightText: © 2025 Project Template Contributors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

`include "slot_defines.svh"

module chip_top #(
    // Signal interfaces
    parameter NUM_INPUT_PADS = `NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS = `NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS = `NUM_ANALOG_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,
    input  wire rst_n,

    inout  wire [7:0] data,

    input  wire a_valid_i,
    output wire a_ready_o,
    input  wire a_last_i,

    input  wire b_valid_i,
    output wire b_ready_o,
    input  wire b_last_i,

    output wire out_valid_o,
    input  wire out_ready_i,
    output wire out_last_o
);

    wire [NUM_INPUT_PADS-1:0] input_in;
    wire [NUM_INPUT_PADS-1:0] input_pu;
    wire [NUM_INPUT_PADS-1:0] input_pd;

    wire [NUM_BIDIR_PADS-1:0] bidir_in;
    wire [NUM_BIDIR_PADS-1:0] bidir_out;
    wire [NUM_BIDIR_PADS-1:0] bidir_oe;
    wire [NUM_BIDIR_PADS-1:0] bidir_cs;
    wire [NUM_BIDIR_PADS-1:0] bidir_sl;
    wire [NUM_BIDIR_PADS-1:0] bidir_ie;
    wire [NUM_BIDIR_PADS-1:0] bidir_pu;
    wire [NUM_BIDIR_PADS-1:0] bidir_pd;

    wire [NUM_ANALOG_PADS-1:0] analog;

    // Input-only signals -> existing chip_core mapping
    assign input_in[0] = a_valid_i;
    assign input_in[1] = a_last_i;
    assign input_in[2] = b_valid_i;
    assign input_in[3] = b_last_i;
    assign input_in[4] = out_ready_i;

    // Shared 8-bit bidirectional data bus
    assign bidir_in[7:0]  = data;
    assign bidir_in[11:8] = '0;

    generate
        for (genvar i = 0; i < 8; i++) begin : data_bus
            assign data[i] = bidir_oe[i] ? bidir_out[i] : 1'bz;
        end
    endgenerate

    // Fixed-direction output signals
    assign a_ready_o   = bidir_out[8];
    assign b_ready_o   = bidir_out[9];
    assign out_valid_o = bidir_out[10];
    assign out_last_o  = bidir_out[11];

    // Purely digital design; retain the existing chip_core interface.
    assign analog = '0;

    // Core design
    chip_core #(
        .NUM_INPUT_PADS  (NUM_INPUT_PADS),
        .NUM_BIDIR_PADS  (NUM_BIDIR_PADS),
        .NUM_ANALOG_PADS (NUM_ANALOG_PADS)
    ) i_chip_core (
        `ifdef USE_POWER_PINS
        .VDD        (VDD),
        .VSS        (VSS),
        `endif

        .clk        (clk),
        .rst_n      (rst_n),

        .input_in   (input_in),
        .input_pu   (input_pu),
        .input_pd   (input_pd),

        .bidir_in   (bidir_in),
        .bidir_out  (bidir_out),
        .bidir_oe   (bidir_oe),
        .bidir_cs   (bidir_cs),
        .bidir_sl   (bidir_sl),
        .bidir_ie   (bidir_ie),
        .bidir_pu   (bidir_pu),
        .bidir_pd   (bidir_pd),

        .analog     (analog)
    );

    // Chip ID - do not remove, necessary for tapeout
    (* keep *)
    gf180mcu_ws_ip__id chip_id ();

    // wafer.space logo - can be removed
    (* keep *)
    gf180mcu_ws_ip__logo wafer_space_logo ();

endmodule

`default_nettype wire
