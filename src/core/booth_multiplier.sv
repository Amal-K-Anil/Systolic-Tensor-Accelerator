module booth_multiplier #(
    parameter DATA_WIDTH = 8
)(
    input  logic signed [DATA_WIDTH-1:0] multiplicand,
    input  logic signed [DATA_WIDTH-1:0] multiplier,
    output logic signed [(2*DATA_WIDTH)-1:0] product
);
    localparam NUM_GROUPS = DATA_WIDTH/2;
    localparam PW = 2*DATA_WIDTH;

    logic zero_s [0:NUM_GROUPS-1];
    logic sel2_s [0:NUM_GROUPS-1];
    logic neg_s  [0:NUM_GROUPS-1];

    logic signed [DATA_WIDTH+1:0] pp_row [0:NUM_GROUPS-1];
    logic corr [0:NUM_GROUPS-1];

    logic signed [(2*DATA_WIDTH)-1:0] shifted_pp [0:NUM_GROUPS-1];

    genvar i;
    generate
        for (i=0; i<NUM_GROUPS; i=i+1) begin : BOOTH_STAGE
            logic [2:0] booth_bits;
            if (i==0)
                assign booth_bits = {multiplier[1], multiplier[0], 1'b0};
            else
                assign booth_bits = {multiplier[(2*i)+1], multiplier[2*i], multiplier[(2*i)-1]};

            booth_encoder encoder (
                .booth_bits(booth_bits),
                .zero(zero_s[i]), .sel2(sel2_s[i]), .neg(neg_s[i])
            );

            partial_product_generator #(.DATA_WIDTH(DATA_WIDTH)) pp_gen (
                .zero(zero_s[i]), .sel2(sel2_s[i]), .neg(neg_s[i]),
                .multiplicand(multiplicand),
                .pp_row(pp_row[i]), .corr(corr[i])
            );

            // Sign-extending assignment into a wider signed reg is free (wires only)
            logic signed [PW-1:0] pp_ext;

assign pp_ext =
{{((2*DATA_WIDTH)-(DATA_WIDTH+2)){pp_row[i][DATA_WIDTH+1]}},
 pp_row[i]};
assign shifted_pp[i] = pp_ext <<< (2*i);
        end
    endgenerate

    integer k;
    logic signed [(2*DATA_WIDTH)-1:0] corr_word;

    always_comb begin
    corr_word = '0;

    for(k=0;k<NUM_GROUPS;k++)
        corr_word[2*k] = corr[k];

        product = corr_word;
        for (k=0; k<NUM_GROUPS; k=k+1)
            product = product + shifted_pp[k];
    end
endmodule







// module booth_multiplier #(
//     parameter DATA_WIDTH = 8
// )(
//     input  logic signed [DATA_WIDTH-1:0] multiplicand,
//     input  logic signed [DATA_WIDTH-1:0] multiplier,

//     output logic signed [(2*DATA_WIDTH)-1:0] product
// );
//     localparam NUM_GROUPS = DATA_WIDTH/2;
//     // Booth operation from each encoder
//     logic [2:0] booth_op [0:NUM_GROUPS-1];

//     // Partial products
//     logic signed [(2*DATA_WIDTH)-1:0] partial_product [0:NUM_GROUPS-1];

//     // Shifted partial products
//     logic signed [(2*DATA_WIDTH)-1:0] shifted_pp [0:NUM_GROUPS-1];

//     genvar i;

//     generate

//         for(i=0;i<NUM_GROUPS;i=i+1)
//         begin : BOOTH_STAGE

//             logic [2:0] booth_bits;
//             if(i==0)
//             begin

//                 assign booth_bits = {
//                                     multiplier[1],
//                                     multiplier[0],
//                                     1'b0
//                                     };

//             end
//             else
//             begin

//                 assign booth_bits = {
//                                     multiplier[(2*i)+1],
//                                     multiplier[(2*i)],
//                                     multiplier[(2*i)-1]
//                                     };

//             end

//             // -----------------------------
//             // Booth Encoder
//             // -----------------------------

//             booth_encoder encoder(

//                 .booth_bits(booth_bits),
//                 .booth_op(booth_op[i])

//             );

//             // -----------------------------
//             // Partial Product Generator
//             // -----------------------------

//             partial_product_generator #(

//                 .DATA_WIDTH(DATA_WIDTH)

//             ) pp_gen (

//                 .booth_op(booth_op[i]),
//                 .multiplicand(multiplicand),
//                 .partial_product(partial_product[i])

//             );

//             // -----------------------------
//             // Shift partial product
//             // -----------------------------

//             assign shifted_pp[i] = partial_product[i] <<< (2*i);

//         end
//     endgenerate
//     integer k;

//     always_comb
//     begin

//         product = '0;

//         for(k=0;k<NUM_GROUPS;k=k+1)
//             product = product + shifted_pp[k];

//     end

// endmodule