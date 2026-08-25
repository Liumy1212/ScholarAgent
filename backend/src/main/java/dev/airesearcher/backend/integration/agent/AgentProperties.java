package dev.airesearcher.backend.integration.agent;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.net.URI;
import java.time.Duration;

@ConfigurationProperties("airesearcher.agent")
public record AgentProperties(URI baseUrl, Duration connectTimeout, Duration openTimeout) {
}
