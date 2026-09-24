package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for LEVEL88-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class Level88Demo {
    private String WS_STATUS = 10;
    private String WS_GENDER = "M";
    private String WS_RESULT = "SPACES";

    public Level88Demo() {}

    public void MAIN_LOGIC() {
        System.out.println("LEVEL-88 DEMO STARTED");
        if ((TRUE == STAT_OK)) {
            WS_RESULT = "STATUS OK";
        } else {
            if ((TRUE == STAT_WARNING)) {
                WS_RESULT = "STATUS WARNING";
            } else {
                if ((TRUE == STAT_ERROR)) {
                    WS_RESULT = "STATUS ERROR";
                } else {
                    if ((TRUE == STAT_ERROR)) {
                        WS_RESULT = "STATUS ERROR";
                    }
                }
            }
        }
        System.out.println("STATUS CHECK: " + WS_RESULT);
        if ("GENDER_MALE") {
            System.out.println("GENDER IS MALE");
        } else {
            System.out.println("GENDER IS FEMALE");
        }
        System.out.println("AFTER SET STAT-OK: WS-STATUS=" + String.format("%02d", WS_STATUS));
        System.out.println("AFTER SET GENDER-FEMALE: WS-GENDER=" + WS_GENDER);
        return;
    }

}