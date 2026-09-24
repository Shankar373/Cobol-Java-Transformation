package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for FILE-WRITE-READ.
 * Auto-generated from Java Application IR.
 */
@Service
public class FileWriteRead {
    private String OUT_ID = "";
    private String OUT_VAL = "";
    private String IN_ID = "";
    private String IN_VAL = "";
    private String WS_OUT_STATUS = "00";
    private String WS_IN_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;

    public FileWriteRead() {}

    public void MAIN_LOGIC() {
        System.out.println("SEQUENTIAL WRITE/READ DEMO STARTED");
        WS_OUT_STATUS = CobolFileIo.open("/workspace/output/wr.dat", "OUTPUT", 0);
        System.out.println("OPEN OUTPUT STATUS=" + WS_OUT_STATUS);
        OUT_ID = "R001";
        OUT_VAL = "VALUE-ONE---";
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/wr.dat", CobolFileIo.pad(OUT_ID, 4, false) + CobolFileIo.pad(OUT_VAL, 12, false), 0);
        System.out.println("WRITE R001 STATUS=" + WS_OUT_STATUS);
        OUT_ID = "R002";
        OUT_VAL = "VALUE-TWO---";
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/wr.dat", CobolFileIo.pad(OUT_ID, 4, false) + CobolFileIo.pad(OUT_VAL, 12, false), 0);
        System.out.println("WRITE R002 STATUS=" + WS_OUT_STATUS);
        OUT_ID = "R003";
        OUT_VAL = "VALUE-THREE-";
        WS_OUT_STATUS = CobolFileIo.write("/workspace/output/wr.dat", CobolFileIo.pad(OUT_ID, 4, false) + CobolFileIo.pad(OUT_VAL, 12, false), 0);
        System.out.println("WRITE R003 STATUS=" + WS_OUT_STATUS);
        WS_OUT_STATUS = CobolFileIo.close("/workspace/output/wr.dat");
        System.out.println("CLOSE OUT STATUS=" + WS_OUT_STATUS);
        WS_IN_STATUS = CobolFileIo.open("/workspace/output/wr.dat", "INPUT", 0);
        System.out.println("OPEN INPUT STATUS=" + WS_IN_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            String _read_0 = CobolFileIo.readNext("/workspace/output/wr.dat");
            if ((_read_0 != null)) {
                WS_IN_STATUS = "00";
                IN_ID = CobolFileIo.pad(_read_0, 16, false).substring(0, 4);
                IN_VAL = CobolFileIo.pad(_read_0, 16, false).substring(4, 16);
                WS_COUNT = (WS_COUNT + 1);
                System.out.println("READ: ID=" + IN_ID + " VAL=" + IN_VAL + " STATUS=" + WS_IN_STATUS);
            } else {
                WS_IN_STATUS = "10";
                WS_EOF = "Y";
            }
        }
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        WS_IN_STATUS = CobolFileIo.close("/workspace/output/wr.dat");
        System.out.println("CLOSE IN STATUS=" + WS_IN_STATUS);
        return;
    }

}