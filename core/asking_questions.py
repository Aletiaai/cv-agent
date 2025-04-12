# core/asking_questions.py

from api_integration.gemini_api import GeminiAPI
from data.data_handler import load_prompt, save_data
import json
from datetime import datetime

gemini_api = GeminiAPI()

def complementary_questions(resume_content, file_name):
    """Analyzes resume sections and ask clarifying questions in order to build an enhanced resume version
    Args:resume_content (dict): Dictionary containing parsed resume sections
    Returns:dict: Structured questions asking for information needed from each section to make an enhanced version
    """
    try:
        # Extract relevant information from the dictionary
        first_name = resume_content["extracted_sections"]["user_info"]["first_name"].title()
    except Exception as e:
        print(f"Error getting user's name: {e}")
        return {
            'error': str(e),
            'analysis_timestamp': datetime.now().isoformat()
        }
    try:

        # Structure the prompt to request a structured JSON response
        prompt_content = load_prompt("q_for_users_v1.txt")

        # Format the prompt with the user's data
        formatted_prompt = prompt_content.format(
            first_name = first_name.title(),
            Summary = resume_content["extracted_sections"]["summary"],
            Skills = resume_content["extracted_sections"]["skills"],
            Work_Experience = resume_content["extracted_sections"]["relevant_work_experience"],
            Education = resume_content["extracted_sections"]["education"],
            Languages = resume_content["extracted_sections"]["languages"],
        )
    except Exception as e:
        print(f"Error formatting the prompt: {e}")
        return {
            'error': str(e),
            'analysis_timestamp': datetime.now().isoformat()
        }
    try:
        # Get clarifying questions from Gemini - the response will be in JSON format
        questions_response = gemini_api.generate_content(formatted_prompt)
    except Exception as e:
        print(f"Error generating complementary questions: {e}")

    try:
        # Clean the response text and ensure it's proper JSON
        response_text = str(questions_response).strip()
        # Remove markdown code blocks if present
        response_text = response_text.strip("```json").strip("```")
        # Remove any leading/trailing whitespace and quotes
        response_text = response_text.strip('"\' \n\t')
        
        # Parse the JSON response
        questions_dict = json.loads(response_text)

        # Create the timestamp for the questions
        questions_time = {
            'questions_made_timestamp': datetime.now().isoformat()
        }
        if questions_response:
            resume_content.update(questions_dict)
            resume_content.update(questions_time)

            print("Added complementary questions to resume data.\n")
        # Save with original filename
        save_data(resume_content, file_name)
        
        return questions_dict
    
    except json.JSONDecodeError as json_err:
        print(f"JSON parsing error: {json_err}")
        print(f"Attempted to parse: {response_text}")
        return {
            'error_message': f"Failed to parse Gemini response as JSON: {str(json_err)}",
            'error_type': 'JSONDecodeError',
            'raw_response': response_text,
            'analysis_timestamp': datetime.now().isoformat()
        }
    