public class RuntimeFail {
    public static void main(String[] args) {
        System.out.println("RUNTIME_FAIL_START");
        int[] arr = new int[1];
        arr[1] = 42;
    }
}
