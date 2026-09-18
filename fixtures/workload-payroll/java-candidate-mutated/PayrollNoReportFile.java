import java.io.IOException;
import java.io.PrintWriter;
import java.util.Locale;

public class PayrollNoReportFile {
    public static void main(String[] args) throws IOException {
        String[] names = {"ALICE", "BOB", "CHARLIE", "DIANA", "EVE"};
        int[] bases = {10000, 15000, 12000, 18000, 11000};
        int[] years = {3, 7, 5, 10, 2};

        int totalPayroll = 0;
        int empCount = names.length;

        PrintWriter recWriter = new PrintWriter(
                new java.io.FileWriter("/workspace/output/records.dat"));

        for (int i = 0; i < empCount; i++) {
            int bonus = bases[i] * years[i] * 2 / 100;
            int total = bases[i] + bonus;
            totalPayroll += total;

            recWriter.printf(Locale.US,
                    "%s|%d|%02d|%05d|%06d%n",
                    names[i], bases[i], years[i], bonus, total);

            if (years[i] > 5) {
                System.err.printf(Locale.US,
                        "WARN:%-10s years=%02d%n", names[i], years[i]);
            }
        }

        int avgPay = totalPayroll / empCount;

        System.out.println("TOTAL_PAYROLL=" + String.format("%07d", totalPayroll));
        System.out.println("EMPLOYEE_COUNT=" + empCount);
        System.out.println("AVERAGE_PAY=" + String.format("%07d", avgPay));

        recWriter.close();
    }
}
