// =======================================================================================
// feeder.sv
//
// Feeder is the data-path entry point of the accelerator_core. It receives two
// independent AXI4-Stream channels from the host — activation data on the A lane
// and weight data on the B lane — and reorganizes them into the diagonally skewed
// wavefront the systolic array needs for output-stationary matrix multiplication.
//
// Operation overview:
//   Each "vector" is one column of A paired with one row of B (ARRAY_SIZE words
//   per lane). Feeder synchronizes the two lanes so neither can outrun the other
//   within a vector: a lane that finishes early is held (a_ready/b_ready drop)
//   until its partner catches up. Once both lanes deliver their 8th word,
//   vector_done fires and the vector is captured into staging registers.
//
//   Every vector shift, staging is pushed one step into a triangular skew
//   buffer, so row i of the array receives its data i valid cycles after row 0 — 
//   this is what produces the correct diagonal wavefront. When the host asserts
//   a_last/b_last on the true final word of each lane, drain_en latches and
//   feeder self-triggers a 2*(ARRAY_SIZE-1)-cycle flush, injecting zero
//   wavefronts to push the remaining data out of the skew buffer and array.
//   drain_done then latches (one cycle after the last flush wavefront, to let
//   the MAC array's registers settle) so output_processor can safely start.
// =======================================================================================

