import java.io.PrintStream;

public class Redefines_Demo {
    static String WS_RECORD = "";

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("REDEFINES DEMO STARTED");
        System.out.println("WS-NUMERIC=" + WS_NUMERIC);
        System.out.println("WS-PART1=" + WS_PART1);
        System.out.println("WS-PART2=" + WS_PART2);
        System.out.println("WS-CHAR=" + WS_CHAR);
        WS_CHAR = "ABCDEF";
        System.out.println("AFTER MOVE CHARS:");
        System.out.println("WS-NUMERIC=" + WS_NUMERIC);
        System.out.println("WS-PART1=" + WS_PART1);
        System.out.println("WS-PART2=" + WS_PART2);
        System.out.println("WS-CHAR=" + WS_CHAR);
        return;

    }
}
