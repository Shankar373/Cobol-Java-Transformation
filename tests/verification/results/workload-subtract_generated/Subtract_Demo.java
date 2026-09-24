import java.io.PrintStream;

public class Subtract_Demo {
    static int WS_A = 100;
    static int WS_B = 25;
    static int WS_RESULT = 0;
    static int WS_TEMP = 50;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("SUBTRACT DEMO STARTED");
        System.out.println("WS-A=" + String.format("%04d", WS_A));
        System.out.println("WS-B=" + String.format("%04d", WS_B) + SUBTRACT + String.format("%04d", WS_B) + FROM + String.format("%04d", WS_A) + GIVING + String.format("%04d", WS_RESULT));
        System.out.println("SUBTRACT B FROM A GIVING RESULT=" + String.format("%04d", WS_RESULT) + SUBTRACT + FROM + String.format("%04d", WS_A));
        System.out.println("SUBTRACT 10 FROM A (in-place) A=" + String.format("%04d", WS_A) + SUBTRACT + String.format("%04d", WS_B) + FROM + String.format("%04d", WS_TEMP) + GIVING + String.format("%04d", WS_RESULT));
        System.out.println("SUBTRACT B FROM TEMP GIVING RESULT=" + String.format("%04d", WS_RESULT) + SUBTRACT + String.format("%04d", WS_A) + String.format("%04d", WS_B) + FROM + GIVING + String.format("%04d", WS_RESULT));
        System.out.println("SUBTRACT A B FROM 200 GIVING RESULT=" + String.format("%04d", WS_RESULT));
        return;

    }
}
