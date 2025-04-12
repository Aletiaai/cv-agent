#api_integration/gemini_api.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

class GeminiAPI:
    def __init__(self):
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')  # Or your preferred model

    def generate_content(self, prompt):
        """Generates content using the Gemini API based on the given prompt.
        Args:
            prompt: The text prompt to send to the Gemini API.
            Returns: The generated text response from the Gemini API."""
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating content: {e}")  # Log the error
            return None
