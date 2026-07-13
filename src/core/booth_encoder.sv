module booth_encoder (
    input  logic [2:0] booth_bits,
    output logic zero,
    output logic sel2,   // select 2x magnitude
    output logic neg     // subtract (invert + correction)
);
    always_comb begin
        unique case (booth_bits)
            3'b000, 3'b111: begin zero=1'b1; sel2=1'b0; neg=1'b0; end // 0
            3'b001, 3'b010: begin zero=1'b0; sel2=1'b0; neg=1'b0; end // +M
            3'b011:         begin zero=1'b0; sel2=1'b1; neg=1'b0; end // +2M
            3'b100:         begin zero=1'b0; sel2=1'b1; neg=1'b1; end // -2M
            3'b101, 3'b110: begin zero=1'b0; sel2=1'b0; neg=1'b1; end // -M
            default:        begin zero=1'b1; sel2=1'b0; neg=1'b0; end
        endcase
    end
endmodule
 // removed the encoding decoding logic to direct generation of control signals

// module booth_encoder (

//     input  logic [2:0] booth_bits,

//     output logic [2:0] booth_op

// );

//     // booth_op encoding
//     // 000 :  0
//     // 001 : +M
//     // 010 : -M
//     // 011 : +2M
//     // 100 : -2M

//     always_comb begin

//         unique case (booth_bits)

//             3'b000,
//             3'b111 : booth_op = 3'b000;   // 0

//             3'b001,
//             3'b010 : booth_op = 3'b001;   // +M

//             3'b101,
//             3'b110 : booth_op = 3'b010;   // -M

//             3'b011 : booth_op = 3'b011;   // +2M

//             3'b100 : booth_op = 3'b100;   // -2M

//             default : booth_op = 3'b000;

//         endcase

//     end

// endmodule