import java.io.PrintStream;

public class Main {
    static String WS_PROG_NAME = "CALC";
    static int WS_INPUT_A = 10;
    static int WS_INPUT_B = 5;
    static int WS_RESULT = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("MAIN STARTED");
        System.out.println("CALLING PROGRAM: " + WS_PROG_NAME);
        Ws_Prog_Name.MAIN_LOGIC(WS_INPUT_A, WS_INPUT_B, WS_RESULT);
        System.out.println("RESULT=" + String.format("%06d", WS_RESULT));
        return;

    }
}
