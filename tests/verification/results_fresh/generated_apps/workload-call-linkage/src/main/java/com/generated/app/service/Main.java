package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for MAIN.
 * Auto-generated from Java Application IR.
 */
@Service
public class Main {
    private int WS_INPUT_A = 10;
    private int WS_INPUT_B = 5;
    private int WS_RESULT = 0;

    private final Calculate calculate;

    public Main(Calculate calculate) {
        this.calculate = calculate;
    }

    public void MAIN_LOGIC() {
        System.out.println("MAIN PROGRAM STARTED");
        System.out.println("INPUT A=" + String.format("%04d", WS_INPUT_A));
        System.out.println("INPUT B=" + String.format("%04d", WS_INPUT_B));
        calculate.MAIN_LOGIC(WS_INPUT_A, WS_INPUT_B, WS_RESULT);
        System.out.println("RESULT FROM SUBROUTINE=" + String.format("%06d", WS_RESULT));
        return;
    }

}