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
//   output_en is high. The three pipeline stages advance together and stall when
//   out_valid is high and out_ready is low.
//
//   final_transfer detects acceptance of the true final result
//   (out_valid && out_ready && out_last). This condition is registered into
//   output_done, producing a one-cycle pulse on the following cycle.
//
//   final_transfer also generates the replicated clear signals for the MAC array.
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
    logic final_result_loaded;
    logic pipeline_advance;
    logic final_transfer;

    assign pipeline_advance = !out_valid || out_ready;
    assign final_transfer   = out_valid && out_ready && out_last;


    // ===================================================================================
    //  Result Unpacking
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] result_matrix [0:ARRAY_SIZE-1][0:ARRAY_SIZE-1];

    generate
        for (genvar r = 0; r < ARRAY_SIZE; r = r + 1) begin : gen_unpack_row
            for (genvar c = 0; c < ARRAY_SIZE; c = c + 1) begin : gen_unpack_col
                assign result_matrix[r][c] = $signed(results[(r * ARRAY_SIZE + c) * ACCUM_WIDTH +: ACCUM_WIDTH]);
            end
        end
    endgenerate


    // ===================================================================================
    //  Pipeline Stage 1 - Column Selection
    // ===================================================================================
    logic [COUNT_W-1:0] col_local [0:ARRAY_SIZE-1];

    logic signed [ACCUM_WIDTH-1:0] column_mux_result [0:ARRAY_SIZE-1];
    logic signed [ACCUM_WIDTH-1:0] intermediate_result [0:ARRAY_SIZE-1];
    logic intermediate_valid;
    logic intermediate_last;

    logic [COUNT_W-1:0] result_row;


    // Replicated column counters reduce column-selection fanout.
    generate
        for (genvar r = 0; r < ARRAY_SIZE; r = r + 1) begin : g_col_local

            (* keep = "true" *)
            logic [COUNT_W-1:0] col_r;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    col_r <= '0;
                end else if (final_transfer) begin
                    col_r <= '0;
                end else if (pipeline_advance && output_en && !output_done && !final_result_loaded) begin
                    if (col_r == COUNT_W'(ARRAY_SIZE-1))
                        col_r <= '0;
                    else
                        col_r <= col_r + 1'b1;
                end
            end

            assign col_local[r] = col_r;

        end
    endgenerate


    // Select one column value from each result row.
    always_comb begin
        for (int r = 0; r < ARRAY_SIZE; r = r + 1) begin
            column_mux_result[r] = '0;

            for (int c = 0; c < ARRAY_SIZE; c = c + 1) begin
                if (col_local[r] == COUNT_W'(c))
                    column_mux_result[r] = result_matrix[r][c];
            end
        end
    end


    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin
            for (int r = 0; r < ARRAY_SIZE; r = r + 1)
                intermediate_result[r] <= '0;
            intermediate_valid <= 1'b0;
            intermediate_last  <= 1'b0;
            result_row         <= '0;

        end else if (final_transfer) begin
            intermediate_valid <= 1'b0;
            intermediate_last  <= 1'b0;

        end else if (pipeline_advance) begin
            if (output_en && !output_done && !final_result_loaded) begin
                for (int r = 0; r < ARRAY_SIZE; r = r + 1)
                    intermediate_result[r] <= column_mux_result[r];

                intermediate_valid <= 1'b1;
                intermediate_last  <= (row == COUNT_W'(ARRAY_SIZE-1)) && (col == COUNT_W'(ARRAY_SIZE-1));
                result_row         <= row;

            end else begin
                intermediate_valid <= 1'b0;
                intermediate_last  <= 1'b0;

            end
        end
    end


    // ===================================================================================
    //  Pipeline Stage 2 - Row Selection
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] row_mux_result;
    logic signed [ACCUM_WIDTH-1:0] raw_result;
    logic raw_valid;
    logic raw_last;


    // Select the required row from the registered column results.
    always_comb begin
        row_mux_result = '0;

        for (int r = 0; r < ARRAY_SIZE; r = r + 1) begin
            if (result_row == COUNT_W'(r))
                row_mux_result = intermediate_result[r];
        end
    end


    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin
            raw_result <= '0;
            raw_valid  <= 1'b0;
            raw_last   <= 1'b0;

        end else if (final_transfer) begin
            raw_valid <= 1'b0;
            raw_last  <= 1'b0;

        end else if (pipeline_advance) begin
            if (intermediate_valid) begin
                raw_result <= row_mux_result;
                raw_valid  <= 1'b1;
                raw_last   <= intermediate_last;

            end else begin
                raw_valid <= 1'b0;
                raw_last  <= 1'b0;

            end
        end
    end


    // ===================================================================================
    //  Pipeline Stage 3 - Quantization and Output
    // ===================================================================================
    logic signed [ACCUM_WIDTH-1:0] shifted_result;
    logic        [DATA_WIDTH-1:0]  quantized_result;

    assign shifted_result = raw_result >>> SHIFT_BITS;

    assign quantized_result = (shifted_result > SAT_MAX) ? OUT_MAX :
                              (shifted_result < SAT_MIN) ? OUT_MIN :
                                                           shifted_result[DATA_WIDTH-1:0];

    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin
            out_data  <= '0;
            out_valid <= 1'b0;
            out_last  <= 1'b0;

        end else if (final_transfer) begin
            out_valid <= 1'b0;
            out_last  <= 1'b0;

        end else if (pipeline_advance) begin
            if (raw_valid) begin
                out_data  <= quantized_result;
                out_valid <= 1'b1;
                out_last  <= raw_last;

            end else begin
                out_valid <= 1'b0;
                out_last  <= 1'b0;

            end
        end
    end


    // ===================================================================================
    //  Serialization and Cleanup Control
    // ===================================================================================
    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin
            row                 <= '0;
            col                 <= '0;
            final_result_loaded <= 1'b0;
            output_done         <= 1'b0;

        end else begin
            output_done <= final_transfer;

            if (final_transfer) begin
                row                 <= '0;
                col                 <= '0;
                final_result_loaded <= 1'b0;

            end else if (pipeline_advance && output_en && !output_done && !final_result_loaded) begin
                if ((row == COUNT_W'(ARRAY_SIZE-1)) && (col == COUNT_W'(ARRAY_SIZE-1))) begin
                    final_result_loaded <= 1'b1;
                end else if (col == COUNT_W'(ARRAY_SIZE-1)) begin
                    col <= '0;
                    row <= row + 1'b1;
                end else begin
                    col <= col + 1'b1;

                end
            end
        end
    end

    // Replicated clear registers reduce clear fanout across the MAC array.
    generate
        for (genvar i = 0; i < ARRAY_SIZE * ARRAY_SIZE; i = i + 1) begin : g_clear

            (* keep = "true" *)
            logic clear_r;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    clear_r <= 1'b0;
                else
                    clear_r <= final_transfer;
            end

            assign clear[i] = clear_r;

        end
    endgenerate


endmodule

`default_nettype wire
