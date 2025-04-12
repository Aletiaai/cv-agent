#core/information_extractor.py
import os
import json
import fitz
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from api_integration.gemini_api import GeminiAPI
from data.data_handler import load_prompt

gemini_api = GeminiAPI()
    
PROMPTS = {}

prompt_files = {
    "user_extract_all_sections": "user_all_sections_extraction_v2.txt"
}

# Load each prompt with error checking
for key, filename in prompt_files.items():
    prompt_content = load_prompt(filename)
    if prompt_content is not None:
        PROMPTS[key] = prompt_content
    else:
        print(f"Warning: Failed to load prompt for {key}")

def get_resume_text_from_pdf(pdf_path): # Extracts text from the specified PDF file. Args: pdf_path: Path to the PDF file. Returns: The extracted text as a single string, or None if an error occurred.
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return None
    
class RateLimitException(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(RateLimitException)
)

def retry_generate_content(prompt):
    try:
        response = gemini_api.generate_content(prompt)
        if not response:
            raise RateLimitException("Empty response from Gemini API")
        return response
    except Exception as e:
        if "429" in str(e) or "Resource has been exhausted" in str(e):
            print("Rate limit hit, waiting before retry...")
            raise RateLimitException(str(e))
        raise
    
def extract_information(resume_data, resume_txt, section_key, prompt_key):
    try:
        # Ensure prompt_key exists in PROMPTS dictionary
        if prompt_key not in PROMPTS:
            print(f"Error: {prompt_key} not found in PROMPTS dictionary")
            return None

        # Get the prompt template and format it with the resume text
        prompt_template = PROMPTS[prompt_key]
        prompt = prompt_template.format(resume_data=resume_txt)

        # Use retry mechanism for API call
        try:
            response = retry_generate_content(prompt)
        except RateLimitException as e:
            print(f"Failed to generate content after retries: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error during content generation: {e}")
            return None
                
        # Convert response to string and clean it
        response_text = str(response).strip()
        
        try:
            # Remove any leading/trailing whitespace and newlines
            response_text = response_text.strip()
            
            # If the response is wrapped in markdown code blocks, extract the JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            # Parse the JSON
            parsed_response = json.loads(response_text)
            resume_data[section_key] = parsed_response
            
            return parsed_response
            
        except json.JSONDecodeError as json_err:
            print(f"\nJSON parsing error: {str(json_err)}")
            print("Response text that failed to parse:")
            print(response_text)
            return None
            
    except Exception as e:
        print(f"Error extracting {section_key}: {str(e)}")
        print("Full error:")
        import traceback
        print(traceback.format_exc())
        return None