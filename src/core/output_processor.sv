`timescale 1ns/1ps

module output_processor #(
    parameter ARRAY_SIZE  = 8,           
    parameter ACCUM_WIDTH = 21,          
    parameter SAT_POS     = 127,         
    parameter SAT_NEG     = -128,        
    parameter DATA_WIDTH  = 8            
)(
    input  logic clk,
    input  logic rst_n,
    
    // 1D packed array for Yosys + Icarus compatibility
    input  logic [(ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH)-1:0] results,
    
    input  logic output_en,
    input  logic ready_out,
    output logic [DATA_WIDTH-1:0] data_out,
    output logic valid_out,
    output logic output_done
);

    localparam COUNTER_WIDTH = $clog2(ARRAY_SIZE);

    logic [COUNTER_WIDTH-1:0] row, col;
    logic       finished;
    logic       done_pulse;

    logic signed [ACCUM_WIDTH-1:0] sel;

    // Unpack the 1D flat port into a clean 2D array
    logic signed [ACCUM_WIDTH-1:0] results_array [0:ARRAY_SIZE-1][0:ARRAY_SIZE-1];
    
    genvar i, j;
    generate
        for (i = 0; i < ARRAY_SIZE; i = i + 1) begin : gen_row
            for (j = 0; j < ARRAY_SIZE; j = j + 1) begin : gen_col
                assign results_array[i][j] = results[(((i * ARRAY_SIZE) + j) * ACCUM_WIDTH) +: ACCUM_WIDTH];
            end
        end
    endgenerate

    // Grab the active accumulator value based on the current counter
    assign sel = results_array[row][col];

    // ====================================================================
    // THE ICARUS FIX: Move saturation to a continuous assign statement.
    // Icarus handles part-selects perfectly here without throwing errors.
    // ====================================================================
    assign data_out = (sel > $signed(SAT_POS)) ? SAT_POS[DATA_WIDTH-1:0] :
                      (sel < $signed(SAT_NEG)) ? SAT_NEG[DATA_WIDTH-1:0] :
                      sel[DATA_WIDTH-1:0];

    assign valid_out   = output_en && !finished;
    assign output_done = done_pulse;

    // Counter State Machine
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row <= '0;
            col <= '0;
            finished <= 1'b0;
            done_pulse <= 1'b0;
        end else if (!output_en) begin
            row <= '0;
            col <= '0;
            finished <= 1'b0;
            done_pulse <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            if (valid_out && ready_out) begin
                if (row == ARRAY_SIZE-1 && col == ARRAY_SIZE-1) begin
                    finished   <= 1'b1;
                    done_pulse <= 1'b1;
                end else if (col == ARRAY_SIZE-1) begin
                    col <= '0;
                    row <= row + 1'b1;
                end else begin
                    col <= col + 1'b1;
                end
            end
        end
    end

endmodule