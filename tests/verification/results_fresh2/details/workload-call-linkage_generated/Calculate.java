import java.io.PrintStream;

public class Calculate {
    static int WS_TEMP = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("SUBROUTINE CALCULATE STARTED");
        System.out.println("INPUT A=" + LS_INPUT_A);
        System.out.println("INPUT B=" + LS_INPUT_B + COMPUTE + String.format("%06d", WS_TEMP) + LS_INPUT_A + LS_INPUT_B);
        LS_RESULT = WS_TEMP;
        System.out.println("SUBROUTINE RESULT=" + String.format("%06d", WS_TEMP) + GOBACK);

    }
}
