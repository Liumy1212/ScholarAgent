package dev.airesearcher.backend.conversation;

public record ConversationToolCall(String toolCallId, String toolName, String status, String errorCode) {
}
