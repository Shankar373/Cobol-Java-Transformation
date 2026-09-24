package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for CALC.
 * Auto-generated from Java Application IR.
 */
@Service
public class Calc {
    private int WS_TEMP = 0;
    private int LS_INPUT_A = 0;
    private int LS_INPUT_B = 0;
    private int LS_RESULT = 0;

    public Calc() {}

    public void MAIN_LOGIC() {
        System.out.println("CALC STARTED");
        System.out.println("INPUT A=" + LS_INPUT_A);
        System.out.println("INPUT B=" + LS_INPUT_B);
        WS_TEMP = (LS_INPUT_A * LS_INPUT_B);
        LS_RESULT = WS_TEMP;
        System.out.println("CALC RESULT=" + String.format("%06d", WS_TEMP));
    }

    public void MAIN_LOGIC() {
        System.out.println("CALC STARTED");
        System.out.println("INPUT A=" + LS_INPUT_A);
        System.out.println("INPUT B=" + LS_INPUT_B);
        WS_TEMP = (LS_INPUT_A * LS_INPUT_B);
        LS_RESULT = WS_TEMP;
        System.out.println("CALC RESULT=" + String.format("%06d", WS_TEMP));
    }

}