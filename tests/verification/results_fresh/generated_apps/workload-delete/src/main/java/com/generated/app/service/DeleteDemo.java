package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for DELETE-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class DeleteDemo {
    private String IDX_KEY = "";
    private String IDX_DATA = "";
    private String WS_FILE_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;

    public DeleteDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("DELETE DEMO STARTED");
        WS_FILE_STATUS = FileIoSupport.open("DELETE.DAT", "OUTPUT", 4);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "RECORD-ONE-TO-DELETE";
        WS_FILE_STATUS = FileIoSupport.write("DELETE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "RECORD-TWO-KEEP----";
        WS_FILE_STATUS = FileIoSupport.write("DELETE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        IDX_DATA = "RECORD-THREE-DELETE";
        WS_FILE_STATUS = FileIoSupport.write("DELETE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K003 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("DELETE.DAT");
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.open("DELETE.DAT", "I-O", 4);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        WS_FILE_STATUS = FileIoSupport.delete("DELETE.DAT", IDX_KEY, 4);
        System.out.println("DELETE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        WS_FILE_STATUS = FileIoSupport.delete("DELETE.DAT", IDX_KEY, 4);
        System.out.println("DELETE K003 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        WS_FILE_STATUS = FileIoSupport.start("DELETE.DAT", ">=", IDX_KEY);
        System.out.println("START K001 STATUS=" + WS_FILE_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            String _read_0 = FileIoSupport.readNext("DELETE.DAT");
            if ((_read_0 != null)) {
                WS_FILE_STATUS = "00";
                IDX_KEY = FileIoSupport.pad(_read_0, 24, false).substring(0, 4);
                IDX_DATA = FileIoSupport.pad(_read_0, 24, false).substring(4, 24);
                WS_COUNT = (WS_COUNT + 1);
                System.out.println("READ: KEY=" + IDX_KEY + " DATA=" + IDX_DATA + " STATUS=" + WS_FILE_STATUS);
            } else {
                WS_FILE_STATUS = "10";
                WS_EOF = "Y";
            }
        }
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        WS_FILE_STATUS = FileIoSupport.close("DELETE.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;
    }

}