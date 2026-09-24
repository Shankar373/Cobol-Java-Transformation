import java.io.PrintStream;

public class Indexed_File_Demo {
    static String WS_FILE_STATUS = "00";
    static String WS_EOF = "N";
    static int WS_COUNT = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("INDEXED FILE DEMO STARTED" + OPEN + OUTPUT + IDX_FILE);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "RECORD-ONE-DATA----";
        // // WRITE IDX-REC
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "RECORD-TWO-DATA----";
        // // WRITE IDX-REC
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        IDX_DATA = "RECORD-THREE-DATA---";
        // // WRITE IDX-REC
        System.out.println("WRITE K003 STATUS=" + WS_FILE_STATUS);
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS + OPEN + I_O + IDX_FILE);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "REC-TWO-UPDATED----";
        System.out.println("REWRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        System.out.println("DELETE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        System.out.println("START K001 STATUS=" + WS_FILE_STATUS);
        WS_EOF = "N";
        WS_COUNT = 0;
        UNTIL();
        WS_COUNT = (WS_COUNT + 1);
System.out.println("READ: KEY=" + IDX_KEY + " DATA=" + IDX_DATA + " STATUS=" + WS_FILE_STATUS);
System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
return;

    }
}
