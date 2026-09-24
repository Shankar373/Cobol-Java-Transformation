import java.io.PrintStream;

public class Sub_Giving {
    static int WS_A = 0;
    static int WS_B = 0;
    static int WS_C = 0;
    static int WS_D = 0;

    public static void MAIN_LOGIC() throws Exception {
        System.out.println("SUB GIVING DEMO STARTED");
        WS_A = 10;
        WS_B = 25;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_B - WS_A);
        System.out.println("SUB A FROM B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_B = (WS_B - 5);
        System.out.println("SUB 5 FROM B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = (WS_B - WS_A);
        System.out.println("SUB A FROM B GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("SUB GIVING DEMO COMPLETED");
        return;
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("SUB GIVING DEMO STARTED");
        WS_A = 10;
        WS_B = 25;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_B - WS_A);
        System.out.println("SUB A FROM B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_B = (WS_B - 5);
        System.out.println("SUB 5 FROM B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = (WS_B - WS_A);
        System.out.println("SUB A FROM B GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("SUB GIVING DEMO COMPLETED");
        return;
    }}
