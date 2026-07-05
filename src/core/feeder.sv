// =============================================================================
// feeder.sv — Optimized, Spec-Compliant, Yosys/LibreLane/iverilog compatible
// SSCS Chipathon 2026 | Track A | Team Maxilerator | Owner: Irene
// Architecture Spec v1.0 Section 4.5
//
// Yosys compatibility requirements addressed:
//   - No unpacked arrays in port declarations (flattened to packed [N*8-1:0])
//   - No SV cast syntax (7'(expr), 4'(expr))
//   - No ++ / -- loop increments
//   - No function calls as array indices inside always blocks
//   - No 'integer' loop variables shared with always blocks (causes PROC_DFF error)
//   - rst_n kept as pure async reset; clear is SYNCHRONOUS (Yosys 0.33+ compatible)
//   - All reset/clear loops fully unrolled (no for-loop variables in always blocks)
//
// Changes vs original feeder.sv:
//   1. Port names corrected to spec: start→swap_pulse, drain_en→last_pass
//   2. BUG FIX: valid_normal was phase_d1&&pos_d2 (wrong). Fixed to phase_d2&&pos_d2.
//   3. k_d1/k_d2 eliminated (−6 FFs). drain_start now uses ~reading as discriminant.
//   4. cap_en_d2 eliminated (−1 FF, was never read).
//   5. a_in/b_in: packed [ARRAY_SIZE*8-1:0] ports; slice internally.
//   6. All loops in always blocks fully unrolled — no integer variables at all.
//   7. clear is synchronous (rst_n async only) — required for Yosys PROC_DFF.
// =============================================================================

