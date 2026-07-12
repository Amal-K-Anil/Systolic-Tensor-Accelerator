// =============================================================================
// feeder.sv — Final, Spec-Compliant, Fully Parameterized
// SSCS Chipathon 2026 | Track A | Team Maxilerator | Owner: Irene
// Architecture Spec v1.0 Section 4.5
//
// Verified against: feeder_8x8_150_cycle_trace_updated.xlsx
//
// Yosys 0.64 compatibility:
//   - No SV cast expressions
//   - No integer loop variables in always blocks
//   - No unpacked port arrays (a_in/b_in flattened to packed vectors)
//   - No automatic functions
//   - rst_n is pure async reset; clear is synchronous
//   - All skew buffer FFs instantiated via generate — fully parameterized
//
// Parameterization: works for ARRAY_SIZE in {2, 4, 8}
//
// Key timing (spec Section 4.5 and cycle trace):
//   Cycle 16: valid=1 fires; ALL staging[0..N-1] already hold current k values
//   Cycle 17: skew buffer shifts — head reads staging (which holds k values)
//   Therefore: skew shift trigger = valid_d1 (one cycle after valid_normal)
//   This ensures staging is fully written before the skew head reads it.
//   valid fires at cycle 16; data at a_in/b_in reflects the shift from cycle 17
//   which loaded k-1 values → a_in[i] at valid k shows A[i][k-i] as required.
// =============================================================================

