package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for COPYBOOK-FILE-MULTI.
 * Auto-generated from Java Application IR.
 */
@Service
public class CopybookFileMulti {
    private String EMP_ID = "";
    private String EMP_NAME = "";
    private String EMP_DEPT = "";
    private String EMP_RD_ID = "";
    private String EMP_RD_NAME = "";
    private String EMP_RD_DEPT = "";
    private String WS_OUT_STATUS = "00";
    private String WS_IN_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;
    private String EMP_SOURCE_REC = "";
    private String EMP_SRC_ID = "";
    private String EMP_SRC_NAME = "";
    private String EMP_SRC_DEPT = "";

    public CopybookFileMulti() {}

    public void MAIN_LOGIC() {
        System.out.println("COPYBOOK FILE MULTI DEMO STARTED");
        WS_OUT_STATUS = CobolFileIo.open("/workspace/output/emp.dat", "OUTPUT", 0);
        System.out.println("OPEN OUTPUT STATUS=" + WS_OUT_STATUS);
        EMP_SRC_ID = "E001";
        EMP_SRC_NAME = "ALICE";
        EMP_SRC_DEPT = "SALES001";
        EMP_ID = EMP_SRC_ID;
        EMP_NAME = EMP_SRC_NAME;
        EMP_DEPT = EMP_SRC_DEPT;
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/emp.dat", CobolFileIo.pad(EMP_ID, 4, false) + CobolFileIo.pad(EMP_NAME, 12, false) + CobolFileIo.pad(EMP_DEPT, 8, false), 0);
        System.out.println("WRITE E001 STATUS=" + WS_OUT_STATUS + " SRC-ID=" + EMP_SRC_ID);
        EMP_SRC_ID = "E002";
        EMP_SRC_NAME = "BOB";
        EMP_SRC_DEPT = "ENGG0001";
        EMP_ID = EMP_SRC_ID;
        EMP_NAME = EMP_SRC_NAME;
        EMP_DEPT = EMP_SRC_DEPT;
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/emp.dat", CobolFileIo.pad(EMP_ID, 4, false) + CobolFileIo.pad(EMP_NAME, 12, false) + CobolFileIo.pad(EMP_DEPT, 8, false), 0);
        System.out.println("WRITE E002 STATUS=" + WS_OUT_STATUS + " SRC-ID=" + EMP_SRC_ID);
        EMP_SRC_ID = "E003";
        EMP_SRC_NAME = "CAROL";
        EMP_SRC_DEPT = "TECH0001";
        EMP_ID = EMP_SRC_ID;
        EMP_NAME = EMP_SRC_NAME;
        EMP_DEPT = EMP_SRC_DEPT;
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/emp.dat", CobolFileIo.pad(EMP_ID, 4, false) + CobolFileIo.pad(EMP_NAME, 12, false) + CobolFileIo.pad(EMP_DEPT, 8, false), 0);
        System.out.println("WRITE E003 STATUS=" + WS_OUT_STATUS + " SRC-ID=" + EMP_SRC_ID);
        WS_OUT_STATUS = CobolFileIo.close("/workspace/output/emp.dat");
        System.out.println("CLOSE OUT STATUS=" + WS_OUT_STATUS);
        WS_IN_STATUS = CobolFileIo.open("/workspace/output/emp.dat", "INPUT", 0);
        System.out.println("OPEN INPUT STATUS=" + WS_IN_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            String _read_0 = CobolFileIo.readNext("/workspace/output/emp.dat");
            if ((_read_0 != null)) {
                WS_IN_STATUS = "00";
                EMP_RD_ID = CobolFileIo.pad(_read_0, 24, false).substring(0, 4);
                EMP_RD_NAME = CobolFileIo.pad(_read_0, 24, false).substring(4, 16);
                EMP_RD_DEPT = CobolFileIo.pad(_read_0, 24, false).substring(16, 24);
                WS_COUNT = (WS_COUNT + 1);
                System.out.println("READ: ID=" + EMP_RD_ID + " NAME=" + EMP_RD_NAME + " DEPT=" + EMP_RD_DEPT);
            } else {
                WS_IN_STATUS = "10";
                WS_EOF = "Y";
            }
        }
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        WS_IN_STATUS = CobolFileIo.close("/workspace/output/emp.dat");
        System.out.println("CLOSE IN STATUS=" + WS_IN_STATUS);
        return;
    }

}