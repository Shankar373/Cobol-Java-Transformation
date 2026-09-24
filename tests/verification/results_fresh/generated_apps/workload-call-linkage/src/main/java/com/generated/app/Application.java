package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.Main;

/**
 * Spring Boot batch application entry point.
 * Application: workload-call-linkage-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final Main main;

    public Application(
        Main main
    ) {
        this.main = main;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            main.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
