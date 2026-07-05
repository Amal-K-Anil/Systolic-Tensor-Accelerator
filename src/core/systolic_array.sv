module systolic_array #(
parameter ARRAY_SIZE = 8,  //array size nxn mac units
parameter DATA_WIDTH = 8,   // int8 input width
parameter ACCUM_WIDTH = 21
)(
input logic clk,
input logic rst_n,
input logic signed [DATA_WIDTH-1:0] a_in [ARRAY_SIZE-1:0],
input logic signed [DATA_WIDTH-1:0] b_in [ARRAY_SIZE-1:0],
input logic valid,
input logic clear,
output logic signed [ACCUM_WIDTH-1:0]
results [ARRAY_SIZE-1:0][ARRAY_SIZE-1:0]
);


//interconnection wires

 logic signed [(DATA_WIDTH-1):0]a_bus[(ARRAY_SIZE-1):0][(ARRAY_SIZE):0];
 logic signed [(DATA_WIDTH-1):0]b_bus[(ARRAY_SIZE):0][(ARRAY_SIZE-1):0];


// a_bus[0][0] ----> PE00 ----> a_bus[0][1] ----> PE01 ----> a_bus[0][2]

// a_bus[1][0] ----> PE10 ----> a_bus[1][1] ----> PE11 ----> a_bus[1][2]


 // pe matrix

//Left end assignments
generate
    for (genvar i=0; i<(ARRAY_SIZE) ; i++)
    begin
       assign a_bus[i][0]= a_in[i];  
    end
endgenerate

//Top edge assignments
generate
    for (genvar j=0; j<(ARRAY_SIZE) ; j++)
    begin
        assign b_bus[0][j]=b_in[j]; 
    end
endgenerate

 //Mac instantiations
generate
    for (genvar i=0; i<(ARRAY_SIZE); i++)
    begin : gen_rows
        for (genvar j=0; j<(ARRAY_SIZE); j++)
        begin :gen_columns
            // if j=0, accept a from a_inor else accept from left 
            // if i=0, accept input from b_in or else from above
            mac_unit #(.DATA_WIDTH(DATA_WIDTH),.ACCUM_WIDTH(ACCUM_WIDTH))
            pe(.clk(clk), .rst_n(rst_n), .valid(valid), .clear(clear),
            .a_in(a_bus[i][j]), .b_in(b_bus[i][j]), 
            .a_out(a_bus[i][j+1]), .b_out(b_bus[i+1][j]),
            .accum_out(results[i][j]));
        end
       
    end
endgenerate

endmodule


// mac_unit pe(.clk(clk), .rst_n(rst_n), .valid(valid), .clear(clear),
//     .a_in(a_in[i]), .b_in(b_in[i]), )

//  mac (
//         input logic clk,
//         input  logic rst_n,    // _n: negative logic
//         input logic signed [7:0] a_in,     // int8
//         input logic signed [7:0] b_in,
//         input logic valid,
//         input logic clear,
//         output logic  signed [7:0] a_out,
//         output logic  signed [7:0]b_out,
//         output logic  signed [20:0] acc
//     );