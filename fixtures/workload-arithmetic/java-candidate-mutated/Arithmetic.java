public class Arithmetic {
    public static void main(String[] args) {
        int a = 10;
        int b = 5;
        int sum = a + b;
        int diff = a - b;
        int prod = a * b;
        int quot = a / b;
        int rem = a % b;

        System.out.println("SUM=" + String.format("%04d", sum));
        System.out.println("DIFF=" + String.format("%04d", diff + 1));
        System.out.println("PROD=" + String.format("%08d", prod));
        System.out.println("QUOT=" + String.format("%04d", quot));
        System.out.println("REM=" + String.format("%04d", rem));

        if (a > b) {
            System.out.println("A_GT_B=TRUE");
        } else {
            System.out.println("A_GT_B=FALSE");
        }

        if (a == b) {
            System.out.println("A_EQ_B=TRUE");
        } else {
            System.out.println("A_EQ_B=FALSE");
        }

        if (a < b) {
            System.out.println("A_LT_B=TRUE");
        } else {
            System.out.println("A_LT_B=FALSE");
        }
    }
}
