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
//   the pipeline has been flushed, until cleared). Serialization proceeds while
//   output_en is high.
//
//   Results pass through a three-stage pipeline. Each row first selects its
//   current column into selected_col_pipe, then the current row is selected into
//   result_pipe_data, followed by registered quantized output.
//
//   The column-selection control is replicated per row to reduce fanout.
//
//   Pipeline backpressure uses a single global advance condition. If the output
//   register contains valid data and the host is not ready, all pipeline stages
//   and serialization counters hold together.
//
//   final_transfer detects acceptance of the true final result
//   (out_valid && out_ready && out_last). This condition is registered into
//   output_done, producing a one-cycle pulse on the following cycle.
//
//   final_transfer also generates replicated clear signals for the MAC array.
//   output_done is wired externally to feeder cleanup.
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
    output logic [ARRAY_SIZE*ARRAY_SIZE-1:0]             clear,       // one clear per MAC

    // Feeder
    input  logic                                         output_en,   // wired to drain_done
    (* keep = "true" *)
    output logic                                         output_done, // wired to feeder cleanup

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
logic all_loaded;


// ===================================================================================
//  Local Column Counters
// ===================================================================================
logic [COUNT_W-1:0] col_local [0:ARRAY_SIZE-1];


// ===================================================================================
//  Result Unpacking
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] result_matrix [0:ARRAY_SIZE-1][0:ARRAY_SIZE-1];

genvar ur, uc;
generate
    for (ur = 0; ur < ARRAY_SIZE; ur = ur + 1) begin : gen_unpack_row
        for (uc = 0; uc < ARRAY_SIZE; uc = uc + 1) begin : gen_unpack_col
            localparam integer RESULT_INDEX = ur * ARRAY_SIZE + uc;
            assign result_matrix[ur][uc] =
                $signed(results[RESULT_INDEX * ACCUM_WIDTH +: ACCUM_WIDTH]);
        end
    end
endgenerate


// ===================================================================================
//  Column Selection
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] selected_col [0:ARRAY_SIZE-1];
integer sel_row, sel_col;

always_comb begin
    for (sel_row = 0; sel_row < ARRAY_SIZE; sel_row = sel_row + 1) begin
        selected_col[sel_row] = '0;

        for (sel_col = 0; sel_col < ARRAY_SIZE; sel_col = sel_col + 1) begin
            if (col_local[sel_row] == COUNT_W'(sel_col))
                selected_col[sel_row] = result_matrix[sel_row][sel_col];
        end
    end
end


// ===================================================================================
//  Column-Selection Pipeline
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] selected_col_pipe [0:ARRAY_SIZE-1];
logic [COUNT_W-1:0] selected_pipe_row;
logic selected_pipe_valid;
logic selected_pipe_last;


// ===================================================================================
//  Row Selection
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] raw_result;
integer row_sel;

always_comb begin
    raw_result = '0;

    for (row_sel = 0; row_sel < ARRAY_SIZE; row_sel = row_sel + 1) begin
        if (selected_pipe_row == COUNT_W'(row_sel))
            raw_result = selected_col_pipe[row_sel];
    end
end


// ===================================================================================
//  Result Pipeline
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] result_pipe_data;
logic result_pipe_valid;
logic result_pipe_last;


// ===================================================================================
//  Quantization
// ===================================================================================
logic signed [ACCUM_WIDTH-1:0] shifted_result;
logic [DATA_WIDTH-1:0] quantized_result;

assign shifted_result = result_pipe_data >>> SHIFT_BITS;

assign quantized_result = (shifted_result > SAT_MAX) ? OUT_MAX :
                          (shifted_result < SAT_MIN) ? OUT_MIN :
                                                     shifted_result[DATA_WIDTH-1:0];


// ===================================================================================
//  Pipeline Handshake
//
//  The complete pipeline advances together.
//
//  If the output register is empty, the pipeline may advance.
//  If the output register is valid, the pipeline advances only when the host
//  accepts the current output.
//
//  This removes the combinational ready chain through every pipeline stage.
// ===================================================================================
logic pipeline_advance;
logic selected_is_last;
logic final_transfer;

assign pipeline_advance =
    !out_valid ||
    out_ready;

