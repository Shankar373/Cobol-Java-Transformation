package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.EvaluateDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-evaluate-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final EvaluateDemo evaluateDemo;

    public Application(
        EvaluateDemo evaluateDemo
    ) {
        this.evaluateDemo = evaluateDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            evaluateDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
