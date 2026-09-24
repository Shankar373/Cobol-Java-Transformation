package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for MAIN.
 * Auto-generated from Java Application IR.
 */
@Service
public class Main {
    private int WS_VALUE = "PIC";

    private final Modify modify;

    public Main(Modify modify) {
        this.modify = modify;
    }

    public void MAIN_LOGIC() {
        System.out.println("MAIN STARTED");
        System.out.println("BEFORE CALL VALUE=" + String.format("%04d", WS_VALUE));
        modify.MAIN_LOGIC(WS_VALUE);
        System.out.println("AFTER CALL VALUE=" + String.format("%04d", WS_VALUE));
        return;
    }

}