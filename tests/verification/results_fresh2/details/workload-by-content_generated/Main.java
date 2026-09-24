import java.io.PrintStream;

public class Main {
    static int WS_VALUE = PIC;

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.out.println("MAIN STARTED");
        System.out.println("BEFORE CALL VALUE=" + String.format("%04d", WS_VALUE));
        Modify.MAIN_LOGIC(WS_VALUE);
        System.out.println("AFTER CALL VALUE=" + String.format("%04d", WS_VALUE));
        return;

    }
}
