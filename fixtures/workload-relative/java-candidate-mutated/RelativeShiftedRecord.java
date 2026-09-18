import java.util.TreeMap;
import java.util.Map;

public class RelativeShiftedRecord {
    public static void main(String[] args) {
        TreeMap<Integer, String> rel = new TreeMap<>();

        rel.put(1, "REL-RECORD-A----01");
        rel.put(2, "REL-RECORD-B----02");
        rel.put(3, "REL-RECORD-C----03");

        rel.put(2, "REL-REC-B-UPD--02");

        rel.clear();
        rel.put(2, "REL-RECORD-A----01");
        rel.put(3, "REL-REC-B-UPD--02");
        rel.put(4, "REL-RECORD-C----03");

        for (int rrn = 1; rrn <= 5; rrn++) {
            String data = rel.get(rrn);
            if (data != null) {
                String rrnStr = String.format("%04d", rrn);
                String padded = String.format("%-20s", data);
                System.out.println(rrnStr + "|" + padded);
            }
        }

        System.out.println("FILESTATUS=00");
        System.out.println("END");
    }
}
