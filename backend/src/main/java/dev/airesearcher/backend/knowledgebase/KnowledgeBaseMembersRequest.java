package dev.airesearcher.backend.knowledgebase;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.hibernate.validator.constraints.UniqueElements;

import java.util.Collections;
import java.util.List;

public record KnowledgeBaseMembersRequest(
        @NotNull @Size(max = 100) @UniqueElements List<@NotEmpty @Size(max = 128) String> addPaperIds,
        @NotNull @Size(max = 100) @UniqueElements List<@NotEmpty @Size(max = 128) String> removePaperIds
) {
    public KnowledgeBaseMembersRequest {
        addPaperIds = addPaperIds == null ? null : List.copyOf(addPaperIds);
        removePaperIds = removePaperIds == null ? null : List.copyOf(removePaperIds);
    }

    @AssertTrue(message = "addPaperIds and removePaperIds must not overlap")
    public boolean isDisjoint() {
        return addPaperIds == null || removePaperIds == null
                || Collections.disjoint(addPaperIds, removePaperIds);
    }
}
