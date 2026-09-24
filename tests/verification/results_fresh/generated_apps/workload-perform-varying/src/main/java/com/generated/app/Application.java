package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.PerformVaryingDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-perform-varying-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final PerformVaryingDemo performVaryingDemo;

    public Application(
        PerformVaryingDemo performVaryingDemo
    ) {
        this.performVaryingDemo = performVaryingDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            performVaryingDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
