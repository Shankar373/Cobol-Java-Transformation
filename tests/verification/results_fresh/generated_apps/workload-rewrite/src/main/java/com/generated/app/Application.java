package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.RewriteDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-rewrite-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final RewriteDemo rewriteDemo;

    public Application(
        RewriteDemo rewriteDemo
    ) {
        this.rewriteDemo = rewriteDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            rewriteDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
