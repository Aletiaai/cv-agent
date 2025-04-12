#data/data_handler.py
import json
import re
import os
import ast

import pandas as pd
import fitz  # PyMuPDF
import uuid
import hashlib
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass
from datetime import datetime


from api_integration.gemini_api import GeminiAPI

DATA_DIR = "data/resumes"
DATA_FILE = "data/resume_data.json"
PROMPTS_DIR = "prompts"
gemini_api = GeminiAPI()

def ensure_data_directory():
    """Ensures the data directory exists"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def generate_filename(resume_name):
    """Generates a unique filename for each resume"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Clean the resume name to create a valid filename
    clean_name = "".join(c for c in resume_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    return f"{clean_name}_{timestamp}.json"

def load_data():
    """Returns an empty dictionary for a new resume"""
    return {}

def save_data_2(data, original_filename=None):
    """Saves resume data to a unique file"""
    ensure_data_directory()
    
    # Generate a filename based on the original PDF name if available
    if original_filename:
        base_name = os.path.splitext(os.path.basename(original_filename))[0]
    else:
        base_name = "resume"
    
    filename = os.path.join(DATA_DIR, generate_filename(base_name))
    
    try:
        with open(filename, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data, filename
    except Exception as e:
        print(f"Error saving resume data: {str(e)}")
        return None, None
    
def save_data(data, original_filename=None):
    """Saves resume data to a unique file with a name based on first name, last name, and CandidateID."""
    ensure_data_directory()

    # Extract user information for the file name
    user_info = data.get("extracted_sections", {}).get("user_info", {})
    first_name = user_info.get("first_name", "Unknown").replace(" ", "_").title()
    last_name = user_info.get("last_name", "Unknown").replace(" ", "_").title()
    candidate_id = data.get("CandidateID", "UnknownID").replace(" ", "_")
    
    # Generate the file name based on user information
    if first_name != "Unknown" and last_name != "Unknown" and candidate_id != "UnknownID":
        base_name = f"{first_name}_{last_name}_{candidate_id}"
    elif original_filename:
        base_name = os.path.splitext(os.path.basename(original_filename))[0]
    else:
        base_name = "resume"

    # Construct the full file path
    filename = os.path.join(DATA_DIR, f"{base_name}.json")

    try:
        with open(filename, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data, filename
    except Exception as e:
        print(f"Error saving resume data: {str(e)}")
        return None, None    
    
def load_prompt(filename):
    """Loads a prompt from a file in the prompts directory"""
    try:
        with open(os.path.join(PROMPTS_DIR, filename), "r", encoding='utf-8') as f:
            return f.read().strip() # Added strip() to remove any trailing whitespace
    except Exception as e:
        print(f"Error loading prompt file {filename}: {str(e)}")
        return None

def format_feedback_content(feedback_dict):
    """Formats the feedback dictionary into a readable email body text."""
    email_content = []
    
    # Add email intro
    email_content.append(feedback_dict['email_intro'])
    email_content.append("\n")
    
    # Add each section's feedback
    for section, content in feedback_dict['sections'].items():
         # Section header
        email_content.append(f" {section.replace('_', ' ').title()} \n")
        
        # Add feedback
        email_content.append("Retroalimentación:")
        # Clean up the feedback text by removing markdown if present
        feedback_text = content['feedback']
        feedback_text = feedback_text.replace('**', '').replace('*', '•')
        email_content.append(feedback_text)
        email_content.append("\n")

        # Add example
        email_content.append("Ejemplo:")
        # If example is a dictionary or list, format it for readability
        example = content['example']
        if isinstance(example, (dict, list)) or str(example).strip().startswith('{') or str(example).strip().startswith('['):
            # Convert string representation of dict/list to actual object if needed
            if isinstance(example, str):
                try:
                    import ast
                    example = ast.literal_eval(example)
                except:
                    pass
            if isinstance(example, (dict, list)):
                # Format dictionaries and lists in a readable way
                formatted_example = format_structured_data(example)
            else:
                formatted_example = example
        else:
            formatted_example = example
            
        email_content.append(formatted_example)
        email_content.append("\n")

    # Add closing message
    email_content.append(feedback_dict['closing'])
    
    # Join all parts with proper spacing
    return "\n".join(email_content)

def format_structured_data(data, indent=0):
    """Helper function to format dictionaries and lists in a readable way."""
    if isinstance(data, dict):
        formatted = []
        for key, value in data.items():
            key_str = key.replace('_', ' ').title()
            if isinstance(value, (dict, list)):
                formatted.append(f"{'  ' * indent}{key_str}:")
                formatted.append(format_structured_data(value, indent + 1))
            else:
                formatted.append(f"{'  ' * indent}{key_str}: {value}")
        return '\n'.join(formatted)
    elif isinstance(data, list):
        formatted = []
        for item in data:
            if isinstance(item, (dict, list)):
                formatted.append(format_structured_data(item, indent + 1))
            else:
                formatted.append(f"{'  ' * indent}• {item}")
        return '\n'.join(formatted)
    else:
        return str(data)
    
def format_feedback_content_API_call(feedback):
    """Helper function to extract the feedback from the json or dictionary and set it into a easy to read email with an API call"""
    try:
        feedback_email_format = ""
        prompt_content = load_prompt("email_format_generator_v1.txt")
        formatted_prompt = prompt_content.format(json_api_response = feedback)

        feedback_email_format = gemini_api.generate_content(formatted_prompt)
        return feedback_email_format
    except Exception as e:
        print(f"An error ocurred when formating the responso into an email body: {e}")
        return None
    
def format_work_experience(work_experience_str):
    try:
        # If it's already a list, format it
        if isinstance(work_experience_str, list):
            return format_work_experience_list(work_experience_str)
        
        # If it's a string, try to parse it
        if isinstance(work_experience_str, str):
            # Clean up the string first
            cleaned_str = work_experience_str.strip()
            if cleaned_str.startswith("[") and cleaned_str.endswith("]"):
                try:
                    # Try using json.loads first with some preprocessing
                    # Replace single quotes with double quotes for JSON compatibility
                    json_str = cleaned_str.replace("'", '"')
                    work_experience = json.loads(json_str)
                    return format_work_experience_list(work_experience)
                except json.JSONDecodeError:
                    try:
                        # If JSON parsing fails, try ast.literal_eval
                        work_experience = ast.literal_eval(cleaned_str)
                        return format_work_experience_list(work_experience)
                    except (ValueError, SyntaxError) as e:
                        print(f"Error parsing work experience string: {e}")
                        # Return a cleaned up version of the string
                        return clean_and_format_raw_text(cleaned_str)
            else:
                # If it's not a list format, return cleaned text
                return clean_and_format_raw_text(cleaned_str)
        
        return ""  # Return empty string if none of the above work
        
    except Exception as e:
        print(f"Error in format_work_experience: {e}")
        return str(work_experience_str)  # Return as-is if all else fails

def format_work_experience_list(work_experience):
    """Helper function to format a list of work experiences"""
    formatted_text = ""
    for job in work_experience:
        # Add job header
        formatted_text += f"\n{job.get('title', 'Unknown Position')} at {job.get('company', 'Unknown Company')}"
        if job.get('dates'):
            formatted_text += f" ({job['dates']})"
        if job.get('location'):
            formatted_text += f" - {job['location']}"
        formatted_text += "\n"
        
        # Add description if it exists
        if job.get('description'):
            # If description is a string of bullet points, keep them as is
            description = job['description']
            if isinstance(description, str):
                # Ensure proper spacing for bullet points
                description = description.replace('* ', '\n* ').strip()
                formatted_text += f"{description}\n"
            else:
                formatted_text += f"{str(description)}\n"
        
        formatted_text += "\n"  # Add extra space between jobs
    return formatted_text

def clean_and_format_raw_text(text):
    """Helper function to clean and format raw text"""
    # Remove unnecessary escape characters
    cleaned = text.replace('\\n', '\n').replace('\\t', '\t')
    # Remove multiple consecutive newlines
    cleaned = '\n'.join(line for line in cleaned.splitlines() if line.strip())
    return cleaned  # Add this return statement

def get_candidate_feedback(candidate_id):
    """
    Retrieve the flattened feedback for a specific candidate.
    
    Args:
        candidate_id (str): The ID of the candidate
        
    Returns:
        dict: The flattened feedback or None if not found
    """
    try:
        feedback_df = pd.read_csv("data/processed_resumes/feedback.csv")
        candidate_feedback = feedback_df[feedback_df['candidate_id'] == candidate_id]
        
        if candidate_feedback.empty:
            return None
        
        # Return the most recent feedback if multiple exist
        return candidate_feedback.sort_values('timestamp', ascending=False).iloc[0].to_dict()
        
    except FileNotFoundError:
        print("No feedback file found")
        return None
    except Exception as e:
        print(f"Error retrieving feedback: {e}")
        return None