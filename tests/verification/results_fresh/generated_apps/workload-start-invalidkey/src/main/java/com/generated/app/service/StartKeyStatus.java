package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for START-KEY-STATUS.
 * Auto-generated from Java Application IR.
 */
@Service
public class StartKeyStatus {
    private String IDX_KEY = "";
    private String IDX_DATA = "";
    private String WS_FILE_STATUS = "00";

    public StartKeyStatus() {}

    public void MAIN_LOGIC() {
        System.out.println("START/INVALID KEY/FILE STATUS DEMO STARTED");
        WS_FILE_STATUS = FileIoSupport.open("START.DAT", "OUTPUT", 4);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "RECORD-ONE----------";
        WS_FILE_STATUS = FileIoSupport.write("START.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "RECORD-TWO---------";
        WS_FILE_STATUS = FileIoSupport.write("START.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        IDX_DATA = "RECORD-THREE--------";
        WS_FILE_STATUS = FileIoSupport.write("START.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE K003 STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.close("START.DAT");
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS);
        WS_FILE_STATUS = FileIoSupport.open("START.DAT", "I-O", 4);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        WS_FILE_STATUS = FileIoSupport.start("START.DAT", "=", IDX_KEY);
        System.out.println("START = K002 STATUS=" + WS_FILE_STATUS);
        String _read_0 = FileIoSupport.readKey("START.DAT", IDX_KEY);
        if ((_read_0 != null)) {
            WS_FILE_STATUS = "00";
            IDX_KEY = FileIoSupport.pad(_read_0, 24, false).substring(0, 4);
            IDX_DATA = FileIoSupport.pad(_read_0, 24, false).substring(4, 24);
        } else {
            WS_FILE_STATUS = "23";
        }
        System.out.println("READ AFTER START = KEY=" + IDX_KEY + " STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        WS_FILE_STATUS = FileIoSupport.start("START.DAT", ">", IDX_KEY);
        System.out.println("START > K001 STATUS=" + WS_FILE_STATUS);
        String _read_1 = FileIoSupport.readKey("START.DAT", IDX_KEY);
        if ((_read_1 != null)) {
            WS_FILE_STATUS = "00";
            IDX_KEY = FileIoSupport.pad(_read_1, 24, false).substring(0, 4);
            IDX_DATA = FileIoSupport.pad(_read_1, 24, false).substring(4, 24);
        } else {
            WS_FILE_STATUS = "23";
        }
        System.out.println("READ AFTER START > KEY=" + IDX_KEY + " STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K999";
        WS_FILE_STATUS = FileIoSupport.start("START.DAT", "=", IDX_KEY);
        if ("23".equals(WS_FILE_STATUS)) {
            System.out.println("START = K999 INVALID KEY STATUS=" + WS_FILE_STATUS);
        }
        IDX_KEY = "K001";
        IDX_DATA = "DUPLICATE-KEY-------";
        WS_FILE_STATUS = FileIoSupport.write("START.DAT", FileIoSupport.pad(IDX_KEY, 4, false) + FileIoSupport.pad(IDX_DATA, 20, false), 4);
        if ("22".equals(WS_FILE_STATUS)) {
            System.out.println("WRITE DUPLICATE K001 INVALID KEY STATUS=" + WS_FILE_STATUS);
        }
        IDX_KEY = "K999";
        String _read_2 = FileIoSupport.readKey("START.DAT", IDX_KEY);
        if ((_read_2 != null)) {
            WS_FILE_STATUS = "00";
            IDX_KEY = FileIoSupport.pad(_read_2, 24, false).substring(0, 4);
            IDX_DATA = FileIoSupport.pad(_read_2, 24, false).substring(4, 24);
        } else {
            WS_FILE_STATUS = "23";
            System.out.println("READ K999 INVALID KEY STATUS=" + WS_FILE_STATUS);
        }
        IDX_KEY = "K002";
        WS_FILE_STATUS = FileIoSupport.delete("START.DAT", IDX_KEY, 4);
        if ("23".equals(WS_FILE_STATUS)) {
            System.out.println("DELETE K002 INVALID KEY STATUS=" + WS_FILE_STATUS);
        }
        IDX_KEY = "K002";
        WS_FILE_STATUS = FileIoSupport.delete("START.DAT", IDX_KEY, 4);
        if ("23".equals(WS_FILE_STATUS)) {
            System.out.println("DELETE K002 AGAIN INVALID KEY STATUS=" + WS_FILE_STATUS);
        }
        WS_FILE_STATUS = FileIoSupport.close("START.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;
    }

}