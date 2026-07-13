module partial_product_generator #(
    parameter DATA_WIDTH = 8
)(
    input  logic zero, sel2, neg,
    input  logic signed [DATA_WIDTH-1:0] multiplicand,
    output logic signed [DATA_WIDTH+1:0] pp_row,  // only DATA_WIDTH+2 bits needed
    output logic corr                              // correction bit (deferred +1)
);
    logic signed [DATA_WIDTH+1:0] mag;

    always_comb begin
        mag     = {{2{multiplicand[DATA_WIDTH-1]}}, multiplicand}; // sign-extend, free
        mag     = sel2 ? (mag <<< 1) : mag;                        // free (wire shift)
        pp_row  = zero ? '0 : (neg ? ~mag : mag);                  // XOR invert only
        corr    = (~zero) & neg;                                   // no adder here
    end
endmodule



// module partial_product_generator #(
//     parameter DATA_WIDTH = 8
// )(
//     input  logic [2:0] booth_op,
//     input  logic signed [DATA_WIDTH-1:0] multiplicand,

//     // Full-width partial product
//     output logic signed [(2*DATA_WIDTH)-1:0] partial_product
// );

//     // Sign-extended multiplicand
//     logic signed [(2*DATA_WIDTH)-1:0] multiplicand_ext;

//     always_comb begin

//         // Sign extension
//         multiplicand_ext =
//         {{DATA_WIDTH{multiplicand[DATA_WIDTH-1]}}, multiplicand};

//         unique case (booth_op)

//             // 0
//             3'b000:
//                 partial_product = '0;

//             // +M
//             3'b001:
//                 partial_product = multiplicand_ext;

//             // -M
//             3'b010:
//                 partial_product = -multiplicand_ext;

//             // +2M
//             3'b011:
//                 partial_product = multiplicand_ext <<< 1;

//             // -2M
//             3'b100:
//                 partial_product = -(multiplicand_ext <<< 1);

//             default:
//                 partial_product = '0;

//         endcase

//     end

// endmodule