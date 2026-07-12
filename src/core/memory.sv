// =============================================================================
// Company/Role: Expert Digital IC Design Engineer (ASIC RTL)
// Module Name:  memory
// Description:  Parameterless, hard-macro-based Ping-Pong SRAM buffer designed 
//               for zero-overhead tile swapping in an output-stationary 
//               systolic array AI accelerator.
// =============================================================================

`timescale 1ns/1ps

module memory (
    input  logic       clk,         
    input  logic       rst_n,       
    input  logic [7:0] write_data,  
    input  logic [6:0] write_addr,  
    input  logic       write_en,    // 
    input  logic [6:0] read_addr,   
    input  logic       read_en,     
    output logic [7:0] read_data,   
    input  logic       swap         
); // Power ports completely removed from logical RTL

    // -------------------------------------------------------------------------
    // Local Parameters (Fixed Macro Dimensions)
    // -------------------------------------------------------------------------
    localparam int DATA_WIDTH = 8;
    localparam int SRAM_DEPTH = 128;
    localparam int ADDR_WIDTH = 7;

    // -------------------------------------------------------------------------
    // Internal Signals & State Tracking
    // -------------------------------------------------------------------------
    // Ping-pong tracking register: 0 -> SRAM_0 Write / SRAM_1 Read
    //                              1 -> SRAM_0 Read / SRAM_1 Write
    logic ping_pong_state;

    // Interconnect wires for SRAM_0 Hard Macro
    logic [ADDR_WIDTH-1:0] sram0_A;
    logic [DATA_WIDTH-1:0] sram0_D;
    logic                  sram0_CEN;
    logic                  sram0_GWEN;
    logic [DATA_WIDTH-1:0] sram0_Q;

    // Interconnect wires for SRAM_1 Hard Macro
    logic [ADDR_WIDTH-1:0] sram1_A;
    logic [DATA_WIDTH-1:0] sram1_D;
    logic                  sram1_CEN;
    logic                  sram1_GWEN;
    logic [DATA_WIDTH-1:0] sram1_Q;

    // -------------------------------------------------------------------------
    // Synchronous State Machine / Toggle Logic
    // -------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin : proc_ping_pong_state
        if (!rst_n) begin
            ping_pong_state <= 1'b0;
        end else if (swap) begin
            ping_pong_state <= ~ping_pong_state;
        end
    end

    // -------------------------------------------------------------------------
    // Combinational Muxing & Routing Logic
    // -------------------------------------------------------------------------
    always_comb begin : proc_mux_routing
        // Default assignments to prevent latch synthesis (CEN=1: Disabled, GWEN=1: Read mode)
        sram0_A    = '0;
        sram0_D    = '0;
        sram0_CEN  = 1'b1;
        sram0_GWEN = 1'b1;

        sram1_A    = '0;
        sram1_D    = '0;
        sram1_CEN  = 1'b1;
        sram1_GWEN = 1'b1;
        
        read_data  = '0;

        if (ping_pong_state == 1'b0) begin
            // -----------------------------------------------------------------
            // State 0: SRAM_0 is WRITE (Controller), SRAM_1 is READ (Feeder)
            // -----------------------------------------------------------------
            // Route to SRAM_0 (Write Port)
            sram0_A    = write_addr;
            sram0_D    = write_data;
            sram0_CEN  = ~write_en;
            sram0_GWEN = 1'b0;

            // Route to SRAM_1 (Read Port)
            sram1_A    = read_addr;
            sram1_CEN  = ~read_en;
            sram1_GWEN = 1'b1;
            read_data  = sram1_Q;
        end else begin
            // -----------------------------------------------------------------
            // State 1: SRAM_0 is READ (Feeder), SRAM_1 is WRITE (Controller)
            // -----------------------------------------------------------------
            // Route to SRAM_0 (Read Port)
            sram0_A    = read_addr;
            sram0_CEN  = ~read_en;
            sram0_GWEN = 1'b1;
            read_data  = sram0_Q;

            // Route to SRAM_1 (Write Port)
            sram1_A    = write_addr;
            sram1_D    = write_data;
            sram1_CEN  = ~write_en;
            sram1_GWEN = 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // Hard Macro Instantiations
    // -------------------------------------------------------------------------
    
    // Instance 0: SRAM_0
    gf180mcu_fd_ip_sram__sram128x8m8wm1 SRAM_0 (
        .CLK  (clk),
        .A    (sram0_A),
        .D    (sram0_D),
        .CEN  (sram0_CEN),
        .GWEN (sram0_GWEN),
        .WEN  (8'b0000_0000),
        .Q    (sram0_Q)
        // No VDD/VSS lines connected here
    );

    // Instance 1: SRAM_1
    gf180mcu_fd_ip_sram__sram128x8m8wm1 SRAM_1 (
        .CLK  (clk),
        .A    (sram1_A),
        .D    (sram1_D),
        .CEN  (sram1_CEN),
        .GWEN (sram1_GWEN),
        .WEN  (8'b0000_0000),
        .Q    (sram1_Q)
        // No VDD/VSS lines connected here
    );

endmodule
