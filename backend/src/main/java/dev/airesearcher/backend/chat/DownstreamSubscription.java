package dev.airesearcher.backend.chat;

import reactor.core.Disposable;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

final class DownstreamSubscription {

    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final AtomicReference<Disposable> subscription = new AtomicReference<>();

    void set(Disposable disposable) {
        if (!subscription.compareAndSet(null, disposable)) {
            disposable.dispose();
            throw new IllegalStateException("Downstream subscription already set");
        }
        if (cancelled.get()) {
            disposable.dispose();
        }
    }

    void cancel() {
        if (cancelled.compareAndSet(false, true)) {
            Disposable disposable = subscription.get();
            if (disposable != null) {
                disposable.dispose();
            }
        }
    }

    boolean isCancelled() {
        return cancelled.get();
    }
}
