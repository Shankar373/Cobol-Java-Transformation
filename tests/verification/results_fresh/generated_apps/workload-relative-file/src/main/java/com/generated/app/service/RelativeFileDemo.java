package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for RELATIVE-FILE-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class RelativeFileDemo {
    private String REL_DATA = "";
    private int WS_RRN = 0;
    private String WS_FILE_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;

    public RelativeFileDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("RELATIVE FILE DEMO STARTED");
        WS_FILE_STATUS = FileIoSupport.open("RELFILE.DAT", "OUTPUT", -1);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        WS_RRN = 1;
        REL_DATA = "REL-RECORD-ONE-----";
        WS_FILE_STATUS = FileIoSupport.write("RELFILE.DAT", FileIoSupport.pad(REL_DATA, 20, false), WS_RRN);
        System.out.println("WRITE RRN=1 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 2;
        REL_DATA = "REL-RECORD-TWO-----";
        WS_FILE_STATUS = FileIoSupport.write("RELFILE.DAT", FileIoSupport.pad(REL_DATA, 20, false), WS_RRN);
        System.out.println("WRITE RRN=2 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 3;
        REL_DATA = "REL-RECORD-THREE----";
        WS_FILE_STATUS = FileIoSupport.write("RELFILE.DAT", FileIoSupport.pad(REL_DATA, 20, false), WS_RRN);
        System.out.println("WRITE RRN=3 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("RELFILE.DAT");
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.open("RELFILE.DAT", "I-O", -1);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        WS_RRN = 2;
        REL_DATA = "REL-REC-TWO-UPD----";
        WS_FILE_STATUS = FileIoSupport.rewrite("RELFILE.DAT", FileIoSupport.pad(REL_DATA, 20, false), WS_RRN);
        System.out.println("REWRITE RRN=2 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 1;
        WS_FILE_STATUS = FileIoSupport.deleteRelative("RELFILE.DAT", WS_RRN);
        System.out.println("DELETE RRN=1 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 0;
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            WS_RRN = (WS_RRN + 1);
            String _read_0 = FileIoSupport.readRelative("RELFILE.DAT", WS_RRN);
            if ((_read_0 != null)) {
                WS_FILE_STATUS = "00";
                REL_DATA = FileIoSupport.pad(_read_0, 20, false).substring(0, 20);
                WS_COUNT = (WS_COUNT + 1);
                System.out.println("READ: RRN=" + String.format("%04d", WS_RRN) + " DATA=" + REL_DATA + " STATUS=" + WS_FILE_STATUS);
            } else {
                WS_FILE_STATUS = "23";
                System.out.println("READ RRN=" + String.format("%04d", WS_RRN) + " INVALID KEY STATUS=" + WS_FILE_STATUS);
            }
            if ((WS_RRN >= 3)) {
                WS_EOF = "Y";
            }
        }
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        WS_FILE_STATUS = FileIoSupport.close("RELFILE.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;
    }

}