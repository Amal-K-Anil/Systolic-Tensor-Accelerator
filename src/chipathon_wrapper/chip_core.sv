// SPDX-FileCopyrightText: 2026 Chipathon 2026 workshop
// SPDX-License-Identifier: Apache-2.0
//
// Minimal chip_core for the Chipathon 2026 workshop padring slot.
// The emphasis of this slot is the padring itself (60 analog + 20
// bidir + 4/4 power + clk/rst_n); the core is intentionally trivial:
// a free-running counter whose state drives the 20 bidir pads. The
// 60 analog pads are routed straight through to analog[] and stay
// unconnected at the core level (the intent is that a downstream
// design wires them to custom analog IP later).

`default_nettype none

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
)(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,       // clock
    input  wire rst_n,     // reset (active low)

    input  wire [NUM_INPUT_PADS-1:0] input_in,   // Input value
    output wire [NUM_INPUT_PADS-1:0] input_pu,   // Pull-up
    output wire [NUM_INPUT_PADS-1:0] input_pd,   // Pull-down

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS, 1=Schmitt)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,   // Pull-down

    inout  wire [NUM_ANALOG_PADS-1:0] analog    // Analog
);

    // =========================================================================
    // Pad mapping
    // =========================================================================
    //
    // bidir[7:0]  : shared input/output data bus
    // bidir[8]    : valid_in
    // bidir[9]    : tile_done
    // bidir[10]   : last_pass
    // bidir[11]   : ready_out
    // bidir[12]   : ready_in
    // bidir[13]   : valid_out
    //
    // All supported slots contain at least 20 bidirectional pads.

    logic [7:0] accelerator_data_in;
    logic [7:0] accelerator_data_out;

    logic valid_in;
    logic tile_done;
    logic last_pass;
    logic ready_out;

    logic ready_in;
    logic valid_out;

    logic [NUM_BIDIR_PADS-1:0] bidir_out_int;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe_int;
    logic [NUM_BIDIR_PADS-1:0] bidir_ie_int;

    // -------------------------------------------------------------------------
    // Discrete input-pad configuration
    // -------------------------------------------------------------------------
    // The accelerator interface uses bidirectional pads, so the discrete input
    // pads remain unused with pull-up and pull-down disabled.

    assign input_pu = '0;
    assign input_pd = '0;

    // -------------------------------------------------------------------------
    // Accelerator inputs
    // -------------------------------------------------------------------------

    assign accelerator_data_in = bidir_in[7:0];

    assign valid_in  = bidir_in[8];
    assign tile_done = bidir_in[9];
    assign last_pass = bidir_in[10];
    assign ready_out = bidir_in[11];

    // -------------------------------------------------------------------------
    // Bidirectional-pad configuration
    // -------------------------------------------------------------------------

    always_comb begin
        // Safe defaults: all pads disabled and driving zero internally.
        bidir_out_int = '0;
        bidir_oe_int  = '0;
        bidir_ie_int  = '0;

        // Shared 8-bit data bus.
        bidir_out_int[7:0] = accelerator_data_out;

        // Host drives the data bus while the accelerator is not producing
        // output. The accelerator drives it only while valid_out is asserted.
        bidir_oe_int[7:0] = {8{valid_out}};
        bidir_ie_int[7:0] = {8{~valid_out}};

        // Input-only control pads.
        bidir_ie_int[8]  = 1'b1; // valid_in
        bidir_ie_int[9]  = 1'b1; // tile_done
        bidir_ie_int[10] = 1'b1; // last_pass
        bidir_ie_int[11] = 1'b1; // ready_out

        // Output-only status pads.
        bidir_out_int[12] = ready_in;
        bidir_out_int[13] = valid_out;

        bidir_oe_int[12] = 1'b1;
        bidir_oe_int[13] = 1'b1;
    end

    assign bidir_out = bidir_out_int;
    assign bidir_oe  = bidir_oe_int;
    assign bidir_ie  = bidir_ie_int;

    // CMOS input mode, fast slew, no pulls.
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;

    // -------------------------------------------------------------------------
    // Accelerator core
    // -------------------------------------------------------------------------

    accelerator_core #(
        .ARRAY_SIZE(8)
    ) u_accelerator_core (
        .clk       (clk),
        .rst_n     (rst_n),

        .data_in   (accelerator_data_in),
        .valid_in  (valid_in),
        .ready_in  (ready_in),

        .tile_done (tile_done),
        .last_pass (last_pass),

        .data_out  (accelerator_data_out),
        .valid_out (valid_out),
        .ready_out (ready_out)
    );

    // Prevent an unused-input warning for the discrete input-pad bank.
    logic unused_inputs;
    assign unused_inputs = &{1'b0, input_in};

    // Free-running counter, width equal to the number of bidir pads.
    logic [NUM_BIDIR_PADS-1:0] count;
    always_ff @(posedge clk) begin
        if (!rst_n) count <= '0;
        else        count <= count + 1;
    end
    assign bidir_out = count;

endmodule

`default_nettype wire
