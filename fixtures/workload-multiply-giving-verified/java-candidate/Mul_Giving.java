import java.io.PrintStream;

public class Mul_Giving {
    static int WS_A = 0;
    static int WS_B = 0;
    static int WS_C = 0;
    static int WS_D = 0;

    public static void MAIN_LOGIC() throws Exception {
        System.out.println("MUL GIVING DEMO STARTED");
        WS_A = 10;
        WS_B = 25;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_A * WS_B);
        System.out.println("MUL A BY B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_B = (4 * WS_B);
        System.out.println("MUL 4 BY B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = (WS_A * WS_B);
        System.out.println("MUL A BY B GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("MUL GIVING DEMO COMPLETED");
        return;
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("MUL GIVING DEMO STARTED");
        WS_A = 10;
        WS_B = 25;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_A * WS_B);
        System.out.println("MUL A BY B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_B = (4 * WS_B);
        System.out.println("MUL 4 BY B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_D = (WS_A * WS_B);
        System.out.println("MUL A BY B GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("MUL GIVING DEMO COMPLETED");
        return;
    }}
