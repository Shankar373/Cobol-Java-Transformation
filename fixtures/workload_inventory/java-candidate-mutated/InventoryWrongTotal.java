import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.Locale;

public class InventoryWrongTotal {
    public static void main(String[] args) throws IOException {
        String[] codes = {"ITEM001", "ITEM002", "ITEM003", "ITEM004", "ITEM005", "ITEM006"};
        String[] names = {"WIDGET A  ", "GADGET B  ", "GIZMO C   ", "TOOL D    ", "PART E    ", "BOLT F    "};
        int[] qtys = {100, 50, 200, 10, 300, 5};
        int[] prices = {2550, 1575, 825, 4500, 350, 9999};

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
            if (i == 2) totalItem = totalItem + 1;
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
