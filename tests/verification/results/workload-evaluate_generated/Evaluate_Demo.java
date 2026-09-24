import java.io.PrintStream;

public class Evaluate_Demo {
    static int WS_GRADE = 85;
    static String WS_RESULT = "SPACES";

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("EVALUATE DEMO STARTED");
        System.out.println("GRADE=" + String.format("%02d", WS_GRADE) + EVALUATE + String.format("%02d", WS_GRADE) + WHEN + THRU);
        WS_RESULT = "A";
        WS_RESULT = "B";
        WS_RESULT = "C";
        WS_RESULT = "D";
        WS_RESULT = "F";
        System.out.println("LETTER GRADE=" + WS_RESULT + EVALUATE + TRUE + WHEN + String.format("%02d", WS_GRADE));
        System.out.println("EXCELLENT" + WHEN + String.format("%02d", WS_GRADE));
        System.out.println("GOOD" + WHEN + String.format("%02d", WS_GRADE));
        System.out.println("AVERAGE" + WHEN + String.format("%02d", WS_GRADE));
        System.out.println("BELOW AVERAGE" + WHEN + OTHER);
        System.out.println("FAILING");
        return;

    }
}
