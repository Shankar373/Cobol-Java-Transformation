package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for MAIN.
 * Auto-generated from Java Application IR.
 */
@Service
public class Main {
    private String WS_PROG_NAME = "CALC";
    private int WS_INPUT_A = 10;
    private int WS_INPUT_B = 5;
    private int WS_RESULT = 0;

    public Main() {}

    public void MAIN_LOGIC() {
        System.out.println("MAIN STARTED");
        System.out.println("CALLING PROGRAM: " + WS_PROG_NAME);
        Ws_Prog_Name.MAIN_LOGIC(WS_INPUT_A, WS_INPUT_B, WS_RESULT);
        System.out.println("RESULT=" + String.format("%06d", WS_RESULT));
        return;
    }

}