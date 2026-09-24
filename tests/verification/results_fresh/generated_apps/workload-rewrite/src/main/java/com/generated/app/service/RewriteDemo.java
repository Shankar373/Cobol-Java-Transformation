package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for REWRITE-DEMO.
 * Auto-generated from Java Application IR.
 */
@Service
public class RewriteDemo {
    private String IDX_KEY = "";
    private String IDX_DATA = "";
    private String WS_FILE_STATUS = "00";

    public RewriteDemo() {}

    public void MAIN_LOGIC() {
        System.out.println("REWRITE DEMO STARTED");
        WS_FILE_STATUS = FileIoSupport.open("REWRITE.DAT", "OUTPUT", 4);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "ORIGINAL-DATA-ONE--";
        WS_FILE_STATUS = FileIoSupport.write("REWRITE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "ORIGINAL-DATA-TWO--";
        WS_FILE_STATUS = FileIoSupport.write("REWRITE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("REWRITE.DAT");
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.open("REWRITE.DAT", "I-O", 4);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "UPDATED-DATA-ONE---";
        WS_FILE_STATUS = FileIoSupport.rewrite("REWRITE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("REWRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        String _read_0 = FileIoSupport.readKey("REWRITE.DAT", IDX_KEY);
        if ((_read_0 != null)) {
            WS_FILE_STATUS = "00";
            IDX_KEY = FileIoSupport.pad(_read_0, 24, false).substring(0, 4);
            IDX_DATA = FileIoSupport.pad(_read_0, 24, false).substring(4, 24);
        } else {
            WS_FILE_STATUS = "23";
        }
        System.out.println("READ K002 DATA=" + IDX_DATA + " STATUS=" + WS_FILE_STATUS);
        IDX_DATA = "UPDATED-DATA-TWO---";
        WS_FILE_STATUS = FileIoSupport.rewrite("REWRITE.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("REWRITE K002 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("REWRITE.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;
    }

}