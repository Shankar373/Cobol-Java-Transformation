import java.io.File;
import java.io.FileWriter;
import java.io.IOException;

public class WorkspaceWrite {
    public static void main(String[] args) {
        System.out.println("WORKSPACE_WRITE_START");
        
        File workspaceFile = new File("/workspace/output.txt");
        try {
            FileWriter fw = new FileWriter(workspaceFile);
            fw.write("writable_workspace");
            fw.close();
            System.out.println("WRITE_WORKSPACE_SUCCESS");
        } catch (Exception e) {
            System.out.println("WRITE_WORKSPACE_FAILED:" + e.getClass().getSimpleName());
        }
        
        System.out.println("WORKSPACE_WRITE_END");
    }
}
