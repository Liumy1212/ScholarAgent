package dev.airesearcher.backend.integration.agent;

import org.springframework.http.HttpHeaders;

import java.io.InputStream;

public record AgentFileResponse(int statusCode, HttpHeaders headers, InputStream body) {
}
