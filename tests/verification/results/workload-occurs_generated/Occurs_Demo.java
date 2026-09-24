import java.io.PrintStream;

public class Occurs_Demo {
    static String WS_TABLE = "";
    static int WS_INDEX = 0;
    static int WS_SUM = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("OCCURS DEMO STARTED" + PERFORM + VARYING + String.format("%02d", WS_INDEX) + FROM + BY + UNTIL + String.format("%02d", WS_INDEX) + COMPUTE + WS_ELEMENT + String.format("%02d", WS_INDEX) + String.format("%02d", WS_INDEX));
        System.out.println("ELEMENT(" + String.format("%02d", WS_INDEX) + ")=" + WS_ELEMENT + String.format("%02d", WS_INDEX) + PERFORM + VARYING + String.format("%02d", WS_INDEX) + FROM + BY + UNTIL + String.format("%02d", WS_INDEX) + ADD + WS_ELEMENT + String.format("%02d", WS_INDEX) + TO + String.format("%04d", WS_SUM));
        System.out.println("SUM OF ELEMENTS=" + String.format("%04d", WS_SUM));
        return;

    }
}
