public class SlowExec {
    public static void main(String[] args) {
        System.out.println("SLOW_EXEC_START");
        System.out.flush();
        try {
            Thread.sleep(60000);
        } catch (InterruptedException e) {
            System.out.println("INTERRUPTED");
        }
        System.out.println("SLOW_EXEC_END");
    }
}
