import java.io.PrintStream;

public class Copybook_Demo {
    static int WS_RESULT = 0;
    static int WS_COUNTER = 0;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("COPYBOOK DEMO STARTED");
        CLAIM_AMOUNT = 100;
        CLAIM_ID = "C-999";
        System.out.println("INITIAL CLAIM-ID=" + CLAIM_ID);
        System.out.println("INITIAL CLAIM-AMOUNT=" + CLAIM_AMOUNT);
        WS_RESULT = CLAIM_AMOUNT;
        System.out.println("WS-RESULT=" + String.format("%08d", WS_RESULT));
        if (CLAIM_AMOUNT > 500) {
    System.out.println("AMOUNT GT 500");
} else {
    System.out.println("AMOUNT LE 500");
}
        System.out.println("FINAL CLAIM-ID=" + CLAIM_ID);
        System.out.println("FINAL CLAIM-AMOUNT=" + CLAIM_AMOUNT);
        return;

    }
}
