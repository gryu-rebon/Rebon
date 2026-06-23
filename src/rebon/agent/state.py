from typing import Annotated
from langgraph.graph.message import add_messages
from pydantic import BaseModel


class UserProfile(BaseModel):
    conditions: list[str] = []
    goals: list[str] = []
    restrictions: list[str] = []
    age: int | None = None
    notes: str = ""


class AgentState(BaseModel):
    messages: Annotated[list, add_messages] = []
    user_profile: UserProfile = UserProfile()
    recommendations: list[dict] = []
