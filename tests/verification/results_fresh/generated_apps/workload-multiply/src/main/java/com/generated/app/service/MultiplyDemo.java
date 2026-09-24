package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for MULTIPLY-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class MultiplyDemo {
    private int WS_A = 10;
    private int WS_B = 5;
    private int WS_RESULT = 0;
    private int WS_TEMP = 3;

    public MultiplyDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("MULTIPLY DEMO STARTED");
        System.out.println("WS-A=" + String.format("%04d", WS_A));
        System.out.println("WS-B=" + String.format("%04d", WS_B));
        WS_RESULT = (WS_A * WS_B);
        System.out.println("MULTIPLY A BY B GIVING RESULT=" + String.format("%08d", WS_RESULT));
        WS_A = (4 * WS_A);
        System.out.println("MULTIPLY 4 BY A (in-place) A=" + String.format("%04d", WS_A));
        WS_RESULT = (WS_B * WS_TEMP);
        System.out.println("MULTIPLY B BY TEMP GIVING RESULT=" + String.format("%08d", WS_RESULT));
        WS_RESULT = (WS_A * WS_B);
        System.out.println("MULTIPLY A BY B GIVING RESULT=" + String.format("%08d", WS_RESULT));
        return;
    }

}