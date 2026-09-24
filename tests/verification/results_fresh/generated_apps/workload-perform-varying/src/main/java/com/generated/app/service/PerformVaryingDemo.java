package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for PERFORM-VARYING-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class PerformVaryingDemo {
    private int WS_I = 0;
    private int WS_SUM = 0;
    private int WS_J = 0;
    private int WS_PROD = 1;

    public PerformVaryingDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("PERFORM VARYING DEMO STARTED");
        for (int WS_I = 1; (WS_I <= 5); WS_I = (WS_I + 1)) {
            WS_SUM = (WS_SUM + WS_I);
            System.out.println("I=" + String.format("%02d", WS_I) + " SUM=" + String.format("%04d", WS_SUM));
        }
        System.out.println("FINAL SUM=" + String.format("%04d", WS_SUM));
        for (int WS_J = 1; (WS_J <= 4); WS_J = (WS_J + 1)) {
            WS_PROD = (WS_J * WS_PROD);
            System.out.println("J=" + String.format("%02d", WS_J) + " PROD=" + String.format("%04d", WS_PROD));
        }
        System.out.println("FINAL PROD=" + String.format("%04d", WS_PROD));
        return;
    }

}