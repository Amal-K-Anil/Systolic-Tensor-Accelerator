// accelerator_core.sv
//
// Reusable compute/control IP boundary for the systolic array accelerator.
// Instantiates and wires: memory, feeder, controller, systolic_array,
// output_processor. Pure structural module — no logic of its own.
//
// Compatible with:
//   - host_interface (Chipathon physical pad interface)
//   - accelerator_axi_wrapper (AXI4-Stream SoC integration)

`default_nettype none

module accelerator_core #(
    parameter ARRAY_SIZE  = 8,
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21
)(
    input  logic                        clk,
    input  logic                        rst_n,

    // ── Host Input Interface ─────────────────────────────────────────
    input  logic [DATA_WIDTH-1:0]       data_in,      // tile byte from host
    input  logic                        valid_in,     // host byte valid
    output logic                        ready_in,     // permission pulse to host
    input  logic                        tile_done,    // host signals tile end
    input  logic                        last_pass,    // host signals final tile

    // ── Host Output Interface ────────────────────────────────────────
    output logic [DATA_WIDTH-1:0]       data_out,     // result byte to host
    output logic                        valid_out,    // result byte valid
    input  logic                        ready_out,    // host ready to receive
    output logic                        output_done   // all 64 results sent
);

    // ====================================================================
    // Internal Signal Declarations
    // ====================================================================

    // controller → memory
    logic [6:0]                         write_addr;
    logic                               write_en;

    // controller → memory + feeder
    logic                               swap;

    // controller → feeder
    logic                               drain_en;
    logic                               clear;

    // controller → output_processor
    logic                               output_en;

    // feeder → controller
    logic                               drain_done;

    // memory → feeder
    logic [7:0]                         sram_data;

    // feeder → memory
    logic [6:0]                         read_addr;
    logic                               read_en;

    // feeder → systolic_array
    logic [ARRAY_SIZE*DATA_WIDTH-1:0]   a_in;
    logic [ARRAY_SIZE*DATA_WIDTH-1:0]   b_in;
    logic                               valid;

    // systolic_array → output_processor
    logic [ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH-1:0] results;

    // ====================================================================
    // Module Instantiations
    // ====================================================================

    // ── Controller ───────────────────────────────────────────────────
    controller #(
        .ARRAY_SIZE  (ARRAY_SIZE)
    ) u_controller (
        .clk         (clk),
        .rst_n       (rst_n),
        // from host
        .valid_in    (valid_in),
        .tile_done   (tile_done),
        .last_pass   (last_pass),
        //to host
        .ready_in    (ready_in),
        // to memory
        .write_addr  (write_addr),
        .write_en    (write_en),
        // to memory and feeder
        .swap        (swap),
        // to feeder
        .drain_en    (drain_en),
        // from feeder
        .drain_done  (drain_done),
        // to feeder and systolic_array
        .clear       (clear),
        // to output_processor
        .output_en   (output_en),
        // from output_processor
        .output_done (output_done)
    );

    // ── Memory ───────────────────────────────────────────────────────
    memory #(
    ) u_memory (
        .clk         (clk),
        .rst_n       (rst_n),
        // from host
        .write_data  (data_in),
        // from controller
        .write_addr  (write_addr),
        .write_en    (write_en),
        .swap        (swap),
        // to feeder
        .read_addr   (read_addr),
        .read_en     (read_en),
        .read_data   (sram_data)
    );

    // ── Feeder ───────────────────────────────────────────────────────
    feeder #(
        .ARRAY_SIZE  (ARRAY_SIZE)
    ) u_feeder (
        .clk         (clk),
        .rst_n       (rst_n),
        // from memory
        .sram_data   (sram_data),
        // to memory
        .read_addr   (read_addr),
        .read_en     (read_en),
        // from controller
        .start       (swap),
        .drain_en    (drain_en),
        .clear       (clear),
        // to systolic_array
        .a_in        (a_in),
        .b_in        (b_in),
        .valid       (valid),
        // to controller
        .drain_done  (drain_done)
    );

    // ── Systolic Array ───────────────────────────────────────────────
    systolic_array #(
        .ARRAY_SIZE  (ARRAY_SIZE),
        .DATA_WIDTH  (DATA_WIDTH),
        .ACCUM_WIDTH (ACCUM_WIDTH)
    ) u_systolic_array (
        .clk         (clk),
        .rst_n       (rst_n),
        // from feeder
        .a_in        (a_in),
        .b_in        (b_in),
        .valid       (valid),
        // from controller
        .clear       (clear),
        // to output_processor
        .results     (results)
    );

    // ── Output Processor ─────────────────────────────────────────────
    output_processor #(
        .ARRAY_SIZE  (ARRAY_SIZE),
        .DATA_WIDTH  (DATA_WIDTH),
        .ACCUM_WIDTH (ACCUM_WIDTH)
    ) u_output_processor (
        .clk         (clk),
        .rst_n       (rst_n),
        // from systolic_array
        .results     (results),
        // from controller
        .output_en   (output_en),
        // to host
        .ready_out   (ready_out),
        .data_out    (data_out),
        .valid_out   (valid_out),
        // to controller and host 
        .output_done (output_done)
    );

endmodule

`default_nettype wire
