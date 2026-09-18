import java.util.ArrayList;
import java.util.List;

public class MemoryPressure {
    public static void main(String[] args) {
        System.out.println("MEMORY_PRESSURE_START");
        List<byte[]> chunks = new ArrayList<>();
        int allocated = 0;
        try {
            while (true) {
                byte[] chunk = new byte[1024 * 1024];
                chunks.add(chunk);
                allocated += chunk.length;
                System.out.println("ALLOCATED_MB=" + (allocated / (1024 * 1024)));
            }
        } catch (OutOfMemoryError e) {
            System.out.println("OOM_CAUGHT:" + e.getMessage());
            System.out.println("TOTAL_ALLOCATED_MB=" + (allocated / (1024 * 1024)));
        }
        System.out.println("MEMORY_PRESSURE_END");
    }
}
