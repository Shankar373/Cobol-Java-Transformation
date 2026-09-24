import java.io.PrintStream;

public class Rewrite_Demo {
    static String WS_FILE_STATUS = "00";

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("REWRITE DEMO STARTED" + OPEN + OUTPUT + IDX_FILE);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "ORIGINAL-DATA-ONE--";
        // // WRITE IDX-REC
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "ORIGINAL-DATA-TWO--";
        // // WRITE IDX-REC
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS + OPEN + I_O + IDX_FILE);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "UPDATED-DATA-ONE---";
        System.out.println("REWRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";

    }
}