assign selected_is_last =
    (row == COUNT_W'(ARRAY_SIZE-1)) &&
    (col == COUNT_W'(ARRAY_SIZE-1));

assign final_transfer =
    out_valid &&
    out_ready &&
    out_last;


// ===================================================================================
//  Clear Distribution
// ===================================================================================
genvar clear_row, clear_col;
generate
    for (clear_row = 0; clear_row < ARRAY_SIZE; clear_row = clear_row + 1) begin : g_clear_row
        for (clear_col = 0; clear_col < ARRAY_SIZE; clear_col = clear_col + 1) begin : g_clear_col
            (* keep = "true" *)
            logic clear_r;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    clear_r <= 1'b0;
                else
                    clear_r <= final_transfer;
            end

            assign clear[clear_row*ARRAY_SIZE + clear_col] = clear_r;
        end
    end
endgenerate


// ===================================================================================
//  Local Column Counter Distribution
// ===================================================================================
genvar col_row;
generate
    for (col_row = 0; col_row < ARRAY_SIZE; col_row = col_row + 1) begin : g_col_local
        (* keep = "true" *)
        logic [COUNT_W-1:0] col_r;

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                col_r <= '0;
            end else if (final_transfer) begin
                col_r <= '0;
            end else if (
                pipeline_advance &&
                output_en &&
                !output_done &&
                !all_loaded
            ) begin
                if (col_r == COUNT_W'(ARRAY_SIZE-1))
                    col_r <= '0;
                else
                    col_r <= col_r + 1'b1;
            end
        end

        assign col_local[col_row] = col_r;
    end
endgenerate


// ===================================================================================
//  Serialization Control
// ===================================================================================
integer pipe_row;

always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        row <= '0;
        col <= '0;
        all_loaded <= 1'b0;

        selected_pipe_row   <= '0;
        selected_pipe_valid <= 1'b0;
        selected_pipe_last  <= 1'b0;

        for (pipe_row = 0; pipe_row < ARRAY_SIZE; pipe_row = pipe_row + 1) begin
            selected_col_pipe[pipe_row] <= '0;
        end

        result_pipe_data  <= '0;
        result_pipe_valid <= 1'b0;
        result_pipe_last  <= 1'b0;

        out_data  <= '0;
        out_valid <= 1'b0;
        out_last  <= 1'b0;

        output_done <= 1'b0;
    end else begin

        // Registered feeder cleanup pulse.
        output_done <= final_transfer;

        // ---------------------------------------------------------------------------
        // Final result accepted
        // ---------------------------------------------------------------------------
        if (final_transfer) begin
            row <= '0;
            col <= '0;
            all_loaded <= 1'b0;

            selected_pipe_valid <= 1'b0;
            selected_pipe_last  <= 1'b0;

            result_pipe_valid <= 1'b0;
            result_pipe_last  <= 1'b0;

            out_valid <= 1'b0;
            out_last  <= 1'b0;

        end else if (pipeline_advance) begin

            // -----------------------------------------------------------------------
            // Stage 3: result pipeline -> output register
            // -----------------------------------------------------------------------
            if (result_pipe_valid) begin
                out_data  <= quantized_result;
                out_valid <= 1'b1;
                out_last  <= result_pipe_last;
            end else begin
                out_valid <= 1'b0;
                out_last  <= 1'b0;
            end


            // -----------------------------------------------------------------------
            // Stage 2: registered column selection -> row selector
            // -----------------------------------------------------------------------
            if (selected_pipe_valid) begin
                result_pipe_data  <= raw_result;
                result_pipe_valid <= 1'b1;
                result_pipe_last  <= selected_pipe_last;
            end else begin
                result_pipe_valid <= 1'b0;
                result_pipe_last  <= 1'b0;
            end


            // -----------------------------------------------------------------------
            // Stage 1: column selector -> column-selection pipeline
            // -----------------------------------------------------------------------
            if (
                output_en &&
                !output_done &&
                !all_loaded
            ) begin
                for (pipe_row = 0; pipe_row < ARRAY_SIZE; pipe_row = pipe_row + 1) begin
                    selected_col_pipe[pipe_row] <= selected_col[pipe_row];
                end

                selected_pipe_row   <= row;
                selected_pipe_valid <= 1'b1;
                selected_pipe_last  <= selected_is_last;

                if (selected_is_last) begin
                    all_loaded <= 1'b1;
                end else if (col == COUNT_W'(ARRAY_SIZE-1)) begin
                    col <= '0;
                    row <= row + 1'b1;
                end else begin
                    col <= col + 1'b1;
                end

            end else begin
                selected_pipe_valid <= 1'b0;
                selected_pipe_last  <= 1'b0;
            end
        end
    end
end

endmodule

`default_nettype wire