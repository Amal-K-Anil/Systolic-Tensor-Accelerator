// =======================================================================================
// mac_unit.sv
//
// mac_unit is a single processing element (PE) of the systolic array. Each cycle it
// receives a_in from its western neighbour (or the array's left edge) and b_in from
// its northern neighbour (or the array's top edge), multiplies them, and accumulates
// the result into accum_out -- output-stationary: accum_out holds the running partial
// sum across every valid pulse for the whole computation, only clearing between runs.
//
// Operation overview:
//   The multiply itself is delegated to booth_multiplier (reviewed and verified
//   separately) rather than a plain a_in*b_in, for area efficiency on the target
//   process. a_out/b_out simply forward a_in/b_in one cycle later to the eastern/
//   southern neighbour -- this is what propagates the diagonal wavefront through the
//   array; mac_unit itself has no notion of "skew," it only ever forwards what it
//   received the previous cycle.
// =======================================================================================

`default_nettype none

module mac_unit #(
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21
)(
    input  logic                            clk,
    input  logic                            rst_n,

    input  logic signed [DATA_WIDTH-1:0]    a_in,        // from western neighbour
    input  logic signed [DATA_WIDTH-1:0]    b_in,        // from northern neighbour
    input  logic                            valid,       // accumulate this cycle
    input  logic                            clear,       // reset accum_out for next run

    output logic signed [DATA_WIDTH-1:0]    a_out,       // to eastern neighbour
    output logic signed [DATA_WIDTH-1:0]    b_out,       // to southern neighbour
    output logic signed [ACCUM_WIDTH-1:0]   accum_out    // running partial sum (output-stationary)
);

    logic signed [2*DATA_WIDTH-1:0] product;

    booth_multiplier #(
        .DATA_WIDTH (DATA_WIDTH)
    ) u_booth_multiplier (
        .multiplicand (a_in),
        .multiplier   (b_in),
        .product      (product)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out     <= '0;
            b_out     <= '0;
            accum_out <= '0;
        end else if (clear) begin
            a_out     <= '0;
            b_out     <= '0;
            accum_out <= '0;
        end else if (valid) begin
            a_out     <= a_in;
            b_out     <= b_in;
            accum_out <= accum_out +
                {{(ACCUM_WIDTH-2*DATA_WIDTH){product[2*DATA_WIDTH-1]}}, product};
        end
    end

endmodule

`default_nettype wire