module feeder #(
    parameter ARRAY_SIZE = 8
)(
    input  wire                        clk,
    input  wire                        rst_n,

    // From memory
    input  wire [7:0]                  sram_data,

    // To memory
    output wire [6:0]                  read_addr,
    output wire                        read_en,

    // Control from controller (spec Section 4.5 port names)
    input  wire                        start,
    input  wire                        drain_en,
    input  wire                        clear,

    // To systolic_array — packed: slice [i*8 +: 8] = row i
    output wire [ARRAY_SIZE*8-1:0]     a_in,
    output wire [ARRAY_SIZE*8-1:0]     b_in,
    output wire                        valid,

    // To controller
    output wire                        drain_done
);

    // -----------------------------------------------------------------------
    // Localparams
    // -----------------------------------------------------------------------
    localparam TILE_BYTES   = 2 * ARRAY_SIZE * ARRAY_SIZE;
    localparam DRAIN_CYCLES = 2 * (ARRAY_SIZE - 1);
    localparam SKEW_DEPTH   = (ARRAY_SIZE * (ARRAY_SIZE - 1)) / 2;
    localparam POS_WIDTH    = $clog2(ARRAY_SIZE);
    localparam CNT_WIDTH    = $clog2(TILE_BYTES);
    localparam DRAIN_WIDTH  = $clog2(DRAIN_CYCLES + 1);

    // -----------------------------------------------------------------------
    // State registers
    // -----------------------------------------------------------------------
    reg                        reading;
    reg [CNT_WIDTH-1:0]        read_counter;

    reg                        cap_en_d1, cap_en_d2;
    reg                        phase_d1,  phase_d2;
    reg [POS_WIDTH-1:0]        pos_d1,    pos_d2;

    reg [7:0] A_stage [0:ARRAY_SIZE-1];
    reg [7:0] B_stage [0:ARRAY_SIZE-1];

    reg [7:0] skew_A [0:SKEW_DEPTH-1];
    reg [7:0] skew_B [0:SKEW_DEPTH-1];

    reg                        drain_active;
    reg [DRAIN_WIDTH-1:0]      drain_counter;

    reg                        valid_d1;   // skew shift trigger (1 cycle after valid_normal)

    // -----------------------------------------------------------------------
    // Section 1.1 — Read counter and address decode
    // -----------------------------------------------------------------------
    wire [POS_WIDTH-1:0]            pos_now   = read_counter[POS_WIDTH-1:0];
    wire                            phase_now = read_counter[POS_WIDTH];
    wire [CNT_WIDTH-POS_WIDTH-2:0]  k_now     = read_counter[CNT_WIDTH-1:POS_WIDTH+1];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_counter <= {CNT_WIDTH{1'b0}};
            reading      <= 1'b0;
        end else if (clear) begin
            read_counter <= {CNT_WIDTH{1'b0}};
            reading      <= 1'b0;
        end else if (start) begin
            read_counter <= {CNT_WIDTH{1'b0}};
            reading      <= 1'b1;
        end else if (reading) begin
            if (read_counter == TILE_BYTES - 1)
                reading <= 1'b0;
            read_counter <= read_counter + {{CNT_WIDTH-1{1'b0}}, 1'b1};
        end
    end

    assign read_en = reading;

    wire [6:0] addr_a = ({{7-POS_WIDTH{1'b0}}, pos_now} * ARRAY_SIZE[6:0])
                        + {{7-(CNT_WIDTH-POS_WIDTH-1){1'b0}}, k_now};
    wire [6:0] addr_b = 7'd64
                        + ({{7-(CNT_WIDTH-POS_WIDTH-1){1'b0}}, k_now} * ARRAY_SIZE[6:0])
                        + {{7-POS_WIDTH{1'b0}}, pos_now};

    assign read_addr = phase_now ? addr_b : addr_a;

    // -----------------------------------------------------------------------
    // Section 1.2 — 2-cycle shadow pipeline
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cap_en_d1 <= 1'b0; cap_en_d2 <= 1'b0;
            phase_d1  <= 1'b0; phase_d2  <= 1'b0;
            pos_d1    <= {POS_WIDTH{1'b0}};
            pos_d2    <= {POS_WIDTH{1'b0}};
        end else begin
            cap_en_d1 <= reading;
            phase_d1  <= phase_now;
            pos_d1    <= pos_now;
            cap_en_d2 <= cap_en_d1;
            phase_d2  <= phase_d1;
            pos_d2    <= pos_d1;
        end
    end

    // -----------------------------------------------------------------------
    // Section 2.1 — valid_normal, drain_start, valid_d1
    //
    // valid_normal: single-cycle pulse at end of each 16-cycle block.
    // valid_d1:     registered version — used as skew shift trigger so that
    //               skew reads staging AFTER it has been fully written.
    // drain_start:  fires on last normal valid of last tile.
    // -----------------------------------------------------------------------
    wire valid_normal = cap_en_d2 & phase_d2 & (pos_d2 == ARRAY_SIZE - 1);
    wire drain_start  = valid_normal & ~reading & drain_en;
    reg  drain_start_d1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)     drain_start_d1 <= 1'b0;
        else if (clear) drain_start_d1 <= 1'b0;
        else            drain_start_d1 <= drain_start;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)    valid_d1 <= 1'b0;
        else if (clear) valid_d1 <= 1'b0;
        else            valid_d1 <= valid_normal;
    end

    // -----------------------------------------------------------------------
    // Section 1.3 — A/B staging registers
    // -----------------------------------------------------------------------
    genvar si;
    generate
        for (si = 0; si < ARRAY_SIZE; si = si + 1) begin : staging_ff
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    A_stage[si] <= 8'd0;
                    B_stage[si] <= 8'd0;
                end else if (clear || drain_start_d1) begin
                    A_stage[si] <= 8'd0;
                    B_stage[si] <= 8'd0;
                end else if (cap_en_d2 && !phase_d2 && (pos_d2 == si)) begin
                    A_stage[si] <= sram_data;
                end else if (cap_en_d2 && phase_d2 && (pos_d2 == si)) begin
                    B_stage[si] <= sram_data;
                end
            end
        end
    endgenerate

    // -----------------------------------------------------------------------
    // Section 2.2 — Skew buffer
    //
    // Shifts on valid_d1 (one cycle after valid_normal) so staging is already
    // fully updated when the skew head reads it. This matches the spec:
    //   "Cycle 16: valid=1 (all staging data ready)"
    //   "Cycle 17: skew buffer shifts"
    //
    // During drain: shifts every cycle (drain_active), staging already zeroed
    // before drain starts (drain_start fires on same cycle as last valid_normal,
    // but staging update for that block happened earlier in the block).
    // -----------------------------------------------------------------------
    genvar grow, gcol;
    generate
        for (grow = 1; grow < ARRAY_SIZE; grow = grow + 1) begin : skew_row

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    skew_A[grow*(grow-1)/2] <= 8'd0;
                    skew_B[grow*(grow-1)/2] <= 8'd0;
                end else if (clear) begin
                    skew_A[grow*(grow-1)/2] <= 8'd0;
                    skew_B[grow*(grow-1)/2] <= 8'd0;
                end else if (valid_d1 || drain_active) begin
                    skew_A[grow*(grow-1)/2] <= A_stage[grow];
                    skew_B[grow*(grow-1)/2] <= B_stage[grow];
                end
            end

            for (gcol = 1; gcol < grow; gcol = gcol + 1) begin : skew_stage
                always @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        skew_A[grow*(grow-1)/2 + gcol] <= 8'd0;
                        skew_B[grow*(grow-1)/2 + gcol] <= 8'd0;
                    end else if (clear) begin
                        skew_A[grow*(grow-1)/2 + gcol] <= 8'd0;
                        skew_B[grow*(grow-1)/2 + gcol] <= 8'd0;
                    end else if (valid_d1 || drain_active) begin
                        skew_A[grow*(grow-1)/2 + gcol] <= skew_A[grow*(grow-1)/2 + gcol - 1];
                        skew_B[grow*(grow-1)/2 + gcol] <= skew_B[grow*(grow-1)/2 + gcol - 1];
                    end
                end
            end

        end
    endgenerate

    // -----------------------------------------------------------------------
    // Section 2.3 — a_in / b_in outputs
    // -----------------------------------------------------------------------
    wire [7:0] a_raw [0:ARRAY_SIZE-1];
    wire [7:0] b_raw [0:ARRAY_SIZE-1];

    assign a_raw[0] = A_stage[0];
    assign b_raw[0] = B_stage[0];

    genvar oi;
    generate
        for (oi = 1; oi < ARRAY_SIZE; oi = oi + 1) begin : skew_out
            assign a_raw[oi] = skew_A[oi*(oi-1)/2 + oi - 1];
            assign b_raw[oi] = skew_B[oi*(oi-1)/2 + oi - 1];
        end
        for (oi = 0; oi < ARRAY_SIZE; oi = oi + 1) begin : out_mux
            assign a_in[oi*8 +: 8] = a_raw[oi];
            assign b_in[oi*8 +: 8] = b_raw[oi];
        end
    endgenerate

    // -----------------------------------------------------------------------
    // Section 3 — Drain counter
    // -----------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drain_active  <= 1'b0;
            drain_counter <= {DRAIN_WIDTH{1'b0}};
        end else if (clear) begin
            drain_active  <= 1'b0;
            drain_counter <= {DRAIN_WIDTH{1'b0}};
        end else if (drain_start) begin
            drain_active  <= 1'b1;
            drain_counter <= {DRAIN_WIDTH{1'b0}};
        end else if (drain_active) begin
            if (drain_counter == DRAIN_CYCLES - 1)
                drain_active <= 1'b0;
            drain_counter <= drain_counter + {{DRAIN_WIDTH-1{1'b0}}, 1'b1};
        end
    end

    assign drain_done = drain_active & (drain_counter == DRAIN_CYCLES - 1);
    assign valid      = valid_normal  | drain_active;

endmodule