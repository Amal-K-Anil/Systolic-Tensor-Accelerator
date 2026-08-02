module systolic_array #(
    parameter ARRAY_SIZE  = 8,
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21
)(
    input  logic clk,
    input  logic rst_n,

    input  logic [ARRAY_SIZE*DATA_WIDTH-1:0]             a_in,
    input  logic [ARRAY_SIZE*DATA_WIDTH-1:0]             b_in,
    input  logic                                         valid,
    input  logic                                         clear,
    output logic [ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH-1:0] results
);

    logic signed [DATA_WIDTH-1:0] a_in_arr [0:ARRAY_SIZE-1];
    logic signed [DATA_WIDTH-1:0] b_in_arr [0:ARRAY_SIZE-1];

    logic signed [ACCUM_WIDTH-1:0] results_arr [0:ARRAY_SIZE-1][0:ARRAY_SIZE-1];

    logic signed [DATA_WIDTH-1:0] a_bus [0:ARRAY_SIZE-1][0:ARRAY_SIZE];
    logic signed [DATA_WIDTH-1:0] b_bus [0:ARRAY_SIZE][0:ARRAY_SIZE-1];

    genvar pi, pj;
    generate
        for (pi = 0; pi < ARRAY_SIZE; pi = pi + 1) begin : unpack_inputs
            assign a_in_arr[pi] = a_in[pi*DATA_WIDTH +: DATA_WIDTH];
            assign b_in_arr[pi] = b_in[pi*DATA_WIDTH +: DATA_WIDTH];

            for (pj = 0; pj < ARRAY_SIZE; pj = pj + 1) begin : pack_outputs
                assign results[(pi*ARRAY_SIZE + pj)*ACCUM_WIDTH +: ACCUM_WIDTH]
                    = results_arr[pi][pj];
            end
        end
    endgenerate

    genvar i;
    generate
        for (i = 0; i < ARRAY_SIZE; i = i + 1) begin : left_edge
            assign a_bus[i][0] = a_in_arr[i];
        end
    endgenerate

    genvar j;
    generate
        for (j = 0; j < ARRAY_SIZE; j = j + 1) begin : top_edge
            assign b_bus[0][j] = b_in_arr[j];
        end
    endgenerate

    genvar r, c;
    generate
        for (r = 0; r < ARRAY_SIZE; r = r + 1) begin : gen_rows
            for (c = 0; c < ARRAY_SIZE; c = c + 1) begin : gen_columns

                mac_unit #(
                    .DATA_WIDTH  (DATA_WIDTH),
                    .ACCUM_WIDTH (ACCUM_WIDTH)
                ) pe (
                    .clk       (clk),
                    .rst_n     (rst_n),
                    .valid     (valid),
                    .clear     (clear),

                    .a_in      (a_bus[r][c]),
                    .b_in      (b_bus[r][c]),

                    .a_out     (a_bus[r][c+1]),
                    .b_out     (b_bus[r+1][c]),

                    .accum_out (results_arr[r][c])
                );

            end
        end
    endgenerate

endmodule
