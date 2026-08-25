package dev.airesearcher.backend.support;

import org.springframework.http.codec.ServerSentEvent;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

public final class ContractSseFixtures {

    private static final Path CONTRACT_ROOT = Path.of("..", "contracts", "sse", "v1");

    private ContractSseFixtures() {
    }

    public static String completedStreamText() throws IOException {
        return Files.readString(
                CONTRACT_ROOT.resolve("examples/streams/run-completed.sse"),
                StandardCharsets.UTF_8
        ).replace("\r\n", "\n");
    }

    public static String failedStreamText() throws IOException {
        return Files.readString(
                CONTRACT_ROOT.resolve("examples/streams/run-failed.sse"),
                StandardCharsets.UTF_8
        ).replace("\r\n", "\n");
    }

    public static String streamOpenErrorText() throws IOException {
        return Files.readString(
                CONTRACT_ROOT.resolve("examples/stream-open-error.json"),
                StandardCharsets.UTF_8
        );
    }

    public static List<ServerSentEvent<String>> completedEvents() throws IOException {
        return parse(completedStreamText());
    }

    public static List<ServerSentEvent<String>> failedEvents() throws IOException {
        return parse(failedStreamText());
    }

    public static List<ServerSentEvent<String>> parse(String stream) {
        List<ServerSentEvent<String>> events = new ArrayList<>();
        for (String block : stream.replace("\r\n", "\n").split("\n\n")) {
            if (block.isBlank()) {
                continue;
            }
            String eventName = null;
            String id = null;
            String comment = null;
            List<String> dataLines = new ArrayList<>();
            for (String line : block.split("\n")) {
                if (line.startsWith("event:")) {
                    eventName = value(line);
                } else if (line.startsWith("id:")) {
                    id = value(line);
                } else if (line.startsWith("data:")) {
                    dataLines.add(value(line));
                } else if (line.startsWith(":")) {
                    comment = line.substring(1).stripLeading();
                }
            }
            ServerSentEvent.Builder<String> builder = dataLines.isEmpty()
                    ? ServerSentEvent.builder()
                    : ServerSentEvent.builder(String.join("\n", dataLines));
            if (eventName != null) {
                builder.event(eventName);
            }
            if (id != null) {
                builder.id(id);
            }
            if (comment != null) {
                builder.comment(comment);
            }
            events.add(builder.build());
        }
        return List.copyOf(events);
    }

    private static String value(String line) {
        String value = line.substring(line.indexOf(':') + 1);
        return value.startsWith(" ") ? value.substring(1) : value;
    }
}
