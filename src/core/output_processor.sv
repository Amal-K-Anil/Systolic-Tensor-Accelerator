/**

 * Implements Architecture Spec v1.0, Section 4.9 exactly.
 */
`timescale 1ns/1ps

module output_processor #(
    parameter ARRAY_SIZE  = 8,
    parameter ACCUM_WIDTH = 21
)(
    input  logic clk,
    input  logic rst_n,
    input  logic signed [ACCUM_WIDTH-1:0] results [ARRAY_SIZE-1:0][ARRAY_SIZE-1:0],
    input  logic output_en,
    input  logic ready_out,
    output logic [7:0] data_out,
    output logic valid_out,
    output logic output_done
);
    logic [2:0] row, col;
    logic       finished;
    logic       done_pulse;

    logic signed [ACCUM_WIDTH-1:0] sel;
    logic [7:0] sat;
    assign sel = results[row][col];
    always_comb begin
        if (sel > 21'sd127)        sat = 8'h7F;
        else if (sel < -21'sd128)  sat = 8'h80;
        else                       sat = sel[7:0];
    end

    assign data_out    = sat;
    assign valid_out   = output_en && !finished;
    assign output_done = done_pulse;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row <= '0; col <= '0; finished <= 1'b0; done_pulse <= 1'b0;
        end else if (!output_en) begin
            row <= '0; col <= '0; finished <= 1'b0; done_pulse <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            if (valid_out && ready_out) begin
                if (row == ARRAY_SIZE-1 && col == ARRAY_SIZE-1) begin
                    finished   <= 1'b1;
                    done_pulse <= 1'b1;
                end else if (col == ARRAY_SIZE-1) begin
                    col <= '0; row <= row + 1'b1;
                end else begin
                    col <= col + 1'b1;
                end
            end
        end
    end
endmodule