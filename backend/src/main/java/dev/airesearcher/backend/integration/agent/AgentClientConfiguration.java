package dev.airesearcher.backend.integration.agent;

import io.netty.channel.ChannelOption;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

@Configuration(proxyBeanMethods = false)
public class AgentClientConfiguration {

    @Bean
    WebClient agentWebClient(WebClient.Builder builder, AgentProperties properties) {
        int connectTimeoutMillis = Math.toIntExact(properties.connectTimeout().toMillis());
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, connectTimeoutMillis);
        return builder
                .baseUrl(properties.baseUrl().toString())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }

    @Bean("agentFileHttpClient")
    java.net.http.HttpClient agentFileHttpClient(AgentProperties properties) {
        Duration connectTimeout = properties.connectTimeout();
        return java.net.http.HttpClient.newBuilder()
                .connectTimeout(connectTimeout)
                .followRedirects(java.net.http.HttpClient.Redirect.NEVER)
                .build();
    }
}