`default_nettype none

module feeder #(
    parameter ARRAY_SIZE = 8,
    parameter DATA_WIDTH = 8
)(
    input  logic                              clk,
    input  logic                              rst_n,

    // Host Interface - Activation channel (AXI4-Stream, sink side)
    input  logic [DATA_WIDTH-1:0]             a_data,      // activation word
    input  logic                              a_valid,     // activation word valid
    output logic                              a_ready,     // may accept activation word
    input  logic                              a_last,      // true final word, activation stream

    // Host Interface - Weight channel (AXI4-Stream, sink side)
    input  logic [DATA_WIDTH-1:0]             b_data,      // weight word
    input  logic                              b_valid,     // weight word valid
    output logic                              b_ready,     // may accept weight word
    input  logic                              b_last,      // true final word, weight stream

    // Output Processor
    input  logic                              clear,       // reset pulse, from output_processor
    output logic                              drain_done,  // safe for output_processor to start

    // Systolic Array
    output logic [ARRAY_SIZE*DATA_WIDTH-1:0]  a_out,       // skewed activation words
    output logic [ARRAY_SIZE*DATA_WIDTH-1:0]  b_out,       // skewed weight words
    output logic                              valid        // a_out/b_out valid this cycle
);

    // ===================================================================================
    //  Constants
    // ===================================================================================
    localparam COUNT_W    = $clog2(ARRAY_SIZE);
    localparam DRAIN_LEN  = 2 * (ARRAY_SIZE - 1);                 // flush cycles needed
    localparam DRAIN_W    = $clog2(DRAIN_LEN);
    localparam SKEW_DEPTH = (ARRAY_SIZE * (ARRAY_SIZE - 1)) / 2;  // sum of rows 1..N-1


    // ===================================================================================
    //  Input Sync and Handshaking
    // ===================================================================================
    logic [COUNT_W-1:0] a_count, b_count;
    logic a_active, b_active;                // confirmed transfer, this cycle
    logic a_vector_last, b_vector_last;      // this transfer is the vector's 8th word
    logic a_vector_last_r, b_vector_last_r;  // this lane's vector done, waiting on partner
    logic a_last_r, b_last_r;                // this lane's true final word transferred
    logic vector_done, drain_en;
    
    assign a_active = a_valid && a_ready;
    assign b_active = b_valid && b_ready;

    assign a_vector_last = a_active && (a_count == COUNT_W'(ARRAY_SIZE-1));
    assign b_vector_last = b_active && (b_count == COUNT_W'(ARRAY_SIZE-1));

    assign vector_done = (a_vector_last_r || a_vector_last) && (b_vector_last_r || b_vector_last);  // both lanes, now or latched
    assign drain_en    = (a_last_r || a_last) && (b_last_r || b_last);                              // stays high until clear

    assign a_ready = !a_vector_last_r && !a_last_r;
    assign b_ready = !b_vector_last_r && !b_last_r;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_count         <= '0;
            b_count         <= '0;
            a_vector_last_r <= 1'b0;
            b_vector_last_r <= 1'b0;
            a_last_r        <= 1'b0;
            b_last_r        <= 1'b0;
        end else if (clear) begin
            a_count         <= '0;
            b_count         <= '0;
            a_vector_last_r <= 1'b0;
            b_vector_last_r <= 1'b0;
            a_last_r        <= 1'b0;
            b_last_r        <= 1'b0;
        end else begin

            if (a_active)
                a_count <= a_vector_last ? '0 : (a_count + 1'b1);
            if (b_active)
                b_count <= b_vector_last ? '0 : (b_count + 1'b1);

            if (vector_done) begin
                a_vector_last_r <= 1'b0;
                b_vector_last_r <= 1'b0;
            end else begin
                if (a_vector_last) 
                    a_vector_last_r <= 1'b1;
                if (b_vector_last) 
                    b_vector_last_r <= 1'b1;
            end

            if (a_last) 
                a_last_r <= 1'b1;
            if (b_last)
                b_last_r <= 1'b1;

        end
    end


    // ===================================================================================
    //  Drain Sequencer
    // ===================================================================================
    logic drain_en_r;                 // flush currently in progress
    logic [DRAIN_W-1:0] drain_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drain_en_r  <= 1'b0;
            drain_count <= '0;
            drain_done  <= 1'b0;
        end else if (clear) begin
            drain_en_r  <= 1'b0;
            drain_count <= '0;
            drain_done  <= 1'b0;
        end else begin
            if (drain_en && !drain_en_r && drain_count == '0)
                drain_en_r <= 1'b1;
            else if (drain_en_r) begin
                if (drain_count == DRAIN_W'(DRAIN_LEN - 1))
                    drain_en_r <= 1'b0;
                else
                    drain_count <= drain_count + 1'b1;
            end
            drain_done <= !drain_en_r && (drain_count == DRAIN_W'(DRAIN_LEN - 1));
        end
    end


    // ===================================================================================
    //  Staging Registers
    // ===================================================================================
    logic [DATA_WIDTH-1:0] a_stage [0:ARRAY_SIZE-1];
    logic [DATA_WIDTH-1:0] b_stage [0:ARRAY_SIZE-1];

    genvar pos;
    generate
        for (pos = 0; pos < ARRAY_SIZE; pos = pos + 1) begin : g_stage
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    a_stage[pos] <= '0;
                    b_stage[pos] <= '0;
                end else if (clear) begin
                    a_stage[pos] <= '0;
                    b_stage[pos] <= '0;
                end else if (drain_en_r) begin
                    a_stage[pos] <= '0;  // flush: zeros for skew buffer to shift out
                    b_stage[pos] <= '0;
                end else begin
                    if (a_active && (a_count == COUNT_W'(pos)))
                        a_stage[pos] <= a_data;
                    if (b_active && (b_count == COUNT_W'(pos)))
                        b_stage[pos] <= b_data;
                end
            end
        end
    endgenerate


    // ===================================================================================
    //  Skew Buffer
    // ===================================================================================
    logic [DATA_WIDTH-1:0] a_skew [0:SKEW_DEPTH-1];
    logic [DATA_WIDTH-1:0] b_skew [0:SKEW_DEPTH-1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)      valid <= 1'b0;
        else if (clear)  valid <= 1'b0;
        else             valid <= vector_done || drain_en_r;
    end

    // row 0: no register, direct read from staging
    assign a_out[0 +: DATA_WIDTH] = a_stage[0];
    assign b_out[0 +: DATA_WIDTH] = b_stage[0];

    genvar row, stage;
    generate
        for (row = 1; row < ARRAY_SIZE; row = row + 1) begin : g_row
            localparam integer ROW_BASE = (row * (row - 1)) / 2;  // rows 1..N-1 have i stages

            for (stage = 0; stage < row; stage = stage + 1) begin : g_stage_row
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        a_skew[ROW_BASE+stage] <= '0;
                        b_skew[ROW_BASE+stage] <= '0;
                    end else if (clear) begin
                        a_skew[ROW_BASE+stage] <= '0;
                        b_skew[ROW_BASE+stage] <= '0;
                    end else if (valid) begin
                        if (stage == 0) begin
                            a_skew[ROW_BASE] <= a_stage[row];
                            b_skew[ROW_BASE] <= b_stage[row];
                        end else begin
                            a_skew[ROW_BASE+stage] <= a_skew[ROW_BASE+stage-1];
                            b_skew[ROW_BASE+stage] <= b_skew[ROW_BASE+stage-1];
                        end
                    end
                end
            end

            assign a_out[row*DATA_WIDTH +: DATA_WIDTH] = a_skew[ROW_BASE+row-1];
            assign b_out[row*DATA_WIDTH +: DATA_WIDTH] = b_skew[ROW_BASE+row-1];
        end
    endgenerate

endmodule

`default_nettype wire
