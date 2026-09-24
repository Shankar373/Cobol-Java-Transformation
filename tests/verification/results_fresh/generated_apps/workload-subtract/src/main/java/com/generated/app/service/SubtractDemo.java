package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for SUBTRACT-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class SubtractDemo {
    private int WS_A = 100;
    private int WS_B = 25;
    private int WS_RESULT = 0;
    private int WS_TEMP = 50;

    public SubtractDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("SUBTRACT DEMO STARTED");
        System.out.println("WS-A=" + String.format("%04d", WS_A));
        System.out.println("WS-B=" + String.format("%04d", WS_B));
        WS_RESULT = (WS_A - WS_B);
        System.out.println("SUBTRACT B FROM A GIVING RESULT=" + String.format("%04d", WS_RESULT));
        WS_A = (WS_A - 10);
        System.out.println("SUBTRACT 10 FROM A (in-place) A=" + String.format("%04d", WS_A));
        WS_RESULT = (WS_TEMP - WS_B);
        System.out.println("SUBTRACT B FROM TEMP GIVING RESULT=" + String.format("%04d", WS_RESULT));
        WS_RESULT = ((200 - WS_A) - WS_B);
        System.out.println("SUBTRACT A B FROM 200 GIVING RESULT=" + String.format("%04d", WS_RESULT));
        return;
    }

}