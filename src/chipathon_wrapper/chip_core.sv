// =======================================================================================
// chip_core.sv
//
// chip_core is the Slot A padring pin-mapping layer. It knows only about raw,
// index-based pad arrays (bidir_in/out/oe/..., input_in/pu/pd) as exposed by
// chip_top -- no protocol logic lives here, only wire connections from specific
// array indices to host_interface's named ports, plus per-pin electrical
// configuration (input threshold, slew rate, pull resistors).
//
// Pin map (17 of 22 available signal pins used; the remaining 5 are simply not
// instantiated in the SLOT_A definition, rather than left as unused pad indices):
//   input_PAD[0]  a_valid_i        input_PAD[3]  b_last_i
//   input_PAD[1]  a_last_i         input_PAD[4]  out_ready_i
//   input_PAD[2]  b_valid_i
//
//   bidir_PAD[0:7]  data[7:0]      bidir_PAD[10] out_valid_o
//   bidir_PAD[8]    a_ready_o      bidir_PAD[11] out_last_o
//   bidir_PAD[9]    b_ready_o
// =======================================================================================

`default_nettype none

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,
    input  wire rst_n,

    input  wire [NUM_INPUT_PADS-1:0] input_in,
    output wire [NUM_INPUT_PADS-1:0] input_pu,
    output wire [NUM_INPUT_PADS-1:0] input_pd,

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,

    inout  wire [NUM_ANALOG_PADS-1:0] analog    // unused, purely digital design
);

    // ===================================================================================
    //  Input-Only Pads -> host_interface (host -> chip signals)
    // ===================================================================================
    wire a_valid_i   = input_in[0];
    wire a_last_i    = input_in[1];
    wire b_valid_i   = input_in[2];
    wire b_last_i    = input_in[3];
    wire out_ready_i = input_in[4];

    assign input_pu = '0;
    assign input_pd = '0;


    // ===================================================================================
    //  Bidir Pads -> host_interface (shared data bus + chip -> host signals)
    // ===================================================================================
    wire [7:0] data_i = bidir_in[7:0];
    wire [7:0] data_o;
    wire       data_oe;

    wire a_ready_o, b_ready_o, out_valid_o, out_last_o;

    assign bidir_out[7:0]  = data_o;
    assign bidir_out[8]    = a_ready_o;
    assign bidir_out[9]    = b_ready_o;
    assign bidir_out[10]   = out_valid_o;
    assign bidir_out[11]   = out_last_o;

    assign bidir_oe[7:0]   = {8{data_oe}};                    // data bus: direction-switched
    assign bidir_oe[11:8]  = 4'b1111;                         // ready/valid/last outs: fixed

    assign bidir_cs = '0;                                     // CMOS input threshold
    assign bidir_sl = '0;                                     // fast slew
    assign bidir_ie = ~bidir_oe;                              // listen only while not driving
    assign bidir_pu = '0;
    assign bidir_pd = '0;

    // Keep synthesis from optimising away the unused analog pad.
    logic _unused;
    assign _unused = &{1'b0, analog};


    // ===================================================================================
    //  Host Interface
    // ===================================================================================
    host_interface u_host_interface (
        .clk         (clk),
        .rst_n       (rst_n),

        .data_i      (data_i),
        .data_o      (data_o),
        .data_oe     (data_oe),

        .a_valid_i   (a_valid_i),
        .a_ready_o   (a_ready_o),
        .a_last_i    (a_last_i),

        .b_valid_i   (b_valid_i),
        .b_ready_o   (b_ready_o),
        .b_last_i    (b_last_i),

        .out_valid_o (out_valid_o),
        .out_ready_i (out_ready_i),
        .out_last_o  (out_last_o)
    );

endmodule

`default_nettype wire
