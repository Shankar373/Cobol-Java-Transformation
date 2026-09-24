package com.generated.app.service;

import org.springframework.stereotype.Service;

/**
 * Service component for IDX-RWDEL-START.
 * Auto-generated from Java Application IR.
 */
@Service
public class IdxRwdelStart {
    private String IDX_KEY = "";
    private String IDX_DATA = "";
    private String WS_STATUS = "00";
    private String WS_EOF = "N";
    private int WS_COUNT = 0;

    public IdxRwdelStart() {}

    public void MAIN_LOGIC() {
        System.out.println("INDEXED REWRITE/DELETE/START DEMO STARTED");
        WS_STATUS = CobolFileIo.open("RWDEL.DAT", "OUTPUT", 4);
        System.out.println("OPEN OUTPUT STATUS=" + WS_STATUS);
        IDX_KEY = "R001";
        IDX_DATA = "REC-ONE-ORIGINAL----";
        WS_STATUS = CobolFileIo.write("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE R001 STATUS=" + WS_STATUS);
        IDX_KEY = "R002";
        IDX_DATA = "REC-TWO-ORIGINAL----";
        WS_STATUS = CobolFileIo.write("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE R002 STATUS=" + WS_STATUS);
        IDX_KEY = "R003";
        IDX_DATA = "REC-THREE-ORIGINAL--";
        WS_STATUS = CobolFileIo.write("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        System.out.println("WRITE R003 STATUS=" + WS_STATUS);
        IDX_KEY = "R002";
        IDX_DATA = "REC-TWO-DUPLICATE---";
        WS_STATUS = CobolFileIo.write("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        if ("22".equals(WS_STATUS)) {
            System.out.println("WRITE DUP R002 INVALID KEY STATUS=" + WS_STATUS);
        }
        System.out.println("POST WRITE DUP STATUS=" + WS_STATUS);
        WS_STATUS = CobolFileIo.close("RWDEL.DAT");
        System.out.println("CLOSE STATUS=" + WS_STATUS);
        WS_STATUS = CobolFileIo.open("RWDEL.DAT", "I-O", 4);
        System.out.println("OPEN I-O STATUS=" + WS_STATUS);
        IDX_KEY = "R002";
        IDX_DATA = "REC-TWO-REWRITTEN---";
        WS_STATUS = CobolFileIo.rewrite("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        System.out.println("REWRITE R002 STATUS=" + WS_STATUS);
        IDX_KEY = "R002";
        String _read_0 = CobolFileIo.readKey("RWDEL.DAT", IDX_KEY);
        if ((_read_0 != null)) {
            WS_STATUS = "00";
            IDX_KEY = CobolFileIo.pad(_read_0, 24, false).substring(0, 4);
            IDX_DATA = CobolFileIo.pad(_read_0, 24, false).substring(4, 24);
        } else {
            WS_STATUS = "23";
        }
        System.out.println("READ KEY R002 DATA=" + IDX_DATA + " STATUS=" + WS_STATUS);
        IDX_KEY = "R001";
        WS_STATUS = CobolFileIo.start("RWDEL.DAT", "=", IDX_KEY);
        System.out.println("START = R001 STATUS=" + WS_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        while ((!(WS_EOF == "Y"))) {
            String _read_1 = CobolFileIo.readNext("RWDEL.DAT");
            if ((_read_1 != null)) {
                WS_STATUS = "00";
                IDX_KEY = CobolFileIo.pad(_read_1, 24, false).substring(0, 4);
                IDX_DATA = CobolFileIo.pad(_read_1, 24, false).substring(4, 24);
                WS_COUNT = (WS_COUNT + 1);
                System.out.println("NEXT: KEY=" + IDX_KEY + " DATA=" + IDX_DATA + " STATUS=" + WS_STATUS);
            } else {
                WS_STATUS = "10";
                WS_EOF = "Y";
            }
        }
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        IDX_KEY = "R003";
        WS_STATUS = CobolFileIo.start("RWDEL.DAT", ">=", IDX_KEY);
        System.out.println("START >= R003 STATUS=" + WS_STATUS);
        String _read_2 = CobolFileIo.readNext("RWDEL.DAT");
        if ((_read_2 != null)) {
            WS_STATUS = "00";
            IDX_KEY = CobolFileIo.pad(_read_2, 24, false).substring(0, 4);
            IDX_DATA = CobolFileIo.pad(_read_2, 24, false).substring(4, 24);
            System.out.println("NEXT FROM >= R003: KEY=" + IDX_KEY + " DATA=" + IDX_DATA);
        } else {
            WS_STATUS = "10";
            WS_EOF = "Y";
        }
        WS_STATUS = CobolFileIo.delete("RWDEL.DAT", IDX_KEY, 4);
        System.out.println("DELETE R003 STATUS=" + WS_STATUS);
        WS_STATUS = CobolFileIo.delete("RWDEL.DAT", IDX_KEY, 4);
        if ("23".equals(WS_STATUS)) {
            System.out.println("DELETE R003 AGAIN INVALID KEY STATUS=" + WS_STATUS);
        }
        IDX_KEY = "R999";
        String _read_3 = CobolFileIo.readKey("RWDEL.DAT", IDX_KEY);
        if ((_read_3 != null)) {
            WS_STATUS = "00";
            IDX_KEY = CobolFileIo.pad(_read_3, 24, false).substring(0, 4);
            IDX_DATA = CobolFileIo.pad(_read_3, 24, false).substring(4, 24);
        } else {
            WS_STATUS = "23";
            System.out.println("READ R999 INVALID KEY STATUS=" + WS_STATUS);
        }
        IDX_KEY = "R001";
        String _read_4 = CobolFileIo.readKey("RWDEL.DAT", IDX_KEY);
        if ((_read_4 != null)) {
            WS_STATUS = "00";
            IDX_KEY = CobolFileIo.pad(_read_4, 24, false).substring(0, 4);
            IDX_DATA = CobolFileIo.pad(_read_4, 24, false).substring(4, 24);
            System.out.println("READ R001 OK DATA=" + IDX_DATA + " STATUS=" + WS_STATUS);
        } else {
            WS_STATUS = "23";
        }
        IDX_KEY = "R999";
        IDX_DATA = "REC-NINE-NEVER----";
        WS_STATUS = CobolFileIo.rewrite("RWDEL.DAT", CobolFileIo.pad(IDX_KEY, 4, false) + CobolFileIo.pad(IDX_DATA, 20, false), 4);
        if ("23".equals(WS_STATUS)) {
            System.out.println("REWRITE R999 INVALID KEY STATUS=" + WS_STATUS);
        }
        WS_STATUS = CobolFileIo.close("RWDEL.DAT");
        System.out.println("FINAL CLOSE STATUS=" + WS_STATUS);
        return;
    }

}