package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for INDEXED-FILE-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class IndexedFileDemo {
    private String IDX_KEY = "";
    private String IDX_DATA = "";
    private String WS_FILE_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;

    public IndexedFileDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("INDEXED FILE DEMO STARTED");
        WS_FILE_STATUS = FileIoSupport.open("IDXFILE.DAT", "OUTPUT", 4);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "RECORD-ONE-DATA----";
        WS_FILE_STATUS = FileIoSupport.write("IDXFILE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "RECORD-TWO-DATA----";
        WS_FILE_STATUS = FileIoSupport.write("IDXFILE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        IDX_DATA = "RECORD-THREE-DATA---";
        WS_FILE_STATUS = FileIoSupport.write("IDXFILE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K003 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("IDXFILE.DAT");
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.open("IDXFILE.DAT", "I-O", 4);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "REC-TWO-UPDATED----";
        WS_FILE_STATUS = FileIoSupport.rewrite("IDXFILE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("REWRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        WS_FILE_STATUS = FileIoSupport.delete("IDXFILE.DAT", IDX_KEY, 4);
        System.out.println("DELETE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        WS_FILE_STATUS = FileIoSupport.start("IDXFILE.DAT", ">=", IDX_KEY);
        System.out.println("START K001 STATUS=" + WS_FILE_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            String _read_0 = FileIoSupport.readNext("IDXFILE.DAT");
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
        WS_FILE_STATUS = FileIoSupport.close("IDXFILE.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;
    }

}