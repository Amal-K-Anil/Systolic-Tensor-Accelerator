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
// Timing model used by the Excel trace:
//   * one SRAM address is presented per clock while read_en=1
//   * sram_data for an address is captured two cycles after that address
//   * for ARRAY_SIZE=8, normal valid cycles are 17,33,...,129
//   * skew state advances one clock after each normal-valid pulse
//   * final drain is 2*(ARRAY_SIZE-1) consecutive valid cycles
//   * drain_done is a one-clock pulse after the last drain-valid cycle
//
// drain_en is sampled on start and belongs to the tile being started.  This is
// important for back-to-back operation: drain_en may already describe tile 2
// while the final normal vector of tile 1 is still leaving the feeder.
// =============================================================================

`default_nettype none

module feeder #(
    parameter ARRAY_SIZE = 8
)(
    input  wire                    clk,
    input  wire                    rst_n,

    // From SRAM
    input  wire [7:0]              sram_data,

    // To SRAM
    output wire [6:0]              read_addr,
    output wire                    read_en,

    // Controller
    input  wire                    start,
    input  wire                    drain_en,
    input  wire                    clear,

    // Systolic-array inputs. Slice [i*8 +: 8] is lane i.
    output wire [ARRAY_SIZE*8-1:0] a_in,
    output wire [ARRAY_SIZE*8-1:0] b_in,
    output wire                    valid,

    // Controller status
    output wire                    drain_done
`ifdef FEEDER_DEBUG
    ,
    // ---------------------------------------------------------------------
    // Simulation-only observability. These ports do not exist unless the
    // testbench compiles with -DFEEDER_DEBUG.
    // ---------------------------------------------------------------------
    output wire [ARRAY_SIZE*8-1:0] dbg_a_stage,
    output wire [ARRAY_SIZE*8-1:0] dbg_b_stage,
    output wire [((ARRAY_SIZE*(ARRAY_SIZE-1))/2)*8-1:0] dbg_skew_a,
    output wire [((ARRAY_SIZE*(ARRAY_SIZE-1))/2)*8-1:0] dbg_skew_b,
    output wire [6:0]              dbg_read_counter,
    output wire                    dbg_reading,
    output wire                    dbg_normal_valid,
    output wire                    dbg_drain_active,
    output wire [4:0]              dbg_drain_counter,
    output wire                    dbg_current_tile_final
