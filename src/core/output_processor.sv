// =======================================================================================
// output_processor.sv
//
// output_processor serializes the systolic array's accumulator results into a
// byte-wide AXI4-Stream output, one result per cycle, row-major across the array
// (row 0 col 0, row 0 col 1, ... row N-1 col N-1). Each result is optionally
// shifted (SHIFT_BITS) then saturated to [SAT_MIN, SAT_MAX] before truncation to
// DATA_WIDTH.
//
// Operation overview:
//   output_en is driven externally by feeder's drain_done (a latch: high once
//   the pipeline has been flushed, until cleared) and used directly as the
//   serialize-enable — row/col only ever advance while output_en is high, and
//   simply hold at 0 otherwise.
//
//   output_done is self-generated here: a single-cycle pulse that fires the
//   exact cycle the true final result transfers (out_valid && out_ready &&
//   out_last). It serves two roles — it resets this module's own row/col
//   counters, and it is wired externally (in accelerator_core) to feeder's and
//   the MAC array's clear inputs — mirroring how feeder self-generates its own
//   drain trigger from a_last/b_last rather than depending on a controller.
// =======================================================================================

`default_nettype none

module output_processor #(
    parameter ARRAY_SIZE  = 8,
    parameter ACCUM_WIDTH = 21,
    parameter DATA_WIDTH  = 8,
    parameter SHIFT_BITS  = 0,  // 0 = pure clip
    parameter signed [ACCUM_WIDTH-1:0] SAT_MAX = (1 <<< (DATA_WIDTH-1)) - 1,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MIN = -(1 <<< (DATA_WIDTH-1))
)(
    input  logic                                         clk,
    input  logic                                         rst_n,

    // Systolic Array
    input  logic [ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH-1:0] results,     // one value per MAC

    // Feeder
    input  logic                                         output_en,   // wired to drain_done
    output logic                                         output_done, // wired to clear

    // Host Interface (AXI4-Stream, source side)
    input  logic                                         out_ready,   // host ready for a result byte
    output logic [DATA_WIDTH-1:0]                        out_data,    // saturated, quantized result byte
    output logic                                         out_valid,   // out_data valid this cycle
    output logic                                         out_last     // true final result of this pass
);

    localparam COUNT_W = $clog2(ARRAY_SIZE);
    localparam [DATA_WIDTH-1:0] OUT_MAX = DATA_WIDTH'(SAT_MAX);
    localparam [DATA_WIDTH-1:0] OUT_MIN = DATA_WIDTH'(SAT_MIN);

    logic [COUNT_W-1:0] row, col;


    // ===================================================================================
    //  Result Unpacking
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] result_matrix [0:ARRAY_SIZE-1][0:ARRAY_SIZE-1];
   
    genvar ur, uc;
    generate
        for (ur = 0; ur < ARRAY_SIZE; ur = ur + 1) begin : gen_unpack_row
            for (uc = 0; uc < ARRAY_SIZE; uc = uc + 1) begin : gen_unpack_col
                localparam integer RESULT_INDEX = ur * ARRAY_SIZE + uc;
                assign result_matrix[ur][uc] = $signed(results[RESULT_INDEX * ACCUM_WIDTH +: ACCUM_WIDTH]);
            end
        end
    endgenerate


    // ===================================================================================
    //  Result Selection
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] selected_row [0:ARRAY_SIZE-1];
    logic signed [ACCUM_WIDTH-1:0] raw_result;
    integer sel_row, sel_col;

    always_comb begin
        raw_result = '0;
        for (sel_col = 0; sel_col < ARRAY_SIZE; sel_col = sel_col + 1) begin
            selected_row[sel_col] = '0;
            for (sel_row = 0; sel_row < ARRAY_SIZE; sel_row = sel_row + 1) begin
                if (row == COUNT_W'(sel_row))
                    selected_row[sel_col] = result_matrix[sel_row][sel_col];
            end
            if (col == COUNT_W'(sel_col))
                raw_result = selected_row[sel_col];
        end
    end


    // ===================================================================================
    //  Quantization
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] shifted_result;

    assign shifted_result = raw_result >>> SHIFT_BITS;

    assign out_data = (shifted_result > SAT_MAX) ? OUT_MAX :
                      (shifted_result < SAT_MIN) ? OUT_MIN :
                                                   shifted_result[DATA_WIDTH-1:0];


    // ===================================================================================
    //  Serialization Control
    // ===================================================================================
    assign out_valid    = output_en;
    assign out_last     = (row == COUNT_W'(ARRAY_SIZE-1)) && (col == COUNT_W'(ARRAY_SIZE-1));
    assign output_done  = out_valid && out_ready && out_last;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row <= '0;
            col <= '0;
        end else if (output_done) begin
            row <= '0;
            col <= '0;
        end else if (out_valid && out_ready) begin
            if (col == COUNT_W'(ARRAY_SIZE-1)) begin
                col <= '0;
                row <= row + 1'b1;
            end else begin
                col <= col + 1'b1;
            end
        end
    end

endmodule

`default_nettype wire
