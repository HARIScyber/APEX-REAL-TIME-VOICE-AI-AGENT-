import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Sample mock enterprise database for demonstration
MOCK_KNOWLEDGE_BASE = [
    {
        "topic": "shipping_policy",
        "keywords": ["shipping", "delivery", "track", "courier", "arrive"],
        "answer": "Standard shipping takes 3 to 5 business days. Express shipping delivers within 24 to 48 hours. Orders over $50 include free standard shipping."
    },
    {
        "topic": "return_policy",
        "keywords": ["return", "refund", "exchange", "money back"],
        "answer": "Items can be returned within 30 days of receipt in their original condition and packaging. Refunds are processed to the original payment method within 3 business days."
    },
    {
        "topic": "support_hours",
        "keywords": ["hours", "open", "contact", "support", "time"],
        "answer": "Our live support team is available 24/7 via voice, chat, and email at support@apexenterprise.com."
    },
    {
        "topic": "warranty",
        "keywords": ["warranty", "repair", "defect", "broken", "guarantee"],
        "answer": "All hardware products carry a 1-year limited warranty covering manufacturing defects. Extended 3-year accidental coverage can be added within 30 days of purchase."
    }
]

MOCK_ORDERS = {
    "ORD-1001": {
        "customer": "Sarah Connor",
        "status": "Out for Delivery",
        "carrier": "FedEx",
        "estimated_arrival": "Today by 5:00 PM",
        "items": ["Ultra-Quiet Wireless ANC Headphones (Black)"]
    },
    "ORD-1002": {
        "customer": "John Doe",
        "status": "Shipped",
        "carrier": "UPS",
        "estimated_arrival": "Tomorrow afternoon",
        "items": ["Smart Ambient LED Desk Lamp", "USB-C Fast Charging Dock"]
    },
    "ORD-1003": {
        "customer": "Elena Rostova",
        "status": "Processing",
        "carrier": "DHL Express",
        "estimated_arrival": "In 2 business days",
        "items": ["Pro 4K HDR Webcam"]
    }
}


class ToolRegistry:
    """Registry of actionable tools that the Voice Agent can execute."""

    @staticmethod
    def search_knowledge_base(query: str) -> str:
        """RAG Knowledge Base Search."""
        logger.info(f"[Tool] search_knowledge_base called with query: '{query}'")
        q = query.lower()
        for doc in MOCK_KNOWLEDGE_BASE:
            if any(k in q for k in doc["keywords"]):
                return f"[Knowledge Base Result]: {doc['answer']}"
        return "No specific knowledge article matched. General policy applies: 30-day returns and 24/7 customer care."

    @staticmethod
    def lookup_order_status(order_id: str) -> str:
        """Database / SQL lookup for order status."""
        logger.info(f"[Tool] lookup_order_status called with ID: '{order_id}'")
        normalized_id = order_id.upper().strip()
        if normalized_id in MOCK_ORDERS:
            ord_info = MOCK_ORDERS[normalized_id]
            return (
                f"Order {normalized_id} for {ord_info['customer']} is currently '{ord_info['status']}'. "
                f"Carrier: {ord_info['carrier']}. Estimated arrival: {ord_info['estimated_arrival']}. "
                f"Items: {', '.join(ord_info['items'])}."
            )
        # Check if user passed just numbers
        for oid, ord_info in MOCK_ORDERS.items():
            if normalized_id in oid:
                return (
                    f"Found order {oid}: Status '{ord_info['status']}', carrier {ord_info['carrier']}, "
                    f"estimated arrival {ord_info['estimated_arrival']}."
                )
        return f"Order '{order_id}' was not found in our database. Please verify the 4-digit order number (e.g. ORD-1001)."

    @staticmethod
    def book_appointment(date: str, time: str, service: str) -> str:
        """Action tool: Schedule an appointment."""
        logger.info(f"[Tool] book_appointment: {service} on {date} at {time}")
        return f"Confirmation: Your appointment for '{service}' has been successfully scheduled for {date} at {time}. A confirmation SMS has been dispatched."

    @staticmethod
    def smart_device_control(device: str, action: str, value: str = "") -> str:
        """Smart Home / IoT Device Action."""
        logger.info(f"[Tool] smart_device_control: {action} on {device} ({value})")
        val_str = f" to {value}" if value else ""
        return f"Success: {device.title()} has been set to '{action}'{val_str}."

    @classmethod
    def get_definitions(cls) -> List[Dict[str, Any]]:
        """Return tool definitions schema in OpenAI / Gemini compatible function call format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "lookup_order_status",
                    "description": "Look up real-time status and delivery info of an order by order ID (e.g. ORD-1001).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string", "description": "The order ID or number"}
                        },
                        "required": ["order_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": "Search enterprise company knowledge, policies on returns, shipping, warranty, or company info.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query keywords"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Book or schedule an appointment or consultation service.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Date of appointment"},
                            "time": {"type": "string", "description": "Time of appointment"},
                            "service": {"type": "string", "description": "Type of service or consultation"}
                        },
                        "required": ["date", "time", "service"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "smart_device_control",
                    "description": "Control smart home devices such as lights, thermostat, or locks.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "device": {"type": "string", "description": "Device name, e.g. living room lights, thermostat"},
                            "action": {"type": "string", "description": "Action, e.g. turn on, turn off, set temperature"},
                            "value": {"type": "string", "description": "Optional value, e.g. 72 degrees, 50% brightness"}
                        },
                        "required": ["device", "action"]
                    }
                }
            }
        ]

    @classmethod
    def execute(cls, name: str, args: Dict[str, Any]) -> str:
        """Execute a tool by name with provided arguments."""
        try:
            if name == "lookup_order_status":
                return cls.lookup_order_status(args.get("order_id", ""))
            elif name == "search_knowledge_base":
                return cls.search_knowledge_base(args.get("query", ""))
            elif name == "book_appointment":
                return cls.book_appointment(args.get("date", ""), args.get("time", ""), args.get("service", ""))
            elif name == "smart_device_control":
                return cls.smart_device_control(args.get("device", ""), args.get("action", ""), args.get("value", ""))
            else:
                return f"Error: Unknown tool '{name}'."
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            return f"Error occurred while running {name}."

    @classmethod
    def execute_timed(cls, name: str, args: Dict[str, Any]):
        """Execute tool and return (result, latency_ms, is_rag)."""
        import time
        t0 = time.perf_counter()
        result = cls.execute(name, args)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        is_rag = (name == "search_knowledge_base")
        return result, latency_ms, is_rag
