"""
WhatsApp chat parser tool
Modified version of the provided parsing code to work with text content
and return data suitable for table display
"""

import re
from typing import List, Dict

def parse_chat_content(text_content: str) -> List[Dict[str, str]]:
    """
    Parse WhatsApp chat text content and return structured data
    
    Args:
        text_content: Raw WhatsApp chat text content
        
    Returns:
        List of dictionaries containing parsed message data
    """
    # Regex pattern to capture WhatsApp messages
    # Supports format: DD/MM/YYYY, HH:MM - Sender: Message
    pattern = re.compile(r"^(\d{2}/\d{2}/\d{4}), (\d{2}:\d{2}) - ([^:]+?): (.*)$")
    
    messages = []
    lines = text_content.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:  # Skip empty lines
            continue
            
        match = pattern.match(line)
        if match:
            date, time, sender, message = match.groups()
            messages.append({
                "Date": date,
                "Time": time,
                # "Date-Time": f"{date} {time}",
                "Phone/Name": sender.strip(),
                "Message": message.strip()
            })
        else:
            # Handle continuation of multiline messages
            if messages:
                messages[-1]["Message"] += " " + line
    
    return messages

def parse_chat_file(filename: str) -> List[Dict[str, str]]:
    """
    Parse WhatsApp chat from file (for testing purposes)
    
    Args:
        filename: Path to the chat file
        
    Returns:
        List of dictionaries containing parsed message data
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        return parse_chat_content(content)
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

def get_chat_statistics(messages: List[Dict[str, str]]) -> Dict[str, any]:
    """
    Get basic statistics from parsed chat data
    
    Args:
        messages: List of parsed message dictionaries
        
    Returns:
        Dictionary containing chat statistics
    """
    if not messages:
        return {
            "total_messages": 0,
            "unique_senders": 0,
            "date_range": None,
            "senders": []
        }
    
    # Get unique senders
    senders = list(set(msg["Phone/Name"] for msg in messages))
    
    # Get date range
    dates = [msg["Date"] for msg in messages]
    date_range = f"{min(dates)} to {max(dates)}" if dates else None
    
    return {
        "total_messages": len(messages),
        "unique_senders": len(senders),
        "date_range": date_range,
        "senders": senders
    }

# Test function (can be removed in production)
if __name__ == "__main__":
    # Sample WhatsApp chat content for testing
    sample_content = """25/12/2023, 10:30 - John Doe: Hi, I want to order something
25/12/2023, 10:31 - Store Admin: Sure! What would you like to order?
25/12/2023, 10:32 - John Doe: I need 2 iPhone 15
Can you help me with that?
25/12/2023, 10:33 - Jane Smith: I also want to place an order
25/12/2023, 10:34 - Jane Smith: 1 MacBook Pro please"""
    
    parsed_data = parse_chat_content(sample_content)
    stats = get_chat_statistics(parsed_data)
    
    print("Parsed Messages:")
    for i, msg in enumerate(parsed_data, 1):
        print(f"{i}. {msg}")
    
    print(f"\nStatistics: {stats}")