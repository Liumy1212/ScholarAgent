from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content: Annotated[str, StringConstraints(min_length=1)]
    paper_ids: list[Identifier] = Field(alias="paperIds")

    @field_validator("paper_ids")
    @classmethod
    def paper_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("paperIds must contain unique items")
        return value
