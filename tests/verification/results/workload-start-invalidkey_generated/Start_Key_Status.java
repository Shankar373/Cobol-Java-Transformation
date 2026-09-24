import java.io.PrintStream;

public class Start_Key_Status {
    static String WS_FILE_STATUS = "00";

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("START/INVALID KEY/FILE STATUS DEMO STARTED" + OPEN + OUTPUT + IDX_FILE);
        System.out.println("OPEN OUTPUT STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "RECORD-ONE----------";
        // // WRITE IDX-REC
        System.out.println("WRITE K001 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        IDX_DATA = "RECORD-TWO---------";
        // // WRITE IDX-REC
        System.out.println("WRITE K002 STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K003";
        IDX_DATA = "RECORD-THREE--------";
        // // WRITE IDX-REC
        System.out.println("WRITE K003 STATUS=" + WS_FILE_STATUS);
        System.out.println("CLOSE STATUS=" + WS_FILE_STATUS + OPEN + I_O + IDX_FILE);
        System.out.println("OPEN I-O STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        System.out.println("START = K002 STATUS=" + WS_FILE_STATUS + READ + IDX_FILE);
        System.out.println("READ AFTER START = KEY=" + IDX_KEY + " STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        System.out.println("START > K001 STATUS=" + WS_FILE_STATUS + READ + IDX_FILE);
        System.out.println("READ AFTER START > KEY=" + IDX_KEY + " STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K999";
        System.out.println("START = K999 INVALID KEY STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K001";
        IDX_DATA = "DUPLICATE-KEY-------";
        // // WRITE IDX-REC
        System.out.println("WRITE DUPLICATE K001 INVALID KEY STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K999";
        IDX_KEY = "K002";
        System.out.println("DELETE K002 INVALID KEY STATUS=" + WS_FILE_STATUS);
        IDX_KEY = "K002";
        System.out.println("DELETE K002 AGAIN INVALID KEY STATUS=" + WS_FILE_STATUS);
        System.out.println("FINAL CLOSE STATUS=" + WS_FILE_STATUS);
        return;

    }
}
