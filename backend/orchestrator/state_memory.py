import time
from typing import List, Dict, Any, Optional


class StateMemory:
    """
    Manages short-term conversation history and long-term user preferences/attributes.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        # Short-term chat history for prompt context
        self.chat_history: List[Dict[str, str]] = []
        # Long-term user preferences / entity slots
        self.user_preferences: Dict[str, Any] = {
            "name": "Alex",
            "tier": "Premium VIP",
            "language": "en",
            "preferred_contact": "voice"
        }
        # Ephemeral turn state
        self.active_turn_id: int = 0
        self.is_assistant_speaking: bool = False

    def add_message(
        self, role: str, content: str, turn_id: Optional[str] = None, source: Optional[str] = None
    ):
        """Append message to chat history with maximum context window retention."""
        self.chat_history.append(
            {"role": role, "content": content, "turn_id": turn_id, "source": source, "timestamp": time.time()}
        )
        if len(self.chat_history) > 12:
            self.chat_history = self.chat_history[-12:]

    def get_messages_for_llm(self, system_prompt: str) -> List[Dict[str, str]]:
        """Format the system prompt and conversation messages for the LLM."""
        formatted = [{"role": "system", "content": system_prompt}]
        formatted.extend({"role": item["role"], "content": item["content"]} for item in self.chat_history)
        return formatted

    def update_preference(self, key: str, value: Any):
        """Save a user preference or slot value."""
        self.user_preferences[key] = value

    def clear_history(self):
        """Reset short-term conversation context."""
        self.chat_history.clear()
