import java.net.Socket;
import java.net.URL;
import java.net.HttpURLConnection;

public class NetworkTest {
    public static void main(String[] args) {
        try {
            Socket s = new Socket("8.8.8.8", 53);
            System.out.println("NETWORK_ACCESS_SUCCESS");
            s.close();
        } catch (Exception e) {
            System.out.println("NETWORK_ACCESS_BLOCKED:" + e.getClass().getSimpleName());
        }
    }
}
