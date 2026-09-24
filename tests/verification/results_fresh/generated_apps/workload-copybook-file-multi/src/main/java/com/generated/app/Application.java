package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.CopybookFileMulti;

/**
 * Spring Boot batch application entry point.
 * Application: workload-copybook-file-multi-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final CopybookFileMulti copybookFileMulti;

    public Application(
        CopybookFileMulti copybookFileMulti
    ) {
        this.copybookFileMulti = copybookFileMulti;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            copybookFileMulti.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
