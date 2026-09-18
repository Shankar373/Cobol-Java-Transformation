import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ClaimsDuplicateRecord {
    public static void main(String[] args) throws Exception {
        List<String[]> claims = readInput("/workspace/input/claims.dat");
        List<String[]> payments = readInput("/workspace/input/payments.dat");

        Map<String, Integer> paymentMap = new LinkedHashMap<>();
        for (String[] p : payments) {
            String claimId = p[1].trim();
            int amount = Integer.parseInt(p[3].trim());
            paymentMap.put(claimId, amount);
        }

        int totalClaims = 0;
        int approved = 0;
        int rejected = 0;
        int pending = 0;
        int paid = 0;
        int unpaid = 0;
        int totalClaimAmt = 0;
        int totalPayAmt = 0;

        PrintWriter rpt = new PrintWriter(new FileWriter("/workspace/output/report.txt"));
        PrintWriter stl = new PrintWriter(new FileWriter("/workspace/output/settlement.dat"));

        rpt.println("CLAIM   PATIENT      DATE     AMT ST CAT      SETTLEMENT");
        rpt.println();

        for (String[] c : claims) {
            totalClaims++;
            String claimId = c[0];
            String patient = c[1];
            String date = c[2];
            String amtStr = c[3];
            String status = c[4];
            String category = c[5];

            int amount = Integer.parseInt(amtStr.trim());
            totalClaimAmt += amount;

            String settlement;
            int payMatch = 0;

            if (status.equals("R")) {
                settlement = "REJECTED";
                rejected++;
            } else if (status.equals("P")) {
                settlement = "PENDING";
                pending++;
            } else if (amount < 500) {
                settlement = "REJECTED";
                rejected++;
            } else {
                settlement = "APPROVED";
                approved++;

                if (paymentMap.containsKey(claimId.trim())) {
                    payMatch = paymentMap.get(claimId.trim());
                    totalPayAmt += payMatch;

                    if (payMatch == amount) {
                        settlement = "PAID_IN_FULL";
                        paid++;
                    } else {
                        settlement = "PARTIAL";
                        paid++;
                    }
                } else {
                    settlement = "UNPAID";
                    unpaid++;
                }
            }

            rpt.printf("%s %s %s %s %s %s %s%n",
                    padRight(claimId, 4),
                    padRight(patient, 12),
                    padRight(date, 8),
                    padRight(amtStr, 5),
                    status,
                    padRight(category, 8),
                    settlement);

            stl.printf("%s|%s|%s|%s|%s|%s%n",
                    claimId,
                    padRight(patient, 12),
                    padRight(amtStr, 5),
                    padRight(category, 8),
                    padRight(settlement, 13),
                    String.format("%05d", payMatch));

            stl.printf("%s|%s|%s|%s|%s|%s%n",
                    claimId,
                    padRight(patient, 12),
                    padRight(amtStr, 5),
                    padRight(category, 8),
                    padRight(settlement, 13),
                    String.format("%05d", payMatch));

            if (settlement.equals("REJECTED")) {
                System.err.printf("REJECT:%s %s reason=%s%n",
                        claimId,
                        padRight(patient, 12),
                        status);
            }
            if (amount < 500 && status.equals("A")) {
                System.err.printf("LOW_AMOUNT:%s %s amt=%s%n",
                        claimId,
                        padRight(patient, 12),
                        padRight(amtStr, 5));
            }
        }

        System.out.println("TOTAL_CLAIMS=" + String.format("%02d", totalClaims));
        System.out.println("APPROVED=" + String.format("%02d", approved));
        System.out.println("REJECTED=" + String.format("%02d", rejected));
        System.out.println("PENDING=" + String.format("%02d", pending));
        System.out.println("PAID=" + String.format("%02d", paid));
        System.out.println("UNPAID=" + String.format("%02d", unpaid));
        System.out.println("TOTAL_CLAIM_AMT=" + String.format("%06d", totalClaimAmt));
        System.out.println("TOTAL_PAY_AMT=" + String.format("%06d", totalPayAmt));

        rpt.close();
        stl.close();
    }

    static List<String[]> readInput(String path) throws Exception {
        List<String[]> rows = new ArrayList<>();
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) {
            if (!line.trim().isEmpty()) {
                rows.add(line.split("\\|", -1));
            }
        }
        br.close();
        return rows;
    }

    static String padRight(String s, int n) {
        if (s == null) {
            s = "";
        }
        if (s.length() >= n) {
            return s.substring(0, n);
        }
        StringBuilder sb = new StringBuilder(s);
        while (sb.length() < n) {
            sb.append(' ');
        }
        return sb.toString();
    }
}
