module mac_unit #(
parameter DATA_WIDTH = 8,   // int8 input width
parameter ACCUM_WIDTH = 21
) (
        input logic clk,
        input  logic rst_n,    // _n: negative logic
        input logic signed [(DATA_WIDTH-1):0] a_in,     // int8
        input logic signed [(DATA_WIDTH-1):0] b_in,
        input logic valid,
        input logic clear,
        output logic  signed [(DATA_WIDTH-1):0] a_out,
        output logic  signed [(DATA_WIDTH-1):0]b_out,
        output logic  signed [ACCUM_WIDTH-1:0] accum_out
    );
    
    
  always_ff @(posedge clk or negedge rst_n)
  begin
    if(!rst_n || clear)
    begin
      a_out<= '0;
      b_out<= '0;
      accum_out<= '0;
    end
      else if (valid) 
      begin
        a_out<=a_in;
        b_out<=b_in;
      accum_out<=accum_out +ACCUM_WIDTH'(a_in*b_in);    //removes ambiguity and extends result to 21 bit signed
      end
    end

endmodule