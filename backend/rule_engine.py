"""
LLM-powered regulation parser.

Takes regulation text from the Excel file and uses GPT to parse it into
structured constraint definitions that the CP-SAT solver can enforce.
"""
import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ParsedRule:
    """A regulation parsed into a structured constraint definition."""
    original_text: str
    type: str  # e.g., "max_consecutive_work_days", "no_shift_jumping"
    params: Dict[str, Any] = field(default_factory=dict)
    enforceable: bool = True
    reason: str = ""  # Why it's not enforceable, if applicable


# Supported constraint types and their descriptions (used in GPT prompt)
SUPPORTED_TYPES = {
    "max_consecutive_work_days": {
        "description": "Limit the maximum number of consecutive working days",
        "params": {"limit": "integer, the max consecutive working days allowed"},
        "example": "Max 6 consecutive working days"
    },
    "max_consecutive_off_days": {
        "description": "Limit the maximum number of consecutive off/rest days",
        "params": {"limit": "integer, the max consecutive off days allowed"},
        "example": "Max 2 consecutive days off"
    },
    "no_shift_jumping": {
        "description": "Prevent agents from jumping between different shift types without an OFF day in between (e.g., morning to night shift directly)",
        "params": {},
        "example": "Avoid shift jumping / consistent shift patterns"
    },
    "gender_shift_restriction": {
        "description": "Restrict certain shifts based on agent gender",
        "params": {
            "gender": "string, 'F' for female or 'M' for male",
            "shift_period": "string, 'night', 'morning', or 'evening'"
        },
        "example": "No night shifts for female agents"
    },
    "max_shifts_per_week": {
        "description": "Limit how many times a specific shift type can be assigned per week",
        "params": {
            "shift_period": "string, 'night', 'morning', or 'evening'",
            "limit": "integer, max count per week"
        },
        "example": "Max 3 night shifts per week"
    },
    "min_off_days_per_week": {
        "description": "Ensure a minimum number of off days per week",
        "params": {"limit": "integer, minimum off days per week"},
        "example": "At least 1 day off per week"
    }
}


def _build_system_prompt() -> str:
    """Build the system prompt for GPT with supported constraint types."""
    types_desc = json.dumps(SUPPORTED_TYPES, indent=2)
    return f"""You are a workforce management regulation parser. Your job is to analyze 
regulation text and map each one to a structured constraint type.

Here are the supported constraint types:
{types_desc}

For each regulation text, return a JSON array where each item has:
- "original_text": the exact regulation text
- "type": one of the supported type keys listed above
- "params": the parameters for that type (as specified above)
- "enforceable": true if you can map it to a supported type, false otherwise
- "reason": if not enforceable, explain why briefly

IMPORTANT RULES:
1. Extract numeric values from the text (e.g., "Max 6 consecutive" → limit: 6)
2. If a regulation is vague or doesn't match any type, set enforceable to false
3. One regulation text may map to one constraint type
4. Return ONLY valid JSON, no markdown or explanation
5. Be precise with parameter values — use exact types (integers for limits, strings for categories)"""


def parse_regulations_with_llm(regulations: List[str]) -> List[ParsedRule]:
    """
    Parse regulation texts using GPT API.
    
    Falls back to default rules if API key is missing or call fails.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    
    if not api_key or api_key == "sk-your-key-here":
        print("No OpenAI API key found, using default hardcoded rules")
        return _get_default_rules()
    
    if not regulations:
        print("No regulations provided, using defaults")
        return _get_default_rules()
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        user_message = "Parse these regulations into constraint definitions:\n\n"
        for i, reg in enumerate(regulations, 1):
            user_message += f"{i}. {reg}\n"
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": user_message}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content
        result_data = json.loads(result_text)
        
        # Handle both {"rules": [...]} and direct [...] formats
        if isinstance(result_data, dict):
            rules_list = result_data.get("rules", result_data.get("regulations", []))
        elif isinstance(result_data, list):
            rules_list = result_data
        else:
            print(f"Unexpected GPT response format: {type(result_data)}")
            return _get_default_rules()
        
        parsed_rules = []
        for rule_data in rules_list:
            parsed_rules.append(ParsedRule(
                original_text=rule_data.get("original_text", ""),
                type=rule_data.get("type", "unknown"),
                params=rule_data.get("params", {}),
                enforceable=rule_data.get("enforceable", False),
                reason=rule_data.get("reason", "")
            ))
        
        if not parsed_rules:
            print("GPT returned no rules, using defaults")
            return _get_default_rules()
        
        print(f"GPT parsed {len(parsed_rules)} regulations: "
              f"{sum(1 for r in parsed_rules if r.enforceable)} enforceable, "
              f"{sum(1 for r in parsed_rules if not r.enforceable)} display-only")
        
        return parsed_rules
        
    except Exception as e:
        print(f"GPT regulation parsing failed: {e}")
        print("Falling back to default hardcoded rules")
        return _get_default_rules()


def _get_default_rules() -> List[ParsedRule]:
    """Return the 4 default hardcoded rules as ParsedRule objects."""
    return [
        ParsedRule(
            original_text="Maximum 6 consecutive working days",
            type="max_consecutive_work_days",
            params={"limit": 6},
            enforceable=True
        ),
        ParsedRule(
            original_text="Consistent shift patterns (avoid shift jumping)",
            type="no_shift_jumping",
            params={},
            enforceable=True
        ),
        ParsedRule(
            original_text="Maximum 2 consecutive off days",
            type="max_consecutive_off_days",
            params={"limit": 2},
            enforceable=True
        ),
        ParsedRule(
            original_text="No night shifts for female agents",
            type="gender_shift_restriction",
            params={"gender": "F", "shift_period": "night"},
            enforceable=True
        ),
    ]


def rules_to_json(rules: List[ParsedRule]) -> List[Dict]:
    """Convert parsed rules to JSON-serializable format for the API response."""
    return [
        {
            "original_text": r.original_text,
            "type": r.type,
            "params": r.params,
            "enforceable": r.enforceable,
            "reason": r.reason
        }
        for r in rules
    ]
