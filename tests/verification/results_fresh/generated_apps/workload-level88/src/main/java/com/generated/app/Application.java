package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.Level88Demo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-level88-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final Level88Demo level88Demo;

    public Application(
        Level88Demo level88Demo
    ) {
        this.level88Demo = level88Demo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            level88Demo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
