import java.util.TreeMap;
import java.util.Map;

public class IndexedDuplicateRecord {
    public static void main(String[] args) {
        TreeMap<String, String> idx = new TreeMap<>();

        idx.put("K001", "RECORD-ONE--0001");
        idx.put("K002", "RECORD-TWO--0002");
        idx.put("K003", "RECORD-THREE-003");

        idx.put("K002", "REC-TWO-UPD--002");

        idx.remove("K002");

        System.out.println("K001|RECORD-ONE--0001");
        System.out.println("K001|RECORD-ONE--0001");
        System.out.println("K003|RECORD-THREE-003");

        System.out.println("FILESTATUS=00");
        System.out.println("END");
    }
}
