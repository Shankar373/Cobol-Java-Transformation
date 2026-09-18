import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.Locale;

public class InventoryReversedOrder {
    public static void main(String[] args) throws IOException {
        String[] codes = {"ITEM006", "ITEM005", "ITEM004", "ITEM003", "ITEM002", "ITEM001"};
        String[] names = {"BOLT F    ", "PART E    ", "TOOL D    ", "GIZMO C   ", "GADGET B  ", "WIDGET A  "};
        int[] qtys = {5, 300, 10, 200, 50, 100};
        int[] prices = {9999, 350, 4500, 825, 1575, 2550};

        int totalValue = 0;
        int itemCount = codes.length;
        int reorderPoint = 20;

        PrintWriter rptWriter = new PrintWriter(
                new FileWriter("/workspace/output/report.txt"));
        PrintWriter recWriter = new PrintWriter(
                new FileWriter("/workspace/output/inventory.dat"));

        rptWriter.println("CODE    NAME       QTY  PRICE   VALUE");
        rptWriter.println();

        for (int i = 0; i < itemCount; i++) {
            int totalItem = qtys[i] * prices[i];
            totalValue += totalItem;

            rptWriter.printf(Locale.US,
                    "%s %s %04d %06d %08d%n",
                    codes[i], names[i], qtys[i], prices[i], totalItem);

            recWriter.printf(Locale.US,
                    "%s|%s|%04d|%06d|%08d%n",
                    codes[i], names[i], qtys[i], prices[i], totalItem);

            if (qtys[i] < reorderPoint) {
                System.err.printf(Locale.US,
                        "WARN:%s %s qty=%04d below reorder%n",
                        codes[i], names[i], qtys[i]);
            }
        }

        int avgValue = totalValue / itemCount;

        System.out.println("TOTAL_VALUE=" + String.format("%09d", totalValue));
        System.out.println("ITEM_COUNT=" + itemCount);
        System.out.println("AVERAGE_VALUE=" + String.format("%09d", avgValue));

        rptWriter.close();
        recWriter.close();
    }
}
