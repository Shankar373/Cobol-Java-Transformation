import java.io.PrintStream;

public class Perform_Varying_Demo {
    static int WS_I = 0;
    static int WS_SUM = 0;
    static int WS_J = 0;
    static int WS_PROD = 1;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("PERFORM VARYING DEMO STARTED" + PERFORM + VARYING + String.format("%02d", WS_I) + FROM + BY + UNTIL + String.format("%02d", WS_I) + ADD + String.format("%02d", WS_I) + TO + String.format("%04d", WS_SUM));
        System.out.println("I=" + String.format("%02d", WS_I) + " SUM=" + String.format("%04d", WS_SUM));
        System.out.println("FINAL SUM=" + String.format("%04d", WS_SUM) + PERFORM + VARYING + String.format("%02d", WS_J) + FROM + BY + UNTIL + String.format("%02d", WS_J) + MULTIPLY + String.format("%02d", WS_J) + BY + String.format("%04d", WS_PROD) + GIVING + String.format("%04d", WS_PROD));
        System.out.println("J=" + String.format("%02d", WS_J) + " PROD=" + String.format("%04d", WS_PROD));
        System.out.println("FINAL PROD=" + String.format("%04d", WS_PROD));
        return;

    }
}
