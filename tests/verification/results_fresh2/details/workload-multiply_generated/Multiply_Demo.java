import java.io.PrintStream;

public class Multiply_Demo {
    static int WS_A = 10;
    static int WS_B = 5;
    static int WS_RESULT = 0;
    static int WS_TEMP = 3;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("MULTIPLY DEMO STARTED");
        System.out.println("WS-A=" + String.format("%04d", WS_A));
        System.out.println("WS-B=" + String.format("%04d", WS_B) + MULTIPLY + String.format("%04d", WS_A) + BY + String.format("%04d", WS_B) + GIVING + String.format("%08d", WS_RESULT));
        System.out.println("MULTIPLY A BY B GIVING RESULT=" + String.format("%08d", WS_RESULT) + MULTIPLY + BY + String.format("%04d", WS_A));
        System.out.println("MULTIPLY 4 BY A (in-place) A=" + String.format("%04d", WS_A) + MULTIPLY + String.format("%04d", WS_B) + BY + String.format("%04d", WS_TEMP) + GIVING + String.format("%08d", WS_RESULT));
        System.out.println("MULTIPLY B BY TEMP GIVING RESULT=" + String.format("%08d", WS_RESULT) + MULTIPLY + String.format("%04d", WS_A) + BY + String.format("%04d", WS_B) + GIVING + String.format("%08d", WS_RESULT));
        System.out.println("MULTIPLY A BY B GIVING RESULT=" + String.format("%08d", WS_RESULT));
        return;

    }
}
