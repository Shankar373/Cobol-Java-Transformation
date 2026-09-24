package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for REDEFINES-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class RedefinesDemo {
    private String WS_RECORD = "";

    public RedefinesDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("REDEFINES DEMO STARTED");
        System.out.println("WS-NUMERIC=" + WS_NUMERIC);
        System.out.println("WS-PART1=" + WS_PART1);
        System.out.println("WS-PART2=" + WS_PART2);
        System.out.println("WS-CHAR=" + WS_CHAR);
        WS_CHAR = "ABCDEF";
        System.out.println("AFTER MOVE CHARS:");
        System.out.println("WS-NUMERIC=" + WS_NUMERIC);
        System.out.println("WS-PART1=" + WS_PART1);
        System.out.println("WS-PART2=" + WS_PART2);
        System.out.println("WS-CHAR=" + WS_CHAR);
        return;
    }

}