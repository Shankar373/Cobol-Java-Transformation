package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for EVALUATE-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class EvaluateDemo {
    private int WS_GRADE = 85;
    private String WS_RESULT = "SPACES";

    public EvaluateDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("EVALUATE DEMO STARTED");
        System.out.println("GRADE=" + String.format("%02d", WS_GRADE));
        if (WS_GRADE >= 90 && WS_GRADE <= 100) {
            WS_RESULT = "A";
        } else {
            if (WS_GRADE >= 80 && WS_GRADE <= 89) {
                WS_RESULT = "B";
            } else {
                if (WS_GRADE >= 70 && WS_GRADE <= 79) {
                    WS_RESULT = "C";
                } else {
                    if (WS_GRADE >= 60 && WS_GRADE <= 69) {
                        WS_RESULT = "D";
                    } else {
                        WS_RESULT = "F";
                    }
                }
            }
        }
        System.out.println("LETTER GRADE=" + WS_RESULT);
        if (TRUE == WS_GRADE || TRUE == >= || TRUE == 90) {
            System.out.println("EXCELLENT");
        } else {
            if (TRUE == WS_GRADE || TRUE == >= || TRUE == 80) {
                System.out.println("GOOD");
            } else {
                if (TRUE == WS_GRADE || TRUE == >= || TRUE == 70) {
                    System.out.println("AVERAGE");
                } else {
                    if (TRUE == WS_GRADE || TRUE == >= || TRUE == 60) {
                        System.out.println("BELOW AVERAGE");
                    } else {
                        System.out.println("FAILING");
                    }
                }
            }
        }
        return;
    }

}