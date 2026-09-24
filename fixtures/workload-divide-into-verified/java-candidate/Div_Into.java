import java.io.PrintStream;

public class Div_Into {
    static int WS_A = 0;
    static int WS_B = 0;
    static int WS_C = 0;
    static int WS_D = 0;

    public static void MAIN_LOGIC() throws Exception {
        System.out.println("DIV INTO DEMO STARTED");
        WS_A = 100;
        WS_B = 7;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_B / WS_A);
        System.out.println("DIV A INTO B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_A = 100;
        WS_B = 7;
        WS_B = (WS_B / WS_A);
        System.out.println("DIV A INTO B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_A = 100;
        WS_B = 7;
        WS_D = (WS_A / WS_B);
        System.out.println("DIV B INTO A GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("DIV INTO DEMO COMPLETED");
        return;
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("DIV INTO DEMO STARTED");
        WS_A = 100;
        WS_B = 7;
        System.out.println("INITIAL A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_C = (WS_B / WS_A);
        System.out.println("DIV A INTO B GIVING C: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " C=" + String.format("%05d", WS_C));
        WS_A = 100;
        WS_B = 7;
        WS_B = (WS_B / WS_A);
        System.out.println("DIV A INTO B INPLACE: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B));
        WS_A = 100;
        WS_B = 7;
        WS_D = (WS_A / WS_B);
        System.out.println("DIV B INTO A GIVING D: A=" + String.format("%05d", WS_A) + " B=" + String.format("%05d", WS_B) + " D=" + String.format("%05d", WS_D));
        System.out.println("DIV INTO DEMO COMPLETED");
        return;
    }}
