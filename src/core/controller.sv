// =======================================================================================
// controller.sv
//
// The controller is the central FSM of the accelerator_core. It sequences
// all operations across the three phases of computation: tile loading,
// ping-pong compute, and result output. It is pure control logic and never
// touches the data path directly.
//
// Operation overview:
//   The host transfers tile data (A and B sub-matrices) one byte at a time
//   via valid_in. The controller tracks each byte using write_addr and asserts
//   write_en to store it into the inactive SRAM. When the host signals the end
//   of a tile via tile_done, the controller cross-checks it against write_addr
//   to guard against spurious pulses, then asserts swap to simultaneously
//   switch the active and inactive SRAMs and restart the feeder on the newly
//   loaded tile. For non-last tiles, ready_in is granted in the same cycle as
//   swap, permitting the host to begin loading the next tile immediately.
//
//   For the last tile (last_pass=1), no ready_in is granted after swap. Instead,
//   drain_en is latched to signal the feeder to enter its 14-cycle drain phase
//   after completing 128 reads. When feeder asserts drain_done, the controller
//   transitions to the OUTPUT state and enables the output_processor to serialize
//   all ARRAY_SIZE² results. Once output_done is received, a single-cycle clear
//   pulse resets all MAC accumulators and the feeder staging/skew registers,
//   and ready_in is reasserted to permit a new computation.
//
// FSM states:
//   IDLE       — waiting for host to send first byte. ready_in held HIGH.
//   PROCESSING — host loads inactive SRAM while feeder reads active SRAM
//                (ping-pong). Handles both the initial tile load (feeder idle)
//                and all subsequent tiles (feeder and host operating in parallel).
//                Transitions to OUTPUT only on drain_done from the last tile.
//   OUTPUT     — output_processor serializes results. Both SRAMs idle.
//                No new tile data accepted (ready_in=0).
//
// =======================================================================================


`default_nettype none

module controller #(
    parameter ARRAY_SIZE = 8
)(
    input  logic        clk,
    input  logic        rst_n,

    // Host Interface
    input  logic        valid_in,    // host driving valid data byte
    input  logic        tile_done,   // host signals end of tile transfer
    input  logic        last_pass,   // host signals this is the final tile
    output logic        ready_in,    // permission pulse to host: send next tile

    // Memory
    output logic [6:0]  write_addr,  // byte address for incoming tile data
    output logic        write_en,    // write strobe: valid_in gated by state

    // Memory + Feeder
    output logic        swap,        // swap active/inactive SRAMs + restart feeder

    // Feeder
    output logic        drain_en,    // tells feeder to drain after last tile read
    input  logic        drain_done,  // feeder completed 14-cycle drain phase

    // Feeder + Systolic Array
    output logic        clear,       // clears feeder staging/skew + all MAC accumulators

    // Output Processor
    output logic        output_en,   // enables output_processor to serialize results
    input  logic        output_done  // output_processor finished sending all results
);

    // ===================================================================================
    //  Constants
    // ===================================================================================
    localparam BYTES_PER_PASS = 2 * ARRAY_SIZE * ARRAY_SIZE;  // 128 for 8x8

    // ===================================================================================
    //  FSM State Encoding
    // ===================================================================================
    typedef enum logic [1:0] {
        IDLE       = 2'b00,  // waiting for first byte from host
        PROCESSING = 2'b01,  // host loading + feeder computing (ping-pong)
        OUTPUT     = 2'b10   // serializing results to host
    } state_t;

    // ===================================================================================
    //  Internal Signals
    // ===================================================================================
    state_t state, next_state;
    logic   last_byte;


    // ===================================================================================
    //  Combinational Logic
    // ===================================================================================
    assign last_byte = tile_done && (write_addr == 7'(BYTES_PER_PASS - 1));  // validates tile_done against write_addr to guard against spurious pulses
    assign write_en  = valid_in && (state == IDLE || state == PROCESSING);   // write_en gated by state to prevent spurious SRAM writes
    assign output_en = (state == OUTPUT);                                    // combinational: avoids 1-cycle gap after drain_done


    // ===================================================================================
    //  FSM State Register
    // ===================================================================================
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= IDLE;
        else        state <= next_state;
    end


    // ===================================================================================
    //  FSM Next State Logic
    // ===================================================================================
    always_comb begin
        next_state = state;
        case (state)
            IDLE:       if (valid_in)   next_state = PROCESSING;
            PROCESSING: if (drain_done) next_state = OUTPUT;
            OUTPUT:     if (output_done) next_state = IDLE;
            default:                    next_state = IDLE;
        endcase
    end


    // ===================================================================================
    //  FSM Output Logic
    // ===================================================================================
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ready_in   <= 1'b1;
            swap       <= 1'b0;
            clear      <= 1'b0;
            drain_en   <= 1'b0;
            write_addr <= '0;
        end else begin

            // single-cycle pulse defaults
            swap  <= 1'b0;
            clear <= 1'b0;

            case (state)

                IDLE: begin
                    if (valid_in) begin
                        ready_in   <= 1'b0;
                        write_addr <= 7'd1;
                    end
                end

                PROCESSING: begin
                    if (valid_in) begin
                        write_addr <= write_addr + 1'b1;
                        if (ready_in)
                            ready_in <= 1'b0;
                    end
                    if (last_byte) begin
                        swap       <= 1'b1;
                        write_addr <= '0;
                        if (last_pass)
                            drain_en <= 1'b1;
                        else
                            ready_in <= 1'b1;
                    end
                    if (drain_done)
                        drain_en <= 1'b0;
                end

                OUTPUT: begin
                    if (output_done) begin
                        clear    <= 1'b1;
                        ready_in <= 1'b1;
                    end
                end

                default: ready_in <= 1'b1;

            endcase
        end
    end

endmodule

`default_nettype wire