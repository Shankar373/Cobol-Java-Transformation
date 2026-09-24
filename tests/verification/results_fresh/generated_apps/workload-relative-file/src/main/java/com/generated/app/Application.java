package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.RelativeFileDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-relative-file-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final RelativeFileDemo relativeFileDemo;

    public Application(
        RelativeFileDemo relativeFileDemo
    ) {
        this.relativeFileDemo = relativeFileDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            relativeFileDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