`endif
);

    localparam integer POS_WIDTH     = $clog2(ARRAY_SIZE);
    localparam integer TILE_BYTES    = 2 * ARRAY_SIZE * ARRAY_SIZE;
    localparam integer COUNT_WIDTH   = $clog2(TILE_BYTES);
    localparam integer B_BASE        = ARRAY_SIZE * ARRAY_SIZE;
    localparam integer SKEW_DEPTH    = (ARRAY_SIZE * (ARRAY_SIZE - 1)) / 2;
    localparam integer DRAIN_CYCLES  = 2 * (ARRAY_SIZE - 1);
    localparam integer DRAIN_WIDTH   = $clog2(DRAIN_CYCLES);

    // -------------------------------------------------------------------------
    // Read sequencer
    // -------------------------------------------------------------------------
    reg                     reading;
    reg [COUNT_WIDTH-1:0]   read_counter;
    reg                     current_tile_final;

    wire [POS_WIDTH-1:0] pos_now;
    wire                 phase_now;
    wire [POS_WIDTH-1:0] k_now;

    wire [6:0] pos_ext;
    wire [6:0] k_ext;
    wire [6:0] addr_a;
    wire [6:0] addr_b;

    assign pos_now   = read_counter[POS_WIDTH-1:0];
    assign phase_now = read_counter[POS_WIDTH];
    assign k_now     = read_counter >> (POS_WIDTH + 1);

    assign pos_ext = {{(7-POS_WIDTH){1'b0}}, pos_now};
    assign k_ext   = {{(7-POS_WIDTH){1'b0}}, k_now};

    // A is stored row-major at [0, N^2-1].
    // For inner step k, read A[row][k], row=0..N-1.
    assign addr_a = (pos_ext << POS_WIDTH) + k_ext;

    // B is stored row-major at [N^2, 2*N^2-1].
    // For inner step k, read B[k][col], col=0..N-1.
    assign addr_b = B_BASE + (k_ext << POS_WIDTH) + pos_ext;

    assign read_addr = phase_now ? addr_b : addr_a;
    assign read_en   = reading;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reading           <= 1'b0;
            read_counter      <= {COUNT_WIDTH{1'b0}};
            current_tile_final <= 1'b0;
        end else if (clear) begin
            reading           <= 1'b0;
            read_counter      <= {COUNT_WIDTH{1'b0}};
            current_tile_final <= 1'b0;
        end else begin
            if (start) begin
                reading            <= 1'b1;
                read_counter       <= {COUNT_WIDTH{1'b0}};
                current_tile_final <= drain_en;
            end else if (reading) begin
                if (read_counter == TILE_BYTES - 1) begin
                    reading      <= 1'b0;
                    read_counter <= read_counter;
                end else begin
                    read_counter <= read_counter + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Metadata shadow for the two-cycle SRAM path
    //
    // Address X is visible during cycle N.  At the N+1 edge its lane metadata
    // enters this register.  At the N+2 edge, the staging register captures
    // sram_data using this metadata.  A second metadata register would add an
    // unwanted third capture cycle.
    // -------------------------------------------------------------------------
    reg                   cap_en_d1;
    reg                   phase_d1;
    reg [POS_WIDTH-1:0]   pos_d1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cap_en_d1 <= 1'b0;
            phase_d1  <= 1'b0;
            pos_d1    <= {POS_WIDTH{1'b0}};
        end else if (clear) begin
            cap_en_d1 <= 1'b0;
            phase_d1  <= 1'b0;
            pos_d1    <= {POS_WIDTH{1'b0}};
        end else begin
            cap_en_d1 <= reading;
            if (reading) begin
                phase_d1 <= phase_now;
                pos_d1   <= pos_now;
            end
        end
    end

    // This registered pulse becomes high in the same displayed cycle in which
    // the last B staging word of an inner step has just been captured.
    reg normal_valid_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            normal_valid_r <= 1'b0;
        else if (clear)
            normal_valid_r <= 1'b0;
        else
            normal_valid_r <= cap_en_d1 && phase_d1 &&
                              (pos_d1 == ARRAY_SIZE - 1);
    end

    // -------------------------------------------------------------------------
    // Drain control
    // -------------------------------------------------------------------------
    reg                    drain_active;
    reg [DRAIN_WIDTH-1:0]  drain_counter;
    reg                    drain_done_r;

    // normal_valid_r is high for the completed tile during the cycle before
    // the first drain wavefront. current_tile_final was latched at that tile's
    // start, so a next tile's drain_en cannot accidentally drain this tile.
    wire drain_begin;
    assign drain_begin = normal_valid_r && !reading &&
                         current_tile_final && !drain_active;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drain_active  <= 1'b0;
            drain_counter <= {DRAIN_WIDTH{1'b0}};
            drain_done_r  <= 1'b0;
        end else if (clear) begin
            drain_active  <= 1'b0;
            drain_counter <= {DRAIN_WIDTH{1'b0}};
            drain_done_r  <= 1'b0;
        end else begin
            drain_done_r <= 1'b0;

            if (drain_begin) begin
                drain_active  <= 1'b1;
                drain_counter <= {DRAIN_WIDTH{1'b0}};
            end else if (drain_active) begin
                if (drain_counter == DRAIN_CYCLES - 1) begin
                    drain_active <= 1'b0;
                    drain_done_r <= 1'b1;
                end else begin
                    drain_counter <= drain_counter +
                                     {{(DRAIN_WIDTH-1){1'b0}}, 1'b1};
                end
            end
        end
    end

    assign drain_done = drain_done_r;
    assign valid      = normal_valid_r | drain_active;

    // -------------------------------------------------------------------------
    // Staging registers
    // -------------------------------------------------------------------------
    reg [7:0] A_stage [0:ARRAY_SIZE-1];
    reg [7:0] B_stage [0:ARRAY_SIZE-1];

    genvar st;
    generate
        for (st = 0; st < ARRAY_SIZE; st = st + 1) begin : g_staging
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    A_stage[st] <= 8'd0;
                    B_stage[st] <= 8'd0;
                end else if (clear) begin
                    A_stage[st] <= 8'd0;
                    B_stage[st] <= 8'd0;
                end else if (drain_begin) begin
                    // At this edge, the skew pipeline still sees the old, final
                    // staging vector (nonblocking assignment semantics).  After
                    // the edge, row/column 0 is zero for drain cycle 1.
                    A_stage[st] <= 8'd0;
                    B_stage[st] <= 8'd0;
                end else begin
                    if (cap_en_d1 && !phase_d1 && (pos_d1 == st))
                        A_stage[st] <= sram_data;
                    if (cap_en_d1 &&  phase_d1 && (pos_d1 == st))
                        B_stage[st] <= sram_data;
                end
            end
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Triangular skew buffer
    //
    // Row/column i has i register stages: total N*(N-1)/2 stages per side.
    // A completed normal vector is shifted one clock after its valid pulse.
    // This lets the systolic array consume the current wavefront while the
    // feeder prepares the next one. During drain, a zero vector shifts every
    // clock.
    // -------------------------------------------------------------------------
    reg [7:0] skew_A [0:SKEW_DEPTH-1];
    reg [7:0] skew_B [0:SKEW_DEPTH-1];

    wire skew_shift;
    assign skew_shift = normal_valid_r | drain_active;

    genvar row;
    genvar depth;
    generate
        for (row = 1; row < ARRAY_SIZE; row = row + 1) begin : g_skew_row
            localparam integer ROW_BASE = (row * (row - 1)) / 2;

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    skew_A[ROW_BASE] <= 8'd0;
                    skew_B[ROW_BASE] <= 8'd0;
                end else if (clear) begin
                    skew_A[ROW_BASE] <= 8'd0;
                    skew_B[ROW_BASE] <= 8'd0;
                end else if (skew_shift) begin
                    skew_A[ROW_BASE] <= A_stage[row];
                    skew_B[ROW_BASE] <= B_stage[row];
                end
            end

            for (depth = 1; depth < row; depth = depth + 1) begin : g_skew_depth
                always @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        skew_A[ROW_BASE + depth] <= 8'd0;
                        skew_B[ROW_BASE + depth] <= 8'd0;
                    end else if (clear) begin
                        skew_A[ROW_BASE + depth] <= 8'd0;
                        skew_B[ROW_BASE + depth] <= 8'd0;
                    end else if (skew_shift) begin
                        skew_A[ROW_BASE + depth] <= skew_A[ROW_BASE + depth - 1];
                        skew_B[ROW_BASE + depth] <= skew_B[ROW_BASE + depth - 1];
                    end
                end
            end
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Packed outputs
    // -------------------------------------------------------------------------
    assign a_in[0 +: 8] = A_stage[0];
    assign b_in[0 +: 8] = B_stage[0];

    genvar out_lane;
    generate
        for (out_lane = 1; out_lane < ARRAY_SIZE; out_lane = out_lane + 1) begin : g_outputs
            localparam integer OUT_INDEX =
                (out_lane * (out_lane - 1)) / 2 + out_lane - 1;
            assign a_in[out_lane*8 +: 8] = skew_A[OUT_INDEX];
            assign b_in[out_lane*8 +: 8] = skew_B[OUT_INDEX];
        end
    endgenerate


`ifdef FEEDER_DEBUG
    // -------------------------------------------------------------------------
    // Debug flattening. The packed order is deliberately simple:
    //   dbg_a_stage[i*8 +: 8] = A_stage[i]
    //   dbg_skew_a[j*8 +: 8]  = skew_A[j]
    // This lets cocotb compare every internal register every clock.
    // -------------------------------------------------------------------------
    genvar dbg_i;
    generate
        for (dbg_i = 0; dbg_i < ARRAY_SIZE; dbg_i = dbg_i + 1) begin : g_dbg_stage
            assign dbg_a_stage[dbg_i*8 +: 8] = A_stage[dbg_i];
            assign dbg_b_stage[dbg_i*8 +: 8] = B_stage[dbg_i];
        end
        for (dbg_i = 0; dbg_i < SKEW_DEPTH; dbg_i = dbg_i + 1) begin : g_dbg_skew
            assign dbg_skew_a[dbg_i*8 +: 8] = skew_A[dbg_i];
            assign dbg_skew_b[dbg_i*8 +: 8] = skew_B[dbg_i];
        end
    endgenerate

    assign dbg_read_counter       = {{(7-COUNT_WIDTH){1'b0}}, read_counter};
    assign dbg_reading            = reading;
    assign dbg_normal_valid       = normal_valid_r;
    assign dbg_drain_active       = drain_active;
    assign dbg_drain_counter      = {{(5-DRAIN_WIDTH){1'b0}}, drain_counter};
    assign dbg_current_tile_final = current_tile_final;
`endif

endmodule
`default_nettype wire
