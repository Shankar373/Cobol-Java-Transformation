package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for CALCULATE.
 * Auto-generated from Java Application IR.
 */
@Service
public class Calculate {
    private int WS_TEMP = 0;
    private int LS_INPUT_A = 0;
    private int LS_INPUT_B = 0;
    private int LS_RESULT = 0;

    public Calculate() {}

    public void MAIN_LOGIC() {
        System.out.println("SUBROUTINE CALCULATE STARTED");
        System.out.println("INPUT A=" + LS_INPUT_A);
        System.out.println("INPUT B=" + LS_INPUT_B);
        WS_TEMP = (LS_INPUT_A + LS_INPUT_B);
        LS_RESULT = WS_TEMP;
        System.out.println("SUBROUTINE RESULT=" + String.format("%06d", WS_TEMP));
    }

    public void MAIN_LOGIC() {
        System.out.println("SUBROUTINE CALCULATE STARTED");
        System.out.println("INPUT A=" + LS_INPUT_A);
        System.out.println("INPUT B=" + LS_INPUT_B);
        WS_TEMP = (LS_INPUT_A + LS_INPUT_B);
        LS_RESULT = WS_TEMP;
        System.out.println("SUBROUTINE RESULT=" + String.format("%06d", WS_TEMP));
    }

}