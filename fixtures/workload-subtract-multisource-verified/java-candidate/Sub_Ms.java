import java.io.PrintStream;

public class Sub_Ms {
    static int WS_A = 0;
    static int WS_B = 0;
    static int WS_C = 0;
    static int WS_D = 0;

    public static void MAIN_LOGIC() throws Exception {
        System.out.println("SUB MULTISOURCE DEMO STARTED");
        WS_A = 10;
        WS_B = 5;
        WS_C = 100;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = ((WS_C - WS_A) - WS_B);
        System.out.println("SUB A B FROM C GIVING D: D=" + String.format("%05d", WS_D) + " C=" + String.format("%05d", WS_C));
        WS_A = 10;
        WS_B = 5;
        WS_C = 100;
        WS_C = ((WS_C - WS_A) - WS_B);
        System.out.println("SUB A B FROM C INPLACE: C=" + String.format("%05d", WS_C));
        System.out.println("SUB MULTISOURCE DEMO COMPLETED");
        return;
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("SUB MULTISOURCE DEMO STARTED");
        WS_A = 10;
        WS_B = 5;
        WS_C = 100;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = ((WS_C - WS_A) - WS_B);
        System.out.println("SUB A B FROM C GIVING D: D=" + String.format("%05d", WS_D) + " C=" + String.format("%05d", WS_C));
        WS_A = 10;
        WS_B = 5;
        WS_C = 100;
        WS_C = ((WS_C - WS_A) - WS_B);
        System.out.println("SUB A B FROM C INPLACE: C=" + String.format("%05d", WS_C));
        System.out.println("SUB MULTISOURCE DEMO COMPLETED");
        return;
    }}
