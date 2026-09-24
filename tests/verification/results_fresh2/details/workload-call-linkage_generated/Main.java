import java.io.PrintStream;

public class Main {
    static int WS_INPUT_A = 10;
    static int WS_INPUT_B = 5;
    static int WS_RESULT = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("MAIN PROGRAM STARTED");
        System.out.println("INPUT A=" + String.format("%04d", WS_INPUT_A));
        System.out.println("INPUT B=" + String.format("%04d", WS_INPUT_B));
        Calculate.MAIN_LOGIC(WS_INPUT_A, WS_INPUT_B, WS_RESULT);
        System.out.println("RESULT FROM SUBROUTINE=" + String.format("%06d", WS_RESULT));
        return;

    }
}
