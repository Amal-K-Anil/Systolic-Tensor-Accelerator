// =======================================================================================
// host_interface.sv
//
// host_interface is the physical pad-level protocol adapter for accelerator_core,
// intended for chip-level testing over the Slot A padring (17 signal pins: an 8-bit
// shared data bus plus 9 single-bit control lines). It is not meant to represent a
// production-grade IP boundary -- a real SoC integration would use accelerator_core's
// native three-bus AXI4-Stream interface directly (see accelerator_axi_wrapper for
// that path); this adapter exists specifically to fit the accelerator onto a small,
// fixed pin budget for the Chipathon padring.
//
// Operation overview:
//   data[7:0] is shared by all three logical channels (A, B, OUT) rather than given
//   a dedicated bus each -- at most one of a_valid_i/b_valid_i is ever asserted by the
//   host in the same cycle (a protocol rule the host must honor; host_interface does
//   not arbitrate or enforce it), and out_valid_o is never asserted while either input
//   channel could still be active, since accelerator_core's own accum/output phases
//   never overlap with its input phase.
//
//   Direction on the shared bus is entirely driven by accelerator_core's own out_valid:
//   data_oe = out_valid. There is no separate phase-tracking state machine here --
//   the chip already knows unambiguously when it is producing results, and the host
//   is expected to stop driving data the moment it observes out_valid_o go high.
//
//   Every other control line (a_valid/a_ready/a_last, b_valid/b_ready/b_last,
//   out_valid/out_ready/out_last) has a single fixed owner for its entire lifetime --
//   host-driven or chip-driven, never both -- so none of them need direction control.
// =======================================================================================

`default_nettype none

module host_interface #(
    parameter ARRAY_SIZE  = 8,
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21,
    parameter SHIFT_BITS  = 0,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MAX = (1 <<< (DATA_WIDTH-1)) - 1,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MIN = -(1 <<< (DATA_WIDTH-1))
)(
    input  logic                  clk,
    input  logic                  rst_n,

    // Shared data bus (bidirectional at the pad)
    input  logic [DATA_WIDTH-1:0] data_i,    // sampled while host drives (input phase)
    output logic [DATA_WIDTH-1:0] data_o,    // driven while chip drives (output phase)
    output logic                  data_oe,   // 1 = chip drives data, 0 = host drives

    // Activation channel (fixed direction)
    input  logic                  a_valid_i,
    output logic                  a_ready_o,
    input  logic                  a_last_i,

    // Weight channel (fixed direction)
    input  logic                  b_valid_i,
    output logic                  b_ready_o,
    input  logic                  b_last_i,

    // Result channel (fixed direction)
    output logic                  out_valid_o,
    input  logic                  out_ready_i,
    output logic                  out_last_o
);

    accelerator_core #(
        .ARRAY_SIZE  (ARRAY_SIZE),
        .DATA_WIDTH  (DATA_WIDTH),
        .ACCUM_WIDTH (ACCUM_WIDTH),
        .SHIFT_BITS  (SHIFT_BITS),
        .SAT_MAX     (SAT_MAX),
        .SAT_MIN     (SAT_MIN)
    ) u_accelerator_core (
        .clk       (clk),
        .rst_n     (rst_n),

        .a_data    (data_i),        // shared bus tap - only latched when a_valid_i=1
        .a_valid   (a_valid_i),
        .a_ready   (a_ready_o),
        .a_last    (a_last_i),

        .b_data    (data_i),        // shared bus tap - only latched when b_valid_i=1
        .b_valid   (b_valid_i),
        .b_ready   (b_ready_o),
        .b_last    (b_last_i),

        .out_data  (data_o),
        .out_valid (out_valid_o),
        .out_ready (out_ready_i),
        .out_last  (out_last_o)
    );

    assign data_oe = out_valid_o;

endmodule

`default_nettype wire
