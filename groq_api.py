"""
Groq API Client for LLama models

This module provides a client for interacting with the Groq API to use LLama models.
"""
import os
import logging
import requests
import json
from typing import Dict, List, Optional, Union, Any

logger = logging.getLogger('groq_api')

class GroqClient:
    """Client for interacting with Groq API to access LLama models"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Groq client with API key"""
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("Groq API key must be provided or set as GROQ_API_KEY environment variable")
        
        self.base_url = "https://api.groq.com/openai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Create messages class-like structure to maintain compatibility with Anthropic
        self.messages = GroqMessages(self)
    
    def chat_completion(self, model: str, messages: List[Dict[str, str]], 
                       system: Optional[str] = None, max_tokens: int = 1000) -> Dict[str, Any]:
        """
        Generate a chat completion using Groq API
        
        Args:
            model: The model to use (e.g., "llama3-8b-8192")
            messages: List of message objects with role and content
            system: Optional system message to set the context
            max_tokens: Maximum number of tokens to generate
            
        Returns:
            Dict containing the response from the API
        """
        url = f"{self.base_url}/chat/completions"
        
        # Prepare the full messages list including system message if provided
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        
        payload = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling Groq API: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            raise

class GroqMessages:
    """Helper class to maintain compatibility with Anthropic's API structure"""
    
    def __init__(self, client):
        """Initialize with reference to the parent client"""
        self.client = client
    
    def create(self, model: str, system: Optional[str] = None, 
              messages: List[Dict[str, str]] = None, max_tokens: int = 1000) -> 'GroqResponse':
        """
        Create a chat completion with a structure similar to Anthropic
        
        Args:
            model: The model to use (e.g., "llama3-8b-8192")
            system: Optional system message
            messages: List of message objects with role and content
            max_tokens: Maximum number of tokens to generate
            
        Returns:
            GroqResponse object that mimics Anthropic response structure
        """
        if messages is None:
            messages = []
            
        response = self.client.chat_completion(
            model=model,
            messages=messages,
            system=system,
            max_tokens=max_tokens
        )
        
        return GroqResponse(response)

class GroqResponse:
    """Response object that mimics Anthropic's response structure"""
    
    def __init__(self, response_data: Dict[str, Any]):
        """Initialize with the raw response data"""
        self.id = response_data.get('id')
        self.model = response_data.get('model')
        self.content = [GroqContent(response_data['choices'][0]['message']['content'])]
        self.raw_response = response_data
    
class GroqContent:
    """Content object that mimics Anthropic's content structure"""
    
    def __init__(self, text: str):
        """Initialize with the text content"""
        self.text = text
        self.type = "text"
