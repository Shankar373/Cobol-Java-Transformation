package com.generated.app;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import com.generated.app.service.IndexedFileDemo;

/**
 * Spring Boot batch application entry point.
 * Application: workload-indexed-file-app
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class Application {

    private final IndexedFileDemo indexedFileDemo;

    public Application(
        IndexedFileDemo indexedFileDemo
    ) {
        this.indexedFileDemo = indexedFileDemo;
    }

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    public CommandLineRunner runner() {
        return args -> {
            indexedFileDemo.MAIN_LOGIC();
            System.exit(0);
        };
    }
}
