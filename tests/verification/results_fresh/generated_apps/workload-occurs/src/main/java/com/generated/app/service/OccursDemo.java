package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for OCCURS-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class OccursDemo {
    private String WS_TABLE = "";
    private int WS_INDEX = 0;
    private int WS_SUM = 0;

    public OccursDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("OCCURS DEMO STARTED");
        for (int WS_INDEX = 1; (WS_INDEX <= 5); WS_INDEX = (WS_INDEX + 1)) {
            WS_ELEMENT(WS_INDEX) = (WS_INDEX * 10);
            System.out.println("ELEMENT(" + String.format("%02d", WS_INDEX) + ")=" + WS_ELEMENT + String.format("%02d", WS_INDEX));
        }
        for (int WS_INDEX = 1; (WS_INDEX <= 5); WS_INDEX = (WS_INDEX + 1)) {
            WS_SUM = (WS_SUM + WS_ELEMENT(WS_INDEX));
        }
        System.out.println("SUM OF ELEMENTS=" + String.format("%04d", WS_SUM));
        return;
    }

}