module feeder #(
    parameter ARRAY_SIZE = 8
)(
    input  wire                    clk,
    input  wire                    rst_n,

    // From memory
    input  wire [7:0]              sram_data,

    // To memory
    output wire [6:0]              read_addr,
    output wire                    read_en,

    // Control (spec Section 4.5 port names)
    input  wire                    swap_pulse,
    input  wire                    last_pass,
    input  wire                    clear,

    // To systolic_array — packed: a_in[i*8 +: 8] = row i
    output wire [ARRAY_SIZE*8-1:0] a_in,
    output wire [ARRAY_SIZE*8-1:0] b_in,
    output wire                    valid,

    // To controller
    output wire                    drain_done
);

    // -----------------------------------------------------------------------
    // Localparams
    // -----------------------------------------------------------------------
    localparam TILE_BYTES   = 128;  // 2*8*8
    localparam DRAIN_CYCLES = 14;   // 2*(8-1)
    localparam SKEW_DEPTH   = 28;   // 8*7/2
    localparam POS_WIDTH    = 3;
    localparam CNT_WIDTH    = 7;
    localparam [CNT_WIDTH-1:0] TILE_LAST  = 7'd127;
    localparam [3:0]           DRAIN_LAST = 4'd13;

    // -----------------------------------------------------------------------
    // State registers
    // -----------------------------------------------------------------------
    reg                    reading;
    reg [CNT_WIDTH-1:0]    read_counter;

    reg                    cap_en_d1;
    reg                    phase_d1, phase_d2;
    reg [POS_WIDTH-1:0]    pos_d1, pos_d2;

    reg [7:0] A_stage [0:7];
    reg [7:0] B_stage [0:7];

    reg [7:0] skew_A [0:27];
    reg [7:0] skew_B [0:27];

    reg       drain_active;
    reg [3:0] drain_counter;

    // -----------------------------------------------------------------------
    // Section 1.1 — Read counter + address decode
    // -----------------------------------------------------------------------
    wire [2:0] pos_now   = read_counter[2:0];
    wire       phase_now = read_counter[3];
    wire [3:0] k_now     = read_counter[6:4];

    // Synchronous clear; rst_n is the only async event
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_counter <= 7'd0;
            reading      <= 1'b0;
        end else if (clear) begin
            read_counter <= 7'd0;
            reading      <= 1'b0;
        end else if (swap_pulse) begin
            read_counter <= 7'd0;
            reading      <= 1'b1;
        end else if (reading) begin
            if (read_counter == TILE_LAST)
                reading <= 1'b0;
            read_counter <= read_counter + 7'd1;
        end
    end

    assign read_en = reading;

    // Address formulas (spec Section 5.2)
    wire [6:0] addr_a = {pos_now, k_now[2:0]};  // pos_now*8 + k_now (since ARRAY_SIZE=8)
    wire [6:0] addr_b = 7'd64 + {k_now[2:0], pos_now};  // 64 + k_now*8 + pos_now

    assign read_addr = phase_now ? addr_b : addr_a;

    // -----------------------------------------------------------------------
    // Section 1.2 — 2-cycle shadow pipeline (rst_n async, no clear)
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cap_en_d1 <= 1'b0;
            phase_d1  <= 1'b0; pos_d1 <= 3'd0;
            phase_d2  <= 1'b0; pos_d2 <= 3'd0;
        end else begin
            cap_en_d1 <= reading;
            phase_d1  <= phase_now; pos_d1 <= pos_now;
            phase_d2  <= phase_d1;  pos_d2 <= pos_d1;
        end
    end

    // -----------------------------------------------------------------------
    // Section 2.1 — valid_normal and drain_start
    // -----------------------------------------------------------------------
    wire valid_normal = phase_d2 & (pos_d2 == 3'd7);
    wire drain_start  = valid_normal & ~reading & last_pass;

    // -----------------------------------------------------------------------
    // Section 1.3 — A/B staging (fully unrolled, no loop variables)
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            A_stage[0]<=8'd0; A_stage[1]<=8'd0; A_stage[2]<=8'd0; A_stage[3]<=8'd0;
            A_stage[4]<=8'd0; A_stage[5]<=8'd0; A_stage[6]<=8'd0; A_stage[7]<=8'd0;
            B_stage[0]<=8'd0; B_stage[1]<=8'd0; B_stage[2]<=8'd0; B_stage[3]<=8'd0;
            B_stage[4]<=8'd0; B_stage[5]<=8'd0; B_stage[6]<=8'd0; B_stage[7]<=8'd0;
        end else if (clear || drain_start) begin
            A_stage[0]<=8'd0; A_stage[1]<=8'd0; A_stage[2]<=8'd0; A_stage[3]<=8'd0;
            A_stage[4]<=8'd0; A_stage[5]<=8'd0; A_stage[6]<=8'd0; A_stage[7]<=8'd0;
            B_stage[0]<=8'd0; B_stage[1]<=8'd0; B_stage[2]<=8'd0; B_stage[3]<=8'd0;
            B_stage[4]<=8'd0; B_stage[5]<=8'd0; B_stage[6]<=8'd0; B_stage[7]<=8'd0;
        end else if (cap_en_d1) begin
            if (!phase_d2) A_stage[pos_d2] <= sram_data;
            else           B_stage[pos_d2] <= sram_data;
        end
    end

    // -----------------------------------------------------------------------
    // Section 2.2 — Skew buffer (fully unrolled, no loop variables)
    // Chain offsets: off[i]=i*(i-1)/2 → 0,0,1,3,6,10,15,21 for rows 0-7
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            skew_A[ 0]<=8'd0; skew_A[ 1]<=8'd0; skew_A[ 2]<=8'd0; skew_A[ 3]<=8'd0;
            skew_A[ 4]<=8'd0; skew_A[ 5]<=8'd0; skew_A[ 6]<=8'd0; skew_A[ 7]<=8'd0;
            skew_A[ 8]<=8'd0; skew_A[ 9]<=8'd0; skew_A[10]<=8'd0; skew_A[11]<=8'd0;
            skew_A[12]<=8'd0; skew_A[13]<=8'd0; skew_A[14]<=8'd0; skew_A[15]<=8'd0;
            skew_A[16]<=8'd0; skew_A[17]<=8'd0; skew_A[18]<=8'd0; skew_A[19]<=8'd0;
            skew_A[20]<=8'd0; skew_A[21]<=8'd0; skew_A[22]<=8'd0; skew_A[23]<=8'd0;
            skew_A[24]<=8'd0; skew_A[25]<=8'd0; skew_A[26]<=8'd0; skew_A[27]<=8'd0;
            skew_B[ 0]<=8'd0; skew_B[ 1]<=8'd0; skew_B[ 2]<=8'd0; skew_B[ 3]<=8'd0;
            skew_B[ 4]<=8'd0; skew_B[ 5]<=8'd0; skew_B[ 6]<=8'd0; skew_B[ 7]<=8'd0;
            skew_B[ 8]<=8'd0; skew_B[ 9]<=8'd0; skew_B[10]<=8'd0; skew_B[11]<=8'd0;
            skew_B[12]<=8'd0; skew_B[13]<=8'd0; skew_B[14]<=8'd0; skew_B[15]<=8'd0;
            skew_B[16]<=8'd0; skew_B[17]<=8'd0; skew_B[18]<=8'd0; skew_B[19]<=8'd0;
            skew_B[20]<=8'd0; skew_B[21]<=8'd0; skew_B[22]<=8'd0; skew_B[23]<=8'd0;
            skew_B[24]<=8'd0; skew_B[25]<=8'd0; skew_B[26]<=8'd0; skew_B[27]<=8'd0;
        end else if (clear) begin
            skew_A[ 0]<=8'd0; skew_A[ 1]<=8'd0; skew_A[ 2]<=8'd0; skew_A[ 3]<=8'd0;
            skew_A[ 4]<=8'd0; skew_A[ 5]<=8'd0; skew_A[ 6]<=8'd0; skew_A[ 7]<=8'd0;
            skew_A[ 8]<=8'd0; skew_A[ 9]<=8'd0; skew_A[10]<=8'd0; skew_A[11]<=8'd0;
            skew_A[12]<=8'd0; skew_A[13]<=8'd0; skew_A[14]<=8'd0; skew_A[15]<=8'd0;
            skew_A[16]<=8'd0; skew_A[17]<=8'd0; skew_A[18]<=8'd0; skew_A[19]<=8'd0;
            skew_A[20]<=8'd0; skew_A[21]<=8'd0; skew_A[22]<=8'd0; skew_A[23]<=8'd0;
            skew_A[24]<=8'd0; skew_A[25]<=8'd0; skew_A[26]<=8'd0; skew_A[27]<=8'd0;
            skew_B[ 0]<=8'd0; skew_B[ 1]<=8'd0; skew_B[ 2]<=8'd0; skew_B[ 3]<=8'd0;
            skew_B[ 4]<=8'd0; skew_B[ 5]<=8'd0; skew_B[ 6]<=8'd0; skew_B[ 7]<=8'd0;
            skew_B[ 8]<=8'd0; skew_B[ 9]<=8'd0; skew_B[10]<=8'd0; skew_B[11]<=8'd0;
            skew_B[12]<=8'd0; skew_B[13]<=8'd0; skew_B[14]<=8'd0; skew_B[15]<=8'd0;
            skew_B[16]<=8'd0; skew_B[17]<=8'd0; skew_B[18]<=8'd0; skew_B[19]<=8'd0;
            skew_B[20]<=8'd0; skew_B[21]<=8'd0; skew_B[22]<=8'd0; skew_B[23]<=8'd0;
            skew_B[24]<=8'd0; skew_B[25]<=8'd0; skew_B[26]<=8'd0; skew_B[27]<=8'd0;
        end else if (valid_normal || drain_active) begin
            // Row 1 (off=0): 1 stage
            skew_A[ 0] <= A_stage[1];   skew_B[ 0] <= B_stage[1];
            // Row 2 (off=1): 2 stages
            skew_A[ 2] <= skew_A[ 1];   skew_B[ 2] <= skew_B[ 1];
            skew_A[ 1] <= A_stage[2];   skew_B[ 1] <= B_stage[2];
            // Row 3 (off=3): 3 stages
            skew_A[ 5] <= skew_A[ 4];   skew_B[ 5] <= skew_B[ 4];
            skew_A[ 4] <= skew_A[ 3];   skew_B[ 4] <= skew_B[ 3];
            skew_A[ 3] <= A_stage[3];   skew_B[ 3] <= B_stage[3];
            // Row 4 (off=6): 4 stages
            skew_A[ 9] <= skew_A[ 8];   skew_B[ 9] <= skew_B[ 8];
            skew_A[ 8] <= skew_A[ 7];   skew_B[ 8] <= skew_B[ 7];
            skew_A[ 7] <= skew_A[ 6];   skew_B[ 7] <= skew_B[ 6];
            skew_A[ 6] <= A_stage[4];   skew_B[ 6] <= B_stage[4];
            // Row 5 (off=10): 5 stages
            skew_A[14] <= skew_A[13];   skew_B[14] <= skew_B[13];
            skew_A[13] <= skew_A[12];   skew_B[13] <= skew_B[12];
            skew_A[12] <= skew_A[11];   skew_B[12] <= skew_B[11];
            skew_A[11] <= skew_A[10];   skew_B[11] <= skew_B[10];
            skew_A[10] <= A_stage[5];   skew_B[10] <= B_stage[5];
            // Row 6 (off=15): 6 stages
            skew_A[20] <= skew_A[19];   skew_B[20] <= skew_B[19];
            skew_A[19] <= skew_A[18];   skew_B[19] <= skew_B[18];
            skew_A[18] <= skew_A[17];   skew_B[18] <= skew_B[17];
            skew_A[17] <= skew_A[16];   skew_B[17] <= skew_B[16];
            skew_A[16] <= skew_A[15];   skew_B[16] <= skew_B[15];
            skew_A[15] <= A_stage[6];   skew_B[15] <= B_stage[6];
            // Row 7 (off=21): 7 stages
            skew_A[27] <= skew_A[26];   skew_B[27] <= skew_B[26];
            skew_A[26] <= skew_A[25];   skew_B[26] <= skew_B[25];
            skew_A[25] <= skew_A[24];   skew_B[25] <= skew_B[24];
            skew_A[24] <= skew_A[23];   skew_B[24] <= skew_B[23];
            skew_A[23] <= skew_A[22];   skew_B[23] <= skew_B[22];
            skew_A[22] <= skew_A[21];   skew_B[22] <= skew_B[21];
            skew_A[21] <= A_stage[7];   skew_B[21] <= B_stage[7];
        end
    end

    // -----------------------------------------------------------------------
    // Section 2.3 — a_in / b_in outputs (packed bit-slice)
    // -----------------------------------------------------------------------
    assign a_in[ 0*8 +: 8] = A_stage[0];
    assign a_in[ 1*8 +: 8] = skew_A[ 0];   // row1 last=off(1)+0=0
    assign a_in[ 2*8 +: 8] = skew_A[ 2];   // row2 last=off(2)+1=2
    assign a_in[ 3*8 +: 8] = skew_A[ 5];   // row3 last=off(3)+2=5
    assign a_in[ 4*8 +: 8] = skew_A[ 9];   // row4 last=off(4)+3=9
    assign a_in[ 5*8 +: 8] = skew_A[14];   // row5 last=off(5)+4=14
    assign a_in[ 6*8 +: 8] = skew_A[20];   // row6 last=off(6)+5=20
    assign a_in[ 7*8 +: 8] = skew_A[27];   // row7 last=off(7)+6=27

    assign b_in[ 0*8 +: 8] = B_stage[0];
    assign b_in[ 1*8 +: 8] = skew_B[ 0];
    assign b_in[ 2*8 +: 8] = skew_B[ 2];
    assign b_in[ 3*8 +: 8] = skew_B[ 5];
    assign b_in[ 4*8 +: 8] = skew_B[ 9];
    assign b_in[ 5*8 +: 8] = skew_B[14];
    assign b_in[ 6*8 +: 8] = skew_B[20];
    assign b_in[ 7*8 +: 8] = skew_B[27];

    // -----------------------------------------------------------------------
    // Section 3 — Drain counter
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drain_active  <= 1'b0;
            drain_counter <= 4'd0;
        end else if (clear) begin
            drain_active  <= 1'b0;
            drain_counter <= 4'd0;
        end else if (drain_start) begin
            drain_active  <= 1'b1;
            drain_counter <= 4'd0;
        end else if (drain_active) begin
            if (drain_counter == DRAIN_LAST)
                drain_active <= 1'b0;
            drain_counter <= drain_counter + 4'd1;
        end
    end

    assign drain_done = drain_active & (drain_counter == DRAIN_LAST);
    assign valid      = valid_normal  | drain_active;

endmodule
