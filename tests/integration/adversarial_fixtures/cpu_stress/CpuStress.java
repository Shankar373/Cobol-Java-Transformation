public class CpuStress {
    public static void main(String[] args) {
        System.out.println("CPU_STRESS_START");
        long iterations = 0;
        long startTime = System.currentTimeMillis();
        while (System.currentTimeMillis() - startTime < 10000) {
            double result = 0;
            for (int i = 1; i < 1000000; i++) {
                result += Math.sin(i) * Math.cos(i);
            }
            iterations++;
        }
        long elapsed = System.currentTimeMillis() - startTime;
        System.out.println("CPU_STRESS_END:iterations=" + iterations + ":elapsed_ms=" + elapsed);
    }
}
