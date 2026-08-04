// =======================================================================================
// accelerator_core.sv
//
// accelerator_core is the reusable compute/control IP boundary of the systolic array
// accelerator. It instantiates and wires feeder, systolic_array, and output_processor
// -- pure structural connection, no logic of its own. This is the module intended for
// reuse in any SoC integration (via the Chipathon host_interface, or an AXI4-Stream
// wrapper); everything above this level is interface-specific.
//
// Operation overview:
//   No controller module exists in this design. Each submodule self-generates its own
//   phase transition and hands it directly to its neighbour:
//
//     feeder.drain_done   -> output_processor.output_en   (safe to start serializing)
//     output_processor.output_done -> feeder.clear AND systolic_array.clear
//                                      (last result transferred, reset for next run)
//
//   Two independent AXI4-Stream input channels (activation, weight) stream into
//   feeder, which skews and drives systolic_array; systolic_array's accumulator grid
//   feeds output_processor, which serializes results out over a third AXI4-Stream
//   channel. See feeder.sv and output_processor.sv for the self-generation reasoning
//   behind drain_done/output_done.
// =======================================================================================

`default_nettype none

module accelerator_core #(
    parameter ARRAY_SIZE  = 8,
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21,
    parameter SHIFT_BITS  = 0,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MAX = (1 <<< (DATA_WIDTH-1)) - 1,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MIN = -(1 <<< (DATA_WIDTH-1))
)(
    input  logic                  clk,
    input  logic                  rst_n,

    // Activation channel (AXI4-Stream, sink side)
    input  logic [DATA_WIDTH-1:0] a_data,
    input  logic                  a_valid,
    output logic                  a_ready,
    input  logic                  a_last,

    // Weight channel (AXI4-Stream, sink side)
    input  logic [DATA_WIDTH-1:0] b_data,
    input  logic                  b_valid,
    output logic                  b_ready,
    input  logic                  b_last,

    // Result channel (AXI4-Stream, source side)
    output logic [DATA_WIDTH-1:0] out_data,
    output logic                  out_valid,
    input  logic                  out_ready,
    output logic                  out_last
);

    // feeder <-> output_processor phase handoff
    logic drain_done;  // feeder -> output_processor.output_en
    logic clear;       // output_processor.output_done -> feeder + systolic_array

    // feeder -> systolic_array
    logic [ARRAY_SIZE*DATA_WIDTH-1:0] a_out, b_out;
    logic                             valid;

    // systolic_array -> output_processor
    logic [ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH-1:0] results;


    // ===================================================================================
    //  Feeder
    // ===================================================================================
    feeder #(
        .ARRAY_SIZE (ARRAY_SIZE),
        .DATA_WIDTH (DATA_WIDTH)
    ) u_feeder (
        .clk        (clk),
        .rst_n      (rst_n),

        .a_data     (a_data),
        .a_valid    (a_valid),
        .a_ready    (a_ready),
        .a_last     (a_last),

        .b_data     (b_data),
        .b_valid    (b_valid),
        .b_ready    (b_ready),
        .b_last     (b_last),

        .clear      (clear),

        .a_out      (a_out),
        .b_out      (b_out),
        .valid      (valid),

        .drain_done (drain_done)
    );


    // ===================================================================================
    //  Systolic Array
    // ===================================================================================
    systolic_array #(
        .ARRAY_SIZE  (ARRAY_SIZE),
        .DATA_WIDTH  (DATA_WIDTH),
        .ACCUM_WIDTH (ACCUM_WIDTH)
    ) u_systolic_array (
        .clk     (clk),
        .rst_n   (rst_n),

        .a_in    (a_out),
        .b_in    (b_out),
        .valid   (valid),
        .clear   (clear),

        .results (results)
    );


    // ===================================================================================
    //  Output Processor
    // ===================================================================================
    output_processor #(
        .ARRAY_SIZE  (ARRAY_SIZE),
        .ACCUM_WIDTH (ACCUM_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .SHIFT_BITS  (SHIFT_BITS),
        .SAT_MAX     (SAT_MAX),
        .SAT_MIN     (SAT_MIN)
    ) u_output_processor (
        .clk          (clk),
        .rst_n        (rst_n),

        .results      (results),

        .output_en    (drain_done),
        .output_done  (clear),

        .out_ready    (out_ready),
        .out_data     (out_data),
        .out_valid    (out_valid),
        .out_last     (out_last)
    );

endmodule

`default_nettype wire
