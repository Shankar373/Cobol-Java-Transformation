import java.io.PrintStream;

public class Relative_File_Demo {
    static int WS_RRN = 0;
    static String WS_FILE_STATUS = "00";
    static String WS_EOF = "N";
    static int WS_COUNT = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("RELATIVE FILE DEMO STARTED" + OPEN + OUTPUT + REL_FILE);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        WS_RRN = 1;
        REL_DATA = "REL-RECORD-ONE-----";
        // // WRITE REL-REC
        System.out.println("WRITE RRN=1 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 2;
        REL_DATA = "REL-RECORD-TWO-----";
        // // WRITE REL-REC
        System.out.println("WRITE RRN=2 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 3;
        REL_DATA = "REL-RECORD-THREE----";
        // // WRITE REL-REC
        System.out.println("WRITE RRN=3 STATUS=" + WS_FILE_STATUS);
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS + OPEN + I_O + REL_FILE);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        WS_RRN = 2;
        REL_DATA = "REL-REC-TWO-UPD----";
        System.out.println("REWRITE RRN=2 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 1;
        System.out.println("DELETE RRN=1 STATUS=" + WS_FILE_STATUS);
        WS_RRN = 0;
        WS_EOF = "N";
        WS_COUNT = 0;
        UNTIL();
        WS_RRN = (WS_RRN + 1);
        if (WS_RRN > == 3) {
    WS_EOF = "Y";
}
        System.out.println("RECORDS READ=" + String.format("%02d", WS_COUNT));
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;

    }
}
