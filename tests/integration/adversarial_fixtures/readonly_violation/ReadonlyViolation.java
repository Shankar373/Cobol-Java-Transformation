import java.io.File;
import java.io.FileWriter;
import java.io.IOException;

public class ReadonlyViolation {
    public static void main(String[] args) {
        System.out.println("READONLY_TEST_START");
        
        File sourceFile = new File("/workspace/source/README.txt");
        try {
            FileWriter fw = new FileWriter(sourceFile);
            fw.write("HACKED");
            fw.close();
            System.out.println("WRITE_SOURCE_SUCCESS");
        } catch (Exception e) {
            System.out.println("WRITE_SOURCE_FAILED:" + e.getClass().getSimpleName());
        }
        
        File workspaceFile = new File("/workspace/hack.txt");
        try {
            FileWriter fw = new FileWriter(workspaceFile);
            fw.write("writable_workspace");
            fw.close();
            System.out.println("WRITE_WORKSPACE_SUCCESS");
        } catch (Exception e) {
            System.out.println("WRITE_WORKSPACE_FAILED:" + e.getClass().getSimpleName());
        }
        
        System.out.println("READONLY_TEST_END");
    }
}
