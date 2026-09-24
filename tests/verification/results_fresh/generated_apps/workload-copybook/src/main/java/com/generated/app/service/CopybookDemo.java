package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for COPYBOOK-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class CopybookDemo {
    private int WS_RESULT = 0;
    private int WS_COUNTER = 0;
    private String CLAIM_REC = "";
    private String CLAIM_ID = "C-001";
    private int CLAIM_AMOUNT = 500;

    public CopybookDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("COPYBOOK DEMO STARTED");
        CLAIM_AMOUNT = 100;
        CLAIM_ID = "C-999";
        System.out.println("INITIAL CLAIM-ID=" + CLAIM_ID);
        System.out.println("INITIAL CLAIM-AMOUNT=" + String.format("%06d", CLAIM_AMOUNT));
        WS_RESULT = CLAIM_AMOUNT;
        System.out.println("WS-RESULT=" + String.format("%08d", WS_RESULT));
        if ((CLAIM_AMOUNT > 500)) {
            System.out.println("AMOUNT GT 500");
        } else {
            System.out.println("AMOUNT LE 500");
        }
        System.out.println("FINAL CLAIM-ID=" + CLAIM_ID);
        System.out.println("FINAL CLAIM-AMOUNT=" + String.format("%06d", CLAIM_AMOUNT));
        return;
    }

}