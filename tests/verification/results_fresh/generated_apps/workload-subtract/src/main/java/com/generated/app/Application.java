package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.SubtractDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-subtract-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final SubtractDemo subtractDemo;

    public Application(
        SubtractDemo subtractDemo
    ) {
        this.subtractDemo = subtractDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            subtractDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
