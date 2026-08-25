package dev.airesearcher.backend.chat;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@ConfigurationProperties("airesearcher.sse")
public record SseProperties(Duration emitterTimeout) {
}